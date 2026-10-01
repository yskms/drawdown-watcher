"""Tracks which events have already been notified, across daily runs.

Keyed by content (date, event_type, detail) rather than a position/count in
the event list -- see docs/architecture.md ("State (per ticker)") for why a
count is fragile here: a config change or a data source revising history
reshuffles what `state_machine.run` returns, and a count desyncs silently.

Only events within WINDOW_DAYS of a ticker's latest close are ever
candidates for notification, and each ticker's stored key set is pruned to
that same window -- relative to *that ticker's own* latest close, not a
date shared across tickers -- on every save (see `save_state`). This keeps
the state file from growing forever and keeps a reshuffle far back in
history from resurrecting or duplicating an old notification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WINDOW_DAYS = 45

EventKey = tuple[str, str, float | str | None]
# {"notified_event_keys": set[EventKey], "last_updated": str | None,
#  "last_row_count": int | None}
TickerState = dict


def event_key(event: dict) -> EventKey:
    """A content-based identity for an event, stable across re-runs.

    `detail` disambiguates events of the same type on the same date: a
    single-day crash can cross more than one configured level at once
    (LEVEL_TRIGGER), and UPTREND_EXIT can happen for either reason.
    """
    date = event["date"]
    date_iso = date.date().isoformat() if hasattr(date, "date") else str(date)
    if event["event"] == "LEVEL_TRIGGER":
        detail = event["level"]
    elif event["event"] == "UPTREND_EXIT":
        detail = event["reason"]
    else:
        detail = None
    return (date_iso, event["event"], detail)


def select_new_events(
    events: list[dict], notified_keys: set[EventKey], today: pd.Timestamp, window_days: int = WINDOW_DAYS
) -> list[dict]:
    """Events within the recency window that aren't already in notified_keys,
    in date order."""
    cutoff = today - pd.Timedelta(days=window_days)
    new = []
    for event in events:
        if event["date"] < cutoff:
            continue
        if event_key(event) in notified_keys:
            continue
        new.append(event)
    return new


def load_state(path: Path) -> dict[str, TickerState]:
    """{ticker: {"notified_event_keys": set, "last_updated": str | None,
    "last_row_count": int | None}}. Missing file means no ticker has ever
    been seen (first run for every ticker -- see `main.py`'s `process_ticker`)."""
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {
        ticker: {
            "notified_event_keys": {tuple(key) for key in entry["notified_event_keys"]},
            "last_updated": entry.get("last_updated"),
            "last_row_count": entry.get("last_row_count"),
        }
        for ticker, entry in raw.items()
    }


def save_state(
    path: Path,
    state: dict[str, TickerState],
    today_by_ticker: dict[str, pd.Timestamp],
    window_days: int = WINDOW_DAYS,
) -> None:
    """Persists `state`. Each ticker's keys are pruned to the last
    `window_days` *relative to that ticker's own entry in `today_by_ticker`*
    -- using a single date shared across tickers would prune a lagging
    ticker's keys using a more recent cutoff than its own window actually
    allows, and a key pruned too early comes back as a duplicate "new"
    notification next run.

    A ticker missing from `today_by_ticker` (its fetch failed this run, so
    there's nothing trustworthy to measure a window from) is saved as-is,
    unpruned, with its previous `last_updated` kept -- this also means a
    ticker's already-sent notifications from earlier in the same run are
    never lost just because a *different* ticker failed (see `main.py`,
    which always calls this once per run regardless of per-ticker errors).

    Every ticker ever seen is kept, even with an empty key set (a ticker
    quiet for `window_days` is the normal case for this tool) -- dropping
    empty entries previously meant a quiet ticker vanished from `state` and
    came back as a false "first run" on the very next day, which silently
    *suppressed* its next real notification instead of sending it (see
    `main.py`'s `process_ticker`: a ticker absent from `state` is treated as
    never seen before, and seeds rather than notifies). A ticker removed
    from config lingering here afterward is accepted as the lesser risk --
    note that this means re-adding a removed ticker later is *not* treated
    as a first run (its old entry is still present), so if it's been out of
    config for a while, whatever happened in its last `window_days` arrives
    as a one-time batch of notifications rather than being seeded quietly.
    Rare enough in practice not to be worth more than this note.
    """
    raw = {}
    for ticker, entry in state.items():
        today = today_by_ticker.get(ticker)
        if today is None:
            kept = entry["notified_event_keys"]
            last_updated = entry.get("last_updated")
        else:
            cutoff = (today - pd.Timedelta(days=window_days)).date().isoformat()
            kept = {key for key in entry["notified_event_keys"] if key[0] >= cutoff}
            last_updated = today.isoformat()
        raw[ticker] = {
            "notified_event_keys": sorted(kept),
            "last_updated": last_updated,
            "last_row_count": entry.get("last_row_count"),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(raw, f, indent=2)
