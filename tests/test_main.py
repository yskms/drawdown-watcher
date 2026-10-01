import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import main as main_module
from src.notification_state import load_state as real_load_state


def _close_series(last_price: float, prior_price: float = 100.0, days: int = 400, end=None) -> pd.Series:
    """`days` calendar days ending at `end` (default: today), all `prior_price`
    except the last day. `days=400` clears rolling_high's 364-day warmup, so
    the last day gets a real reference high instead of NaN."""
    end = end or pd.Timestamp.now().normalize()
    index = pd.date_range(end=end, periods=days, freq="D")
    prices = [prior_price] * (days - 1) + [last_price]
    return pd.Series(prices, index=index)


_CFG = {"watch_threshold": -20, "levels": [], "recovery_threshold": 10, "recovery_confirm_days": 2}


def _state_entry(last_row_count=None) -> dict:
    return {"notified_event_keys": set(), "last_updated": None, "last_row_count": last_row_count}


def test_process_ticker_notifies_new_events_when_not_first_run(monkeypatch):
    close = _close_series(last_price=79.0)  # dd=-21% -- a DRAWDOWN_MODE_ENTER today
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {"SPXL": _state_entry()}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]
    assert seeded == []
    assert len(notified_calls) == 1
    assert today == close.index[-1]
    assert len(state["SPXL"]["notified_event_keys"]) == 1


def test_process_ticker_keeps_keys_for_events_sent_before_a_later_failure(monkeypatch):
    # Regression guard: keys must be recorded event-by-event, not in a
    # separate pass after all notify_event calls -- otherwise a failure on
    # the Nth event of a ticker would also unrecord the first N-1, already
    # successfully sent, causing them to be re-sent next run too.
    index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=400, freq="D")
    prices = [100.0] * 396 + [79.0, 70.0, 65.0, 60.0]  # ENTRY, then a LEVEL_TRIGGER(-30)
    close = pd.Series(prices, index=index)
    cfg = {**_CFG, "levels": [-30]}
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)

    calls = []

    def flaky_notify_event(ticker, event):
        calls.append(event)
        if len(calls) == 2:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(main_module, "notify_event", flaky_notify_event)

    state = {"SPXL": _state_entry()}  # not first run -- both events go through notify_event
    with pytest.raises(RuntimeError, match="smtp down"):
        main_module.process_ticker("SPXL", cfg, state, dry_run=False)

    assert [e["event"] for e in calls] == ["DRAWDOWN_MODE_ENTER", "LEVEL_TRIGGER"]
    recorded_event_types = {key[1] for key in state["SPXL"]["notified_event_keys"]}
    assert recorded_event_types == {"DRAWDOWN_MODE_ENTER"}  # the one that failed is not recorded


def test_process_ticker_notifies_a_quiet_ticker_after_45_quiet_days(monkeypatch):
    # Regression guard for the bug where an empty-but-known ticker (the
    # normal state for this tool between episodes) got dropped from `state`
    # by save_state's old "drop if empty" behavior, came back as a false
    # "first run" the next day, and had its next real event silently seeded
    # instead of sent -- forever, since every quiet day repeated the cycle.
    close = _close_series(last_price=79.0)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    # A ticker that's been through at least one save_state cycle with no
    # pending events still has an entry -- it is NOT absent from state.
    state = {"SPXL": _state_entry()}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]
    assert seeded == []
    assert len(notified_calls) == 1


def test_process_ticker_seeds_past_events_but_still_notifies_todays_on_first_run(monkeypatch):
    close = _close_series(last_price=79.0)  # one DRAWDOWN_MODE_ENTER, dated today
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {}  # SPXL has never been seen before
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]  # dated today -- sent regardless
    assert seeded == []
    assert len(notified_calls) == 1
    assert len(state["SPXL"]["notified_event_keys"]) == 1  # recorded either way, so it won't resurface


def test_process_ticker_seeds_an_older_event_without_notifying_on_first_run(monkeypatch):
    # Same as above, but the event is a few days old relative to `today` --
    # exercises the actual seed-without-notifying path (date != today).
    index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=400, freq="D")
    prices = [100.0] * 396 + [79.0, 80.0, 80.0, 80.0]  # entry 3 days ago, no further event since
    close = pd.Series(prices, index=index)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert notified == []
    assert [e["event"] for e in seeded] == ["DRAWDOWN_MODE_ENTER"]
    assert notified_calls == []


