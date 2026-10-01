"""52-week high tracking and drawdown calculation. Pure functions, no I/O."""

from __future__ import annotations

import pandas as pd

ROLLING_WINDOW = "364D"


def rolling_high(close: pd.Series, window: str = ROLLING_WINDOW, warmup: str = ROLLING_WINDOW) -> pd.Series:
    """Trailing high close over the given calendar window, inclusive of today.

    `close` must be indexed by (sorted, tz-naive) date. Returns NaN for the
    first `warmup` of the series (default: same as `window`) — otherwise a
    ticker's listing price stands in as a fake "52-week high" from day one,
    which is not a real reference high (this is what produced SPXL's
    spurious 2008-11-20 entry, 11 trading days after inception).
    """
    high = close.rolling(window, min_periods=1).max()
    has_full_history = close.index >= close.index[0] + pd.Timedelta(warmup)
    return high.where(has_full_history)


def all_time_high(close: pd.Series, warmup: str = ROLLING_WINDOW) -> pd.Series:
    """Trailing all-time high close, inclusive of today.

    Same `warmup` masking as rolling_high, so comparisons between the two
    methods aren't skewed by one
    treating the listing price as a reference high and the other not.
    """
    high = close.cummax()
    has_full_history = close.index >= close.index[0] + pd.Timedelta(warmup)
    return high.where(has_full_history)


def drawdown_pct(close: pd.Series, reference_high: pd.Series) -> pd.Series:
    """Drawdown of `close` from `reference_high`, as a percentage (e.g. -20.0)."""
    return (close / reference_high - 1) * 100
