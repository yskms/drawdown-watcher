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

    assert current_status(close, events, config) == "現在: 平常（下落局面ではありません）"


def test_normal_but_not_tracking_an_uptrend_when_never_confirmed():
    close = _series([100, 95, 90, 95, 100])
    config = TickerConfig(watch_threshold=-20, levels=[], trail_from_peak=-15)

    events = run(close, _ref(close), config)

    # Uptrend tracking is configured but nothing has started one: no
    # "上昇の追跡" line, and the headline doesn't claim one.
    assert current_status(close, events, config) == "現在: 平常（下落局面ではありません）"


def test_drawdown_mode_reports_drawdown_pct_and_next_level():
    close = _series([100, 79, 74, 73])
    config = TickerConfig(watch_threshold=-20, levels=[-25, -30])

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert status.startswith("現在: 下落局面の途中（底打ちは未確認）\n")
    assert f"下落局面: {close.index[1].date()}に突入" in status
    assert "高値 100.00 から現在 -27.0%" in status
    assert "次の警戒ライン: -30%（70.00）" in status


def test_drawdown_mode_with_all_levels_reached():
    close = _series([100, 79, 74, 69])
    config = TickerConfig(watch_threshold=-20, levels=[-25, -30])

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert "警戒ラインはすべて到達済み" in status
    assert "次の警戒ライン" not in status


def test_drawdown_mode_without_configured_levels_mentions_no_level():
    close = _series([100, 79, 74, 73])
    config = TickerConfig(watch_threshold=-20, levels=[])

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert "警戒ライン" not in status


def test_bottom_confirmed_and_holding_while_the_episode_is_still_open():
    # The case that prompted the Japanese rewrite: Drawdown Mode is still
    # open (old high not regained), yet the bottom is confirmed and the
    # rebound is being followed. The headline has to say both.
    close = _series([100, 100, 79, 76, 84, 84, 84, 88])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert status.splitlines()[0] == "現在: 底打ち確認済み。上昇を追跡中（2.0倍になるまで保有）"
    assert "高値を回復するまで続きます" in status
    assert f"底打ち確認日（{close.index[6].date()}）の終値 84.00 から ×1.05" in status
    assert "2.0倍（168.00）に達するまで" in status


def test_uptrend_not_armed_shows_multiple_from_base():
    close = _series([100, 100, 79, 76, 84, 84, 84, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    # price regained the episode's high on the last day: back to NORMAL, but
    # the uptrend it started is still being followed
    assert status.splitlines()[0] == "現在: 平常（下落局面ではありません）。上昇を追跡中（2.0倍になるまで保有）"
    assert f"底打ち確認日（{close.index[6].date()}）の終値 84.00" in status


def test_bottom_unconfirmed_again_after_an_undercut():
    close = _series([100, 100, 79, 76, 84, 84, 84, 70])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    assert [e["event"] for e in events] == [
        "DRAWDOWN_MODE_ENTER", "RECOVERY_CONFIRMED", "RECOVERY_UNDERCUT", "UPTREND_EXIT",
    ]  # sanity check on the setup

    status = current_status(close, events, config)

    assert status.splitlines()[0] == "現在: 下落局面の途中（底打ちは未確認）"
    assert "上昇の追跡" not in status


def test_bottom_confirmed_without_uptrend_tracking_configured():
    close = _series([100, 100, 79, 76, 84, 84, 84, 88])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert status.splitlines()[0] == "現在: 底打ち確認済み"


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

    # a renewed decline un-confirms the bottom too: it's a fresh sub-episode
    assert status.splitlines()[0] == "現在: 下落局面の途中（底打ちは未確認）"
    assert f"下落局面: {close.index[7].date()}に突入" in status
    assert "次の警戒ライン: -30%" in status  # not "-80%": -30 resets as untriggered after the relock


def test_uptrend_armed_shows_peak_and_sell_line():
    close = _series([100, 100, 79, 76, 84, 84, 84, 100, 200, 190])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3,
        trail_from_peak=-15, hold_until_multiple=2.0,
    )

    events = run(close, _ref(close), config)
    status = current_status(close, events, config)

    assert status.splitlines()[0] == "現在: 平常（下落局面ではありません）。上昇を追跡中（売りルール有効中）"
    assert f"高値 200.00（{close.index[8].date()}）から現在 -5.0%" in status
    assert "売りライン 170.00（高値から-15%）" in status
