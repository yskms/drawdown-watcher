"""Tracks which events have already been notified, across daily runs.

Keyed by content (date, event_type, detail) rather than a position/count in
the event list -- see docs/architecture.md ("State (per ticker)") for why a
count is fragile here: a config change or a data source revising history
reshuffles what `state_machine.run` returns, and a count desyncs silently.

Only events within WINDOW_DAYS of the latest close are ever candidates for
notification, and the stored key set is pruned to the same window on every
save. This keeps the state file from growing forever and keeps a reshuffle
far back in history from resurrecting or duplicating an old notification.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

WINDOW_DAYS = 45

EventKey = tuple[str, str, float | str | None]


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


def load_state(path: Path) -> dict[str, set[EventKey]]:
    """{ticker: notified_keys}. Missing file means no state yet (first run)."""
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {
        ticker: {tuple(key) for key in entry["notified_event_keys"]}
        for ticker, entry in raw.items()
    }


def save_state(path: Path, state: dict[str, set[EventKey]], today: pd.Timestamp, window_days: int = WINDOW_DAYS) -> None:
    """Persists `state`, pruning each ticker's keys to the recency window
    first so the file doesn't grow forever."""
    cutoff = (today - pd.Timedelta(days=window_days)).date().isoformat()
    raw = {
        ticker: {
            "notified_event_keys": sorted(
                key for key in keys if key[0] >= cutoff
            ),
            "last_updated": today.isoformat(),
        }
        for ticker, keys in state.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(raw, f, indent=2)
