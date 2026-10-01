<p align="center"><b>English</b> | <a href="strategy.ja.md">日本語</a></p>

# Strategy

## Why

Instead of checking the market every day for a buying opportunity,
Drawdown Watcher watches for the kind of large, infrequent drawdown that
matters: a financial crisis, a crash like 2020 or 2022, a sharp
tariff-driven selloff like 2025, or whatever the next one turns out to be.

It does not try to predict these events. It mechanically monitors rules
that were decided in advance, during calm markets — not in the middle of
a panic.

The person using this doesn't watch the market day to day, so the whole
point is to be told when it's worth paying attention. That's four
distinct things, not one:

1. **Pay attention** — a real drawdown has started (`DRAWDOWN_MODE_ENTER`,
   or `RENEWED_DECLINE` if it flares up again mid-episode; see below).
2. **Maybe getting interesting** — it's reached a deeper configured level
   (`LEVEL_TRIGGER`) — informational, no action implied.
3. **It bottomed** — a confirmed rebound off the low (`RECOVERY_CONFIRMED`)
   — the signal meant to prompt buying.
4. **Keep holding / the uptrend looks over** — after a bottom call, the
   rebound is followed until it has clearly run its course
   (`UPTREND_ARMED`, `UPTREND_EXIT`; see "After the bottom", below) — the
   signal meant to prompt selling, and just as importantly, *not* selling
   before then.

Catching the exact bottom is explicitly not a goal of (3) — reacting
10-20% off the low is completely fine. What matters is that (3) is
trustworthy: a false "it bottomed" right before the real leg down is the
one failure mode worth designing hard against, more than being early or
late.

## Reference high

During normal conditions, the reference high is the **52-week highest
closing price**. It updates automatically as new highs are made.

```text
52-week high: $230
Current close: $207

drawdown = 207 / 230 - 1 = -10.0%
```

Only daily closes are used, not intraday prices. This filters out
single-day spikes, keeps the system easy to backtest, and reduces API
calls — real-time precision isn't needed to catch a multi-month drawdown.

A ticker's first 52 weeks of trading don't count as a real reference high
— a listing price isn't a peak, and treating it as one produces a fake
drawdown right out of the gate (this is what caused SPXL's spurious entry
11 trading days after its 2008 listing, which coincided with the 2008
crash itself). `rolling_high`/`all_time_high` return unknown (`NaN`) until
a ticker has a full 52 weeks of history, and the state machine simply
doesn't evaluate entry during that warmup.

## Drawdown mode

A rolling 52-week high has a problem: in a selloff that lasts more than a
year, the pre-crash high eventually rolls out of the 52-week window, and
the reference price would creep upward even though the market never
recovered.

To avoid that, once a ticker's configured `watch_threshold` is reached,
the reference high is **locked** at its current value and the ticker
enters Drawdown Mode. All further drawdown levels are measured against
that locked value, not a moving 52-week window, until recovery.

```text
52-week high: $200
watch_threshold: -20%

Close: $160  →  -20% reached  →  Reference High locked at $200
```

## How deep: catch the crash, not the correction

The goal isn't to catch every dip — missing some is fine. The intended
target is the kind of drawdown that happens once every few years, not the
ordinary corrections that happen almost every year.

That has a practical consequence for how deep `watch_threshold` has to be:
a 3x leveraged ETF routinely has 20-30% pullbacks that have nothing to do
with a real crash, so a multi-year cadence needs thresholds far deeper
than the "-10% / -20%" range that would make sense for a broad index fund.
How deep exactly is per-ticker tuning, not part of the design: use
`src/threshold_sweep.py` to see how often Drawdown Mode would have fired
historically at each candidate depth, and `src/backtest.py` to inspect the
resulting episodes. The values in `config/config.example.yaml` are
illustrative only.

Some cautions when tuning:

- Each ticker only has a handful of qualifying crashes in its history, so
  it's easy to overfit to them. Check that nudging a threshold by a few
  points doesn't change which crashes get caught.
- Leveraged ETFs have short histories (most launched after 2008), and the
  years since then were an unusually strong bull market. `--synthetic`
  (on `src/backtest.py`, `src/threshold_sweep.py` and `src/exit_sweep.py`)
  replays a 3x-daily-rebalanced series built from the underlying index
  instead (`src/synthetic.py`; back to 1960 for the S&P 500), covering
  1973-74, 1987, 2000-2002, the full 2008 crash, and long sideways markets.
  Check both: a rule that only works on the ETF's own history is fitted to
  one bull market.
