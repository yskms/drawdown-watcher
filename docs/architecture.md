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
    └── Recovery confirm / undercut
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
  tracked as a sub-state within DRAWDOWN (see docs/strategy.md).
- `notifier.py` — sends a notification per new event, plus errors and
  periodic heartbeats.
- `backtest.py` — runs the state machine against each configured ticker's
  full price history, printing every event it would have fired.
- `threshold_sweep.py` — a tuning aid: sweeps candidate `watch_threshold`
  values to show how often Drawdown Mode would have fired historically,
  and prints the recovery timeline for a chosen threshold. Used to tune
  per-ticker values (see docs/strategy.md).

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

## State (per ticker)

Only "what's already been notified" needs to persist. **Open design
question for the start of Phase 3** — a plain count of events seen so far
(`events_notified_count`, treating `events[count:]` as new) is tempting
but fragile: changing a ticker's config, or the data source revising or
extending its history, reshuffles `run()`'s output and silently
desyncs the count — the exact kind of break that should never happen
silently on a system meant to run untouched for years. A safer shape to
decide on before building this: key "already notified" by something
content-based — e.g. `(date, event_type, level_or_threshold)` — and only
ever consider events from, say, the last 30 days as notification
candidates, so a reshuffle further back in history can't resurrect or
duplicate old notifications.

```text
ticker
notified_event_keys    # e.g. {(date, event_type, level), ...}, recent window only
last_updated
```

Either way, everything else (mode, locked reference high, lowest close,
confirmed low, …) lives only inside that day's `run()` call, derived
fresh from price history + config — never stored.

## Configuration

Monitoring logic and per-ticker rules are separate — adding a new ticker
should never require a code change. See
[config/config.example.yaml](../config/config.example.yaml) for the format
(its values are illustrative). The real config is meant to live outside
this repo and be passed in with `--config`.

## Notifications

One per new event out of `state_machine.run`, plus:

- Error (data fetch / job failure)
- Heartbeat (periodic, confirms the system is still alive — expected to
  otherwise go silent for long stretches, so it's the main defense
  against a silent failure going unnoticed for years)

## Deployment

A cloud scheduler (e.g. AWS EventBridge + Lambda) running once a day.
Secrets (API keys, webhook URLs, notification tokens) are injected via
environment variables / a secrets manager, never committed — see
[.env.example](../.env.example).
