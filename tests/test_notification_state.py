import pandas as pd

from src.notification_state import event_key, load_state, save_state, select_new_events


def _event(date: str, event: str, **extra) -> dict:
    return {"date": pd.Timestamp(date), "event": event, **extra}


def _entry(keys: set) -> dict:
    return {"notified_event_keys": keys, "last_updated": None}


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

    save_state(path, {"SPXL": _entry(keys)}, {"SPXL": today})
    loaded = load_state(path)

    assert loaded["SPXL"]["notified_event_keys"] == keys
    assert loaded["SPXL"]["last_updated"] == today.isoformat()


def test_save_state_prunes_keys_outside_window(tmp_path):
    path = tmp_path / "state.json"
    today = pd.Timestamp("2026-03-10")
    keys = {("2026-01-01", "DRAWDOWN_MODE_ENTER", None), ("2026-03-05", "RECOVERY_CONFIRMED", None)}

    save_state(path, {"SPXL": _entry(keys)}, {"SPXL": today}, window_days=45)
    loaded = load_state(path)

    assert loaded["SPXL"]["notified_event_keys"] == {("2026-03-05", "RECOVERY_CONFIRMED", None)}


def test_save_state_prunes_each_ticker_by_its_own_date(tmp_path):
    # A lagging ticker's cutoff must come from its own `today`, not another
    # ticker's -- otherwise a lagging ticker's still-in-window key gets
    # pruned early by a less-lagging ticker's more recent cutoff, and the
    # same event is notified again next run.
    path = tmp_path / "state.json"
    key_close_to_cutoff = ("2026-01-20", "DRAWDOWN_MODE_ENTER", None)
    state = {
        "LAGGING": _entry({key_close_to_cutoff}),
        "CURRENT": _entry({("2026-02-01", "DRAWDOWN_MODE_ENTER", None)}),
    }
    today_by_ticker = {
        "LAGGING": pd.Timestamp("2026-03-01"),  # cutoff: 2026-01-15 -- key survives
        "CURRENT": pd.Timestamp("2026-03-10"),  # cutoff: 2026-01-24 -- would prune the key above
    }

    save_state(path, state, today_by_ticker, window_days=45)
    loaded = load_state(path)

    assert loaded["LAGGING"]["notified_event_keys"] == {key_close_to_cutoff}


def test_save_state_keeps_ticker_unpruned_when_missing_from_today_by_ticker(tmp_path):
    # A ticker whose fetch failed this run has no trustworthy `today` --
    # it must be saved as-is rather than pruned against some other date.
    path = tmp_path / "state.json"
    old_key = ("2026-01-01", "DRAWDOWN_MODE_ENTER", None)
    state = {"SPXL": {"notified_event_keys": {old_key}, "last_updated": "2026-01-01T00:00:00"}}

    save_state(path, state, {}, window_days=45)
    loaded = load_state(path)

    assert loaded["SPXL"]["notified_event_keys"] == {old_key}
    assert loaded["SPXL"]["last_updated"] == "2026-01-01T00:00:00"


def test_save_state_drops_ticker_with_no_keys_left(tmp_path):
    path = tmp_path / "state.json"
    today = pd.Timestamp("2026-03-10")
    old_key = {("2026-01-01", "DRAWDOWN_MODE_ENTER", None)}

    save_state(path, {"SPXL": _entry(old_key)}, {"SPXL": today}, window_days=45)
    loaded = load_state(path)

    assert "SPXL" not in loaded


def test_load_state_missing_file_returns_empty(tmp_path):
    assert load_state(tmp_path / "missing.json") == {}
