import json

import pandas as pd

from src.notification_state import event_key, load_state, save_state, select_new_events


def _event(date: str, event: str, **extra) -> dict:
    return {"date": pd.Timestamp(date), "event": event, **extra}


def test_event_key_disambiguates_same_day_level_triggers():
    e1 = _event("2026-03-01", "LEVEL_TRIGGER", level=-40)
    e2 = _event("2026-03-01", "LEVEL_TRIGGER", level=-50)

    assert event_key(e1) != event_key(e2)


def test_event_key_disambiguates_uptrend_exit_reason():
    undercut = _event("2026-03-01", "UPTREND_EXIT", reason="undercut")
    trail = _event("2026-03-01", "UPTREND_EXIT", reason="trail")

    assert event_key(undercut) != event_key(trail)


def test_select_new_events_excludes_already_notified():
    today = pd.Timestamp("2026-03-10")
    events = [_event("2026-03-01", "DRAWDOWN_MODE_ENTER"), _event("2026-03-05", "RECOVERY_CONFIRMED")]
    notified = {event_key(events[0])}

    new = select_new_events(events, notified, today)

    assert [e["event"] for e in new] == ["RECOVERY_CONFIRMED"]


def test_select_new_events_excludes_events_outside_window():
    today = pd.Timestamp("2026-03-10")
    old_event = _event("2026-01-01", "DRAWDOWN_MODE_ENTER")

    new = select_new_events([old_event], set(), today, window_days=45)

    assert new == []


def test_save_and_load_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    today = pd.Timestamp("2026-03-10")
    keys = {("2026-03-01", "DRAWDOWN_MODE_ENTER", None), ("2026-03-02", "LEVEL_TRIGGER", -40.0)}

    save_state(path, {"SPXL": keys}, today)
    loaded = load_state(path)

    assert loaded == {"SPXL": keys}


def test_save_state_prunes_keys_outside_window(tmp_path):
    path = tmp_path / "state.json"
    today = pd.Timestamp("2026-03-10")
    keys = {("2026-01-01", "DRAWDOWN_MODE_ENTER", None), ("2026-03-05", "RECOVERY_CONFIRMED", None)}

    save_state(path, {"SPXL": keys}, today, window_days=45)
    loaded = load_state(path)

    assert loaded == {"SPXL": {("2026-03-05", "RECOVERY_CONFIRMED", None)}}


def test_load_state_missing_file_returns_empty(tmp_path):
    assert load_state(tmp_path / "missing.json") == {}