- Thresholds live in config, so they can be re-tuned later against fresh
  data without a code change.

## Levels

Each ticker has its own set of drawdown levels below `watch_threshold`,
tracked purely for situational awareness while in Drawdown Mode — they
are not the actionable signal (see Recovery, below), so they don't gate
on a multi-day confirmation. An earlier idea was to require a level to
stay breached for 3-5 trading days before confirming it, to filter out
single-day noise. Backtesting real crash episodes ruled that out: how
long a level actually stayed breached ranged from 1 trading day to over
500, with no consistent pattern — a fixed-day rule would have both
delayed real notifications and, in some cases (a level breached for only
2 days before bouncing), suppressed one outright.

```yaml
SPXL:
  watch_threshold: -30
  levels: [-40, -50, -60]  # illustrative values
```

## Recovery

This is tier 3, "it bottomed" — the one signal meant to prompt action, so
it has to be trustworthy more than it has to be fast.

A first version just fired once a rebound of `recovery_threshold` off the
running low was reached. That turned out to be backwards for a 3x
leveraged ETF: backtesting real crash episodes (SPXL/SOXL/TECL in 2008,
2011, 2020, 2022) showed a +15% dead-cat bounce clearing in a day or two
is common in the middle of an ongoing crash, not a sign it's over — in
the 2020 crash, SPXL's first +15% bounce came just days into the selloff,
and it then fell another ~60% before the real low. Worse, since it only fired
once per episode, the single early notification was also the *only* one
— the real bottom, months later, passed in silence. For someone who
isn't watching, that's the worst possible failure: told "it's over," then
it keeps crashing with no further word.

So confirmation now requires two things together, and can re-fire:

- **Both a size and a time condition**: price must be `recovery_threshold`
  (+15%) above the running low, *and* that low must not have been undercut
  for `recovery_confirm_days` (10) trading days. Size alone isn't enough —
  a sharp bounce right off a fresh low doesn't yet mean anything.
