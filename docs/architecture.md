<p align="center"><b>English</b> | <a href="architecture.ja.md">日本語</a></p>

# Architecture

## Overview

```text
Market Data (full history, re-fetched)
    │
    ▼
Daily Scheduler
    │
    ▼
Drawdown Engine (state_machine.run, replayed from scratch)
    │
    ├── 52-week high
    ├── Reference high (lock)
    ├── Drawdown / level checks
    ├── Recovery confirm / undercut
    └── Uptrend tracking after a bottom call (hold / sell line)
    │
    ▼
Diff against "already notified" cursor
    │
    ▼
Notification
```

Runs once per day, after the US market closes. The goal is years of
low-cost, close-to-zero-maintenance operation, not low latency.

## Modules (`src/`)

- `market_data.py` — fetches daily closing prices for a ticker.
- `drawdown.py` — pure drawdown calculation (52-week high, reference
  high, drawdown %). No I/O.
- `state_machine.py` — the NORMAL ⇄ DRAWDOWN transitions (DRAWDOWN_MODE_ENTER
  / LEVEL_TRIGGER / RECOVERY_CONFIRMED / RECOVERY_UNDERCUT / RENEWED_DECLINE
  / NORMAL_RESUME), replayed over a full price series. There is no
  separate "RECOVERY" mode — confirming or undercutting a recovery is
  tracked as a sub-state within DRAWDOWN (see docs/strategy.md). On top
  of that, `track_uptrend` follows each bottom call's rebound
  (UPTREND_ARMED / UPTREND_EXIT) independently of those modes, since a
  worthwhile uptrend runs well past NORMAL_RESUME.
- `main.py` — the daily production runner: fetches fresh prices, runs the
  state machine, diffs against `notification_state.py`, and emails new
  events (see Statelessness and State, below).
- `notification_state.py` — tracks which events have already been
  notified, across daily runs (see State, below).
- `status.py` — derives the heartbeat's per-ticker "current stage"
  summary from a day's events plus the price series.
- `event_format.py` — human-readable formatting of an event, shared by
  `backtest.py` (printed) and `notifier.py` (emailed).
- `notifier.py` — sends a notification per new event, plus errors and
  periodic heartbeats, by email (SMTP; see `.env.example`).
- `config.py` — loads `config/*.yaml` into `TickerConfig`, shared by
  `backtest.py` and `main.py`.
- `backtest.py` — runs the state machine against each configured ticker's
  full price history, printing every event it would have fired.
- `threshold_sweep.py` — a tuning aid: sweeps candidate `watch_threshold`
  values to show how often Drawdown Mode would have fired historically,
  and prints the recovery timeline for a chosen threshold. Used to tune
  per-ticker values (see docs/strategy.md).
- `exit_sweep.py` — a tuning aid for the uptrend exit: compounds each
  bottom-call-to-exit round trip under several `trail_from_peak` values,
  next to "sell at 2x" and "never sell" baselines.
- `synthetic.py` — builds a long synthetic history for a leveraged ETF from
  its underlying index (leverage, borrowing cost, expense ratio), so the
  tuning tools can be run with `--synthetic` against decades the ETF
  itself never traded through.

Backtesting and live monitoring call the exact same `state_machine.run` —
only the data source and what happens with the resulting events (print vs.
notify) differ. This is load-bearing, not incidental (see Statelessness
below): it's what keeps a backtested decision trustworthy in production.

## Statelessness and stock splits

`state_machine.run` is a pure function of (full price history, config) —
it has no memory of its own between calls. In production this is replayed
from scratch every day, over the ticker's *entire* price history, rather
than persisting an in-progress `reference_high` / `mode` across days.

This is deliberate, not just simple: a leveraged ETF splits or reverse-splits
far more often than a plain index fund (SOXL and TECL both did in 2021).
Every price history API adjusts past prices for splits after the fact — so
a `reference_high` saved yesterday, before a split, would be silently wrong
today, producing a bogus drawdown the next time it's compared against a
post-split close. Recomputing from the freshly-fetched (correctly
adjusted) series every time sidesteps this entirely: there's no stale
locked value to go stale. The ~4,500 rows of daily data per ticker make
full replay cheap enough that this costs nothing meaningful.

Rows with a missing close are dropped before replay (`load_close`). A NaN
close compares false against every threshold, so instead of failing it
would silently skip that day's checks — and data fetched during trading
hours can end in exactly such a not-yet-final row.

