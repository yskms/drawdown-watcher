import json

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


def test_process_ticker_notifies_new_events_when_not_first_run(monkeypatch):
    close = _close_series(last_price=79.0)  # dd=-21% -- a DRAWDOWN_MODE_ENTER today
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    monkeypatch.setattr(main_module, "_cached_row_count", lambda ticker: None)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {"SPXL": {"notified_event_keys": set(), "last_updated": None}}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]
    assert seeded == []
    assert len(notified_calls) == 1
    assert today == close.index[-1]
    assert len(state["SPXL"]["notified_event_keys"]) == 1


def test_process_ticker_seeds_silently_on_first_run(monkeypatch):
    close = _close_series(last_price=79.0)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    monkeypatch.setattr(main_module, "_cached_row_count", lambda ticker: None)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {}  # SPXL has never been seen before
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=False)

    assert notified == []
    assert [e["event"] for e in seeded] == ["DRAWDOWN_MODE_ENTER"]
    assert notified_calls == []  # seeded, not emailed
    assert len(state["SPXL"]["notified_event_keys"]) == 1  # but still recorded, so it won't resurface


def test_process_ticker_dry_run_does_not_call_notify_event(monkeypatch):
    close = _close_series(last_price=79.0)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    monkeypatch.setattr(main_module, "_cached_row_count", lambda ticker: None)
    notified_calls = []
    monkeypatch.setattr(main_module, "notify_event", lambda ticker, event: notified_calls.append(event))

    state = {"SPXL": {"notified_event_keys": set(), "last_updated": None}}
    status_line, today, notified, seeded = main_module.process_ticker("SPXL", _CFG, state, dry_run=True)

    assert [e["event"] for e in notified] == ["DRAWDOWN_MODE_ENTER"]  # still reported, for dry-run printing
    assert notified_calls == []  # but never actually emailed


def test_process_ticker_raises_on_stale_data(monkeypatch):
    stale_close = _close_series(last_price=100.0, end=pd.Timestamp.now().normalize() - pd.Timedelta(days=30))
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: stale_close)
    monkeypatch.setattr(main_module, "_cached_row_count", lambda ticker: None)

    with pytest.raises(RuntimeError, match="data may be stuck"):
        main_module.process_ticker("SPXL", _CFG, {}, dry_run=False)


def test_process_ticker_raises_on_row_count_drop(monkeypatch):
    close = _close_series(last_price=100.0, days=400)
    monkeypatch.setattr(main_module, "fetch_history", lambda ticker, refresh: close)
    monkeypatch.setattr(main_module, "_cached_row_count", lambda ticker: 1000)  # was 1000, now 400

    with pytest.raises(RuntimeError, match="row count dropped"):
        main_module.process_ticker("SPXL", _CFG, {}, dry_run=False)


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
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(state_path)])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert error_calls == [("SPXL", "SPXL: network down")]
    assert heartbeat_calls == [[]]  # still sent, proving the run completed rather than hanging/crashing silently

    saved = real_load_state(state_path)
    assert saved["SPXL"]["notified_event_keys"] == {("2026-01-01", "DRAWDOWN_MODE_ENTER", None)}


def test_main_notifies_error_on_startup_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda path: (_ for _ in ()).throw(ValueError("bad yaml")))
    error_calls = []
    monkeypatch.setattr(main_module, "notify_error", lambda ticker, msg: error_calls.append((ticker, msg)))
    monkeypatch.setattr("sys.argv", ["main.py", "--state", str(tmp_path / "state.json")])

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert len(error_calls) == 1
    assert error_calls[0][0] is None
    assert "bad yaml" in error_calls[0][1]
