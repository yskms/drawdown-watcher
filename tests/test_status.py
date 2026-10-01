import pandas as pd

from src.drawdown import all_time_high
from src.state_machine import TickerConfig, run
from src.status import current_status


def _series(prices: list[float], start: str = "2020-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=index)


def _ref(close: pd.Series) -> pd.Series:
    return all_time_high(close, warmup="0D")


def test_normal_with_no_uptrend_tracking_configured():
    close = _series([100, 95, 90, 95, 100])
    config = TickerConfig(watch_threshold=-20, levels=[])

    events = run(close, _ref(close), config)

    assert current_status(close, events, config) == (
        f"NORMAL (no active drawdown episode) (as of {close.index[-1].date()})"
    )


def test_normal_but_not_tracking_an_uptrend_when_never_confirmed():
    close = _series([100, 95, 90, 95, 100])
    config = TickerConfig(watch_threshold=-20, levels=[], trail_from_peak=-15)

    events = run(close, _ref(close), config)

    assert current_status(close, events, config) == (
        f"NORMAL (no active drawdown episode) | not tracking an uptrend "
        f"(as of {close.index[-1].date()})"
    )


def test_drawdown_mode_reports_drawdown_pct_and_next_level():
    close = _series([100, 79, 74, 73])
    config = TickerConfig(watch_threshold=-20, levels=[-25, -30])

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert status.startswith(f"DRAWDOWN MODE since {close.index[1].date()}:")
    assert "-27.0% off 100.00" in status
    assert "next level -30%" in status


def test_uptrend_not_armed_shows_multiple_from_base():
    close = _series([100, 100, 79, 76, 84, 84, 84, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert "UPTREND (holding to 2.0x)" in status
    assert f"bottom call 84.00 on {close.index[6].date()}" in status


def test_triggered_levels_reset_when_a_renewed_decline_relocks():
    # A RENEWED_DECLINE should start its (sub-)episode with no levels
    # considered triggered, even though the prior episode already triggered
    # one of them -- state_machine.py resets triggered_levels on relock.
    close = _series([100, 100, 79, 65, 90, 90, 95, 74])
    config = TickerConfig(
        watch_threshold=-20, levels=[-30, -80], recovery_threshold=10, recovery_confirm_days=2,
    )

    events = run(close, _ref(close), config)
    assert [e["event"] for e in events] == [
        "DRAWDOWN_MODE_ENTER", "LEVEL_TRIGGER", "RECOVERY_CONFIRMED", "RENEWED_DECLINE",
    ]  # sanity check on the setup: -30 triggers before the relock, not after

    status = current_status(close, events, config)

    assert status.startswith(f"DRAWDOWN MODE since {close.index[7].date()}:")
    assert "next level -30%" in status  # not "-80%": -30 resets as untriggered after the relock


def test_uptrend_armed_shows_peak_and_sell_line():
    close = _series([100, 100, 79, 76, 84, 84, 84, 100, 200, 190])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert f"UPTREND ARMED: peak 200.00 on {close.index[8].date()}" in status
    assert "now -5.0% off peak" in status
    assert "sell line 170.00" in status