def test_process_ticker_dry_run_does_not_call_notify_event(monkeypatch):
    close = _close_series(last_price=79.0)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {"SPXL": _state_entry()}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=True)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]  # still reported, for dry-run printing
    assert notified_calls == []  # but never actually emailed


def test_process_ticker_raises_on_stale_data(monkeypatch):
    stale_close = _close_series(last_price=100.0, end=pd.Timestamp.now().normalize() - pd.Timedelta(days=30))
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: stale_close)

    with pytest.raises(RuntimeError, match="data may be stuck"):
        main_module.process_ticker("SPXL", _CFG, {}, dry_run=False)


def test_process_ticker_raises_on_row_count_drop(monkeypatch):
    close = _close_series(last_price=100.0, days=400)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    state = {"SPXL": _state_entry(last_row_count=1000)}  # was 1000, now 400

    with pytest.raises(RuntimeError, match="row count dropped"):
        main_module.process_ticker("SPXL", _CFG, state, dry_run=False)


def test_process_ticker_keeps_last_known_good_row_count_after_a_bad_fetch(monkeypatch):
    # Regression guard: the baseline must come from `state`, not from
    # re-reading the (already overwritten by fetch_history) price cache --
    # otherwise a truncated fetch both raises *and* becomes tomorrow's
    # baseline, so a data source stuck returning the same bad history is
    # only ever caught once.
    state = {"SPXL": _state_entry(last_row_count=1000)}
    bad_close = _close_series(last_price=100.0, days=400)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: bad_close)

    with pytest.raises(RuntimeError, match="row count dropped"):
        main_module.process_ticker("SPXL", _CFG, state, dry_run=False)
    assert state["SPXL"]["last_row_count"] == 1000  # unchanged -- the bad fetch never overwrote it

    with pytest.raises(RuntimeError, match="row count dropped"):
        main_module.process_ticker("SPXL", _CFG, state, dry_run=False)  # still caught, a second time


def test_main_saves_state_even_when_every_ticker_fails(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "SPXL": {
            "notified_event_keys": [["2026-01-01", "DRAWDOWN_MODE_ENTER", None]],
            "last_updated": "2026-01-01T00:00:00",
        }
    }))

    monkeypatch.setattr(main_module, "load_config", lambda path: {"SPXL": _CFG})
    monkeypatch.setattr(
        main_module, "fetch_history",
        lambda ticker, refresh: (_ for _ in ()).throw(RuntimeError("network down")),
    )
    error_calls = []
    heartbeat_calls = []
    monkeypatch.setattr(main_module, "notify_error", lambda ticker, msg: error_calls.append((ticker, msg)))
    monkeypatch.setattr(main_module, "notify_heartbeat", lambda lines: heartbeat_calls.append(lines))
    # Not under test here -- see test_refuse_if_market_open_* and
    # test_main_* below for the guard itself.
    monkeypatch.setattr(main_module, "_refuse_if_market_open", lambda: None)
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(state_path)])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert error_calls == [("SPXL", "SPXL: network down")]
    # Still sent (not skipped), and the failure shows up here too -- in case
    # the same outage that broke the fetch also breaks the error email above.
    assert heartbeat_calls == [["SPXL: ERROR - network down"]]

    saved = real_load_state(state_path)
    assert saved["SPXL"]["notified_event_keys"] == {("2026-01-01", "DRAWDOWN_MODE_ENTER", None)}