## State (per ticker)

Only "what's already been notified" needs to persist (`src/notification_state.py`).
A plain count of events seen so far (`events_notified_count`, treating
`events[count:]` as new) would be tempting but fragile: changing a ticker's
config, or the data source revising or extending its history, reshuffles
`run()`'s output and silently desyncs the count — the exact kind of break
that should never happen silently on a system meant to run untouched for
years. Instead, "already notified" is keyed by something content-based —
`(date, event_type, detail)`, where `detail` is the level for
`LEVEL_TRIGGER` (a single-day crash can cross more than one level at once)
or the reason for `UPTREND_EXIT`, and `None` otherwise — and only events
within the last 45 days are ever notification candidates. The stored key
set is pruned to that same window on every save, so a reshuffle further
back in history can't resurrect or duplicate an old notification, and the
state file never grows unbounded.

```text
ticker
notified_event_keys    # {(date, event_type, detail), ...}, pruned to the last 45 days
last_updated
```

Either way, everything else (mode, locked reference high, lowest close,
confirmed low, …) lives only inside that day's `run()` call, derived
fresh from price history + config — never stored. The one exception is the
heartbeat's "current stage" summary (`src/status.py`), which re-derives
mode/drawdown%/uptrend peak from `run()`'s event list plus the price series
after the fact, rather than exposing the state machine's internal loop
variables.

This module's config/state are passed in as plain file paths (`--config`,
`--state`); where those paths actually live — a local file today, S3/SSM
once deployed — is a Phase 4 (deployment) decision, kept separate from this
diffing logic.

## Configuration

Monitoring logic and per-ticker rules are separate — adding a new ticker
should never require a code change. See
[config/config.example.yaml](../config/config.example.yaml) for the format
(its values are illustrative). The real config is meant to live outside
this repo and be passed in with `--config`.

## Notifications

Sent by email (SMTP; see `.env.example` and `notifier.py`). One per new
event out of `state_machine.run`, plus:

- Error (data fetch / job failure — including a stuck or truncated price
  history: `main.py` rejects a ticker's data as unhealthy if its latest
  close is more than `STALE_AFTER_DAYS` old, or if its row count drops
  sharply from the previous run, rather than silently computing events
  from bad data).
- Heartbeat (sent every run — currently daily, since nothing yet
  distinguishes a "quiet" run from a "notify" one — confirms the system is
  still alive; expected to otherwise go silent for long stretches, so it's
  the main defense against a silent failure going unnoticed for years). It
  also states each ticker's current stage in concrete numbers, as of its
  latest close date — in Drawdown Mode, how far down and the next level;
  while tracking an uptrend, whether it's still in the hold-to-2x stage or
  armed, the peak and its date, the current distance from it, and the sell
  line price. The user rarely looks at the market, so "what was I supposed
  to do?" has to be answerable from the latest message alone. Whether a
  daily heartbeat is too chatty (and whether to make that configurable) is
  open — revisit once Phase 4 scheduling is decided, since the scheduler
  could just as easily control the frequency from outside `main.py`.

A ticker's very first run (or one recovering from a lost state file) seeds
whatever's within the notification window as already-known instead of
emailing it, since none of it just happened today (see
`src/notification_state.py`, `src/main.py` `process_ticker`).

## Deployment

A cloud scheduler running once a day, **well after the US market closes**
(target undecided as of Phase 3 — e.g. AWS EventBridge + Lambda, or a
scheduled GitHub Actions workflow in the private repo). This margin isn't
optional: during market hours, yfinance can return a non-final price for
the current day that isn't NaN, so `dropna()` (see "Statelessness and stock
splits") does not protect against running too early — an event computed
from an intraday price would be notified and recorded as already-sent,
with no way to retract it once the real close comes in lower or higher.

Secrets (SMTP credentials, API keys) are injected via environment
variables / a secrets manager, never committed — see
[.env.example](../.env.example). Two more things depend on the deployment
target, beyond secrets:

- Where `main.py`'s `--config`/`--state` paths resolve to (a local file,
  S3, SSM, …).
- Where `market_data.py`'s price cache (`data/`) is writable from — it
  writes on every refresh, which a read-only runtime (e.g. Lambda's
  deployment package) won't allow; `DATA_DIR` would need to become
  configurable (e.g. to `/tmp`, which Lambda does provide, non-persistent)
  rather than the hardcoded repo-relative path it is today.
