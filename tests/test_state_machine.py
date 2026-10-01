import pandas as pd
import pytest

from src.drawdown import all_time_high
from src.state_machine import TickerConfig, run


def _series(prices: list[float], start: str = "2020-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=index)


def _ref(close: pd.Series) -> pd.Series:
    # warmup="0D" so these short synthetic series aren't masked by the
    # 52-week warmup period (see test_drawdown.py for that behavior).
    return all_time_high(close, warmup="0D")


def test_level_only_triggers_once_per_episode():
    close = _series([100, 79, 74, 73, 100])
    config = TickerConfig(watch_threshold=-20, levels=[-25])

    events = run(close, _ref(close), config)
    level_triggers = [e for e in events if e["event"] == "LEVEL_TRIGGER"]

    assert len(level_triggers) == 1


def test_no_events_when_drawdown_never_reaches_watch_threshold():
    close = _series([100, 95, 90, 95, 100])
    config = TickerConfig(watch_threshold=-20, levels=[-25])

    events = run(close, _ref(close), config)

    assert events == []


def test_recovery_needs_both_threshold_and_confirm_days():
    # low=76 at index 3. +10.5% is reached at index 4, but confirmation
    # also needs recovery_confirm_days=3 trading days without a new low.
    close = _series([100, 100, 79, 76, 84, 84, 84, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=3
    )

    events = run(close, _ref(close), config)
    confirmed = [e for e in events if e["event"] == "RECOVERY_CONFIRMED"]

    assert len(confirmed) == 1
    assert confirmed[0]["date"] == close.index[6]  # not index 4 -- too soon
    assert confirmed[0]["recovery_pct"] == pytest.approx(10.5263, rel=1e-3)
    assert confirmed[0]["days_since_low"] == 3


def test_new_low_undercuts_confirmed_recovery_and_can_reconfirm():
    close = _series([100, 100, 79, 79, 90, 70, 70, 85, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=2
    )

    events = run(close, _ref(close), config)
    kinds = [(e["date"], e["event"]) for e in events]

    confirmed_dates = [d for d, k in kinds if k == "RECOVERY_CONFIRMED"]
    undercut_dates = [d for d, k in kinds if k == "RECOVERY_UNDERCUT"]

    assert confirmed_dates == [close.index[4], close.index[7]]
    assert undercut_dates == [close.index[5]]
    # the undercut must come after the first confirmation, before the second
    assert confirmed_dates[0] < undercut_dates[0] < confirmed_dates[1]


def test_no_renewed_decline_without_a_prior_confirmed_recovery():
    # Oscillates above and below watch_threshold repeatedly, but recovery
    # never confirms (threshold is unreachable) -- so none of that
    # oscillation should be reported as a "renewed" decline. A plain dip
    # back toward the original reference_high is normal noise, not a new
    # crash, until a recovery has actually been confirmed once.
    close = _series([100, 100, 75, 95, 70, 95, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=1000, recovery_confirm_days=1000
    )

    events = run(close, _ref(close), config)
    kinds = [e["event"] for e in events]

    assert kinds == ["DRAWDOWN_MODE_ENTER", "NORMAL_RESUME"]


def test_renewed_decline_starts_fresh_sub_episode_after_confirmed_recovery():
    # Enters, confirms a recovery off low=79, rallies to a post-recovery
    # high of 99 (short of the original reference_high=100, so no
    # NORMAL_RESUME yet), then drops -20%+ from *that* high without going
    # below the old confirmed low (79) -- a fresh crash, not an undercut.
    # Reconfirms off the new low (79.1), rallies back to 99 again (still
    # short of the original 100 -- no resume yet either), then finally
    # reaches the original 100.
    close = _series([100, 100, 79, 79, 95, 99, 79.1, 92, 92, 99, 100])
    config = TickerConfig(
        watch_threshold=-20, levels=[], recovery_threshold=10, recovery_confirm_days=2
    )

    events = run(close, _ref(close), config)
    kinds = [(e["date"], e["event"]) for e in events]

    assert kinds == [
        (close.index[2], "DRAWDOWN_MODE_ENTER"),
        (close.index[4], "RECOVERY_CONFIRMED"),
        (close.index[6], "RENEWED_DECLINE"),
        (close.index[8], "RECOVERY_CONFIRMED"),
        (close.index[10], "NORMAL_RESUME"),
    ]

    renewed = events[2]
    assert renewed["reference_high"] == pytest.approx(99)
    assert renewed["drawdown_pct"] == pytest.approx(-20.1, abs=0.1)

    # the fresh sub-episode's own recovery is tracked from its own low (79.1),
    # not the original episode's low (79)
    second_confirm = events[3]
    assert second_confirm["lowest_close"] == pytest.approx(79.1)

    # resume only once the *original* reference high (100) is regained --
    # reaching the relocked, lower one (99) at index 9 must NOT resume,
    # since the real 52-week high a production caller would see is still
    # the original 100, not far out of reach -- resuming there would
    # immediately re-trigger a spurious DRAWDOWN_MODE_ENTER the next day
    # even while price is still in the middle of genuinely recovering.
    resume = events[4]
    assert resume["reference_high"] == pytest.approx(100)


def test_normal_resume_on_reference_high_regained():
    close = _series([100, 100, 79, 76, 74, 60, 66, 100])
    config = TickerConfig(watch_threshold=-20, levels=[-25, -40], recovery_confirm_days=0)

    events = run(close, _ref(close), config)

    resume = events[-1]
    assert resume["event"] == "NORMAL_RESUME"
    assert resume["close"] == 100
    assert resume["lowest_close"] == 60
