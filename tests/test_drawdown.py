import pandas as pd
import pytest

from src.drawdown import all_time_high, drawdown_pct, rolling_high


def _series(prices: list[float], start: str = "2020-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=index)


def test_rolling_high_rolls_off_after_window():
    # Peak of 100 at day 0, then flat at 50. Once the peak is more than
    # 364 days old, the rolling high should drop to 50.
    prices = [100.0] + [50.0] * 400
    close = _series(prices)

    high = rolling_high(close, warmup="0D")

    assert high.iloc[0] == 100.0
    assert high.iloc[363] == 100.0  # still within the 364-day window
    assert high.iloc[364] == 50.0  # peak has rolled off


def test_rolling_high_masks_warmup_period():
    # A ticker's listing price isn't a real 52-week high -- the first
    # `warmup` (default: same as the window) should read as unknown.
    close = _series([100.0] * 400)

    high = rolling_high(close)

    assert high.iloc[:364].isna().all()
    assert high.iloc[364] == 100.0


def test_all_time_high_never_rolls_off():
    prices = [100.0] + [50.0] * 400
    close = _series(prices)

    high = all_time_high(close, warmup="0D")

    assert (high == 100.0).all()


def test_drawdown_pct():
    close = _series([80.0])
    reference = _series([100.0])

    result = drawdown_pct(close, reference)

    assert result.iloc[0] == pytest.approx(-20.0)