- **Confirmation is revocable**: if a close later undercuts an already-
  confirmed low, that confirmation is revoked (`RECOVERY_UNDERCUT`, "the
  last bottom call was wrong, it's still falling") and has to re-earn
  confirmation from the new, lower low.

Across every historical episode in the backtest, the *last* confirmation
in an episode was never subsequently undercut — i.e. it always landed
after the genuine low, which is the property this is meant to guarantee.
Clean V-shaped crashes (2018, 2020, 2025) typically confirm in one shot;
grinding ones (2011, 2022) can cycle through 2-3 confirm → undercut rounds
before landing on the real bottom. That can mean a handful of notifications
over a year or two in the worst episodes — an accepted cost, given the
alternative is a confident, false "it's over."

`recovery_threshold: 15` and `recovery_confirm_days: 10` (the defaults)
are starting points, not results tuned per ticker — see the overfitting
caveat above.

## Staying alert during a long episode

A grinding decline can stay in Drawdown Mode for years (SOXL's 2022 crash
didn't fully resume until April 2026) without the reference high ever
being reached. Left alone, that would mean nothing — no fresh "pay
attention" — for however much further damage happens in the meantime,
since Drawdown Mode doesn't resume real 52-week tracking until it's over.

The first version of this re-fired every time price crossed back below
`watch_threshold` relative to the original (ancient, locked) reference
high. That was far too noisy in practice: it fired repeatedly on ordinary
back-and-forth near that line — including while still inside the very
crash that caused entry — and kept firing well after a real
`RECOVERY_CONFIRMED` had already happened, both before and after the
confirmed bottom. In a backtest across several leveraged and unleveraged
ETFs, it fired over a dozen times per ticker, and almost none of them were
a genuinely new drawdown.

So this is now scoped to only matter *after* a `RECOVERY_CONFIRMED`: once
a bottom is confirmed, the high reached since then is tracked separately,
and a fresh drop of `watch_threshold`% from *that* high — not the
original reference high — is what re-fires the tier-1 "pay attention"
signal (`RENEWED_DECLINE`). Before any recovery has been confirmed, a dip
back toward the original reference high is just the same ongoing crash,
not a new one, so it's never reported as "renewed."

This is treated as the start of a new sub-episode: reference high relocks
to that post-recovery high, and level/recovery tracking resets, so the
usual three-tier flow (pay attention → levels → confirmed bottom) plays
out again for it — rather than requiring price to fall all the way back
to the *original* crash's reference high (which, on a leveraged ETF, can
be most of an order of magnitude away) before anything is reported again.
Re-backtesting this version against the same tickers: no false fires,
and one true one — SOXL, correctly catching a genuinely separate, serious
drawdown in early 2025 that the 2022 episode's own reference high was too
far away to ever register (price never undercut the 2022 low, so the
Recovery tracking above wouldn't have caught it either).

The relocked reference high only governs level/recovery tracking for the
new sub-episode — it is *not* what decides when Drawdown Mode itself
ends. `NORMAL_RESUME` only fires once price regains the *original*
episode-starting reference high, tracked separately and never relocked.
Gating resume on the (lower) relocked value instead would be a real bug:
since the original, higher reference high can still easily be within the
52-week window, resuming there would hand a fresh `reference_high_series`
lookup a stale, much higher value the very next day — immediately
re-triggering a spurious `DRAWDOWN_MODE_ENTER` while price is actually
still in the middle of genuinely recovering. This doesn't show up in the
current backtest only because, by the time SOXL's 2025 sub-episode
resolved, the original 2022 high had already rolled out of the window —
but it's exactly the failure mode that would otherwise hit a
crash-rebound-crash year like 2008, which is precisely the kind of market
this is meant to catch.

## After the bottom: holding the uptrend

A bottom call is only half of it. The other common mistake is selling a
good entry far too early — buying near the low, selling at 2x, and
watching it go on to 5x. For someone who rarely looks at the market,
there's a second problem: opening the brokerage account months later, it's
hard to even reconstruct the rule — where was the peak, how far was it
supposed to be allowed to fall?

So after a bottom call, the tool keeps following the rebound and states
the rule in concrete numbers. Tracking starts at the `RECOVERY_CONFIRMED`
close (the "base"; the actual purchase price isn't needed, so no personal
position data is involved), and works in two stages:

1. **Hold until `hold_until_multiple` (2x) of the base.** No price-based
   exit at all before that: a young uptrend is as choppy as a bottom, and
   any trailing exit armed this early gets shaken out repeatedly.
   Reaching 2x fires `UPTREND_ARMED` — deliberately at the point where the
   urge to take the profit is strongest, as "from here on, the rule is:
   hold until it falls `trail_from_peak`% from its peak."
2. **After that, exit on a `trail_from_peak`% drop from the highest close
   since the base** (`UPTREND_EXIT`, reason `trail`) — "the uptrend looks
   over." Never the top itself; giving back part of the gain is the price
   of not being shaken out of the rest of it.

One exception in stage 1: if the bottom call itself is revoked
(`RECOVERY_UNDERCUT`) before 2x, tracking ends (`UPTREND_EXIT`, reason
`undercut`) — the premise for holding is gone. The next bottom call starts
a new round.

Tracking is independent of Drawdown Mode: a worthwhile uptrend usually
runs far past the episode's original reference high (`NORMAL_RESUME`),
and keeps being followed past it.

What backtesting showed, comparing exit rules by compounding each round
trip from bottom call to exit (cash in between):

- **Selling early costs the most.** A shallow trailing exit from the start
  did worse than simply selling at 2x, and far worse than holding longer —
  it gets shaken out in the choppy early phase and in grinding bear
  markets.
- **Holding to 2x before arming the trailing exit** removed most of that
  churn, and on leveraged ETFs beat both selling at 2x and a plain
  trailing exit.
- **But "hold to 2x no matter what" is catastrophic over long history.**
  On the ETFs' own (post-2008) history it looked best of all; on synthetic
  history, a bottom call made during 2000-2002 was held all the way down
  — for decades, or to near zero for a semiconductor 3x fund — waiting for
  a 2x that never came. Exiting when the bottom call is revoked fixes this
  at the cost of small, bounded losses (typically -10 to -30%) on false
  bottom calls, which can come several in a row in a bad year (2008).
- Results are sensitive to the exact `trail_from_peak`, since each ticker
  only has a handful of full cycles. Treat it as a rough range, and check
  it against both the real and the synthetic history.

Between notifications, the periodic heartbeat states where each tracked
ticker stands — e.g. "holding, armed at 2x; peak $245.10 (2026-08-14),
now -9.7% from it; sell line $171.57, 22.5% further down" — so the answer
to "what was I supposed to do?" is always in the latest message, not in
memory.

## What this is not

- Not a crash predictor.
- Not investment advice or a position sizer. Every signal is a rule its
  user configured in advance; the tool only applies it and states it in
  concrete numbers.
- Not tied to any specific ticker — thresholds are configuration, not code.