def test_main_notifies_event_after_a_quiet_run_round_trip(tmp_path, monkeypatch):
    # End-to-end regression guard for the exact bug the reviewer reproduced:
    # a quiet run (no events) must not make the ticker "disappear" from the
    # persisted state file, or its next real event gets silently seeded
    # instead of emailed on every subsequent quiet-then-active cycle.
    state_path = tmp_path / "state.json"
    quiet_close = _close_series(last_price=100.0, days=400)  # no episode -- nothing to notify
    monkeypatch.setattr(main_module, "load_config", lambda path: {"SPXL": _CFG})
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: quiet_close)
    monkeypatch.setattr(main_module, "notify_heartbeat", lambda lines: None)
    monkeypatch.setattr(main_module, "notify_error", lambda ticker, msg: None)
    # Not under test here -- see test_refuse_if_market_open_* and
    # test_main_* below for the guard itself.
    monkeypatch.setattr(main_module, "_refuse_if_market_open", lambda: None)
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(state_path)])

    main_module.main()  # a quiet run -- establishes SPXL in state with zero keys

    after_quiet_run = real_load_state(state_path)
    assert "SPXL" in after_quiet_run  # must not vanish just for having nothing to report

    event_close = _close_series(last_price=79.0, days=400)  # now a DRAWDOWN_MODE_ENTER
    notified_calls = []
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: event_close)
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    main_module.main()

    assert [e["event"] for e in notified_calls] == ["DRAWDOWN_MODE_ENTER"]


def test_main_notifies_error_on_startup_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda path: (_ for _ in ()).throw(ValueError("bad yaml")))
    error_calls = []
    monkeypatch.setattr(main_module, "notify_error", lambda ticker, msg: error_calls.append((ticker, msg)))
    # Not under test here -- see test_refuse_if_market_open_* and
    # test_main_* below for the guard itself.
    monkeypatch.setattr(main_module, "_refuse_if_market_open", lambda: None)
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(tmp_path / "state.json")])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert len(error_calls) == 1
    assert error_calls[0][0] is None
    assert "bad yaml" in error_calls[0][1]


def test_refuse_if_market_open_raises_during_regular_hours():
    a_thursday_noon = datetime(2026, 10, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    with pytest.raises(RuntimeError, match="NYSE hours"):
        main_module._refuse_if_market_open(a_thursday_noon)


def test_refuse_if_market_open_raises_shortly_after_the_close():
    # Regression guard: the close itself isn't necessarily final the moment
    # the bell rings, so the cutoff is a couple of hours past 16:00, not
    # 16:00 itself -- see docs/architecture.md "Deployment".
    just_after_close = datetime(2026, 10, 1, 16, 5, tzinfo=ZoneInfo("America/New_York"))
    with pytest.raises(RuntimeError, match="NYSE hours"):
        main_module._refuse_if_market_open(just_after_close)


def test_refuse_if_market_open_allows_evening():
    a_thursday_evening = datetime(2026, 10, 1, 20, 0, tzinfo=ZoneInfo("America/New_York"))
    main_module._refuse_if_market_open(a_thursday_evening)  # does not raise


def test_refuse_if_market_open_allows_weekend_even_at_noon():
    a_saturday_noon = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    main_module._refuse_if_market_open(a_saturday_noon)  # does not raise


def test_refuse_if_market_open_is_exclusive_of_the_safe_time():
    exactly_safe = datetime(2026, 10, 1, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    main_module._refuse_if_market_open(exactly_safe)  # 18:00 itself is already safe


def test_main_refuses_to_run_and_notifies_error_when_market_is_open(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda path: {"SPXL": _CFG})
    monkeypatch.setattr(
        main_module, "_refuse_if_market_open",
        lambda: (_ for _ in ()).throw(RuntimeError("refusing to run during NYSE hours (12:00 EDT)")),
    )
    error_calls = []
    monkeypatch.setattr(main_module, "notify_error", lambda ticker, msg: error_calls.append((ticker, msg)))
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(tmp_path / "state.json")])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert len(error_calls) == 1
    assert error_calls[0][0] is None
    assert "NYSE hours" in error_calls[0][1]


def test_main_dry_run_never_checks_market_hours(monkeypatch, tmp_path):
    # dry-run sends no email and saves no state, so running it during market
    # hours is harmless -- the guard must not even be consulted.
    monkeypatch.setattr(main_module, "load_config", lambda path: {"SPXL": _CFG})
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: _close_series(last_price=100.0, days=400))
    checked = []
    monkeypatch.setattr(main_module, "_refuse_if_market_open", lambda: checked.append(True))
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(tmp_path / "state.json"), "--dry-run"])

    main_module.main()

    assert checked == []
