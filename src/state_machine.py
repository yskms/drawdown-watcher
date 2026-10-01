"""NORMAL -> DRAWDOWN MODE state transitions, driven by drawdown.py.

Reference high tracking (52-week vs. all-time-high) is injected as a
series, so the same state machine can be backtested against either
method (see docs/strategy.md: comparing the two is how the 52-week
method's blind spots get found).

Recovery design (see docs/strategy.md "Recovery" for the full rationale):
a single rebound off the lowest close is not trustworthy on its own — on a
3x leveraged ETF, a dead-cat bounce can clear +15% in a day or two in the
middle of an ongoing crash. So a recovery only *confirms* once at least
recovery_confirm_days trading days have passed since the running low
without a new low, and the close that day is recovery_threshold% above
that low. If a new low later undercuts an already confirmed bottom, that
confirmation is revoked (RECOVERY_UNDERCUT) and has to re-earn
confirmation from the new low. Being late is fine; a false "it bottomed"
is the failure mode this guards against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

NORMAL = "NORMAL"
DRAWDOWN = "DRAWDOWN"


@dataclass
class TickerConfig:
    watch_threshold: float  # e.g. -20 (percent)
    levels: list[float] = field(default_factory=list)  # e.g. [-25, -40, -50]
    recovery_threshold: float = 15.0  # % rebound off the running low
    recovery_confirm_days: int = 10  # trading days without a new low, before confirming


def _streak_length(close: pd.Series, start_date, threshold_price: float) -> int:
    """Consecutive trading days from start_date (inclusive) with close <= threshold_price."""
    count = 0
    for price in close.loc[start_date:]:
        if price > threshold_price:
            break
        count += 1
    return count


def run(
    close: pd.Series, reference_high_series: pd.Series, config: TickerConfig
) -> list[dict]:
    """Day-by-day simulation. Returns a list of event dicts, in date order.

    Event types:
      DRAWDOWN_MODE_ENTER  -- watch_threshold reached, reference high locked.
      LEVEL_TRIGGER         -- a deeper configured level reached (informational).
      RECOVERY_CONFIRMED    -- the actionable "it bottomed" signal.
      RECOVERY_UNDERCUT     -- a later close broke back below a confirmed bottom.
      RENEWED_DECLINE       -- only possible after a RECOVERY_CONFIRMED: price
                               went on to make new highs, then fell
                               watch_threshold% from *that* high. Treated as
                               a fresh sub-episode -- reference_high relocks
                               to that post-recovery high and level/recovery
                               tracking resets, so the usual three-tier flow
                               (pay attention -> levels -> confirmed bottom)
                               replays for it, without waiting for the
                               original, much older reference_high to be
                               fully regained (see docs/strategy.md "Staying
                               alert during a long episode"). Same "pay
                               attention" meaning as DRAWDOWN_MODE_ENTER.
      NORMAL_RESUME         -- close back at/above the *episode's original*
                               reference high -- not a relocked one from a
                               RENEWED_DECLINE. Otherwise, a relock to a
                               lower post-recovery high could itself be
                               within reach of the 52-week high still
                               sitting in the window from before the
                               episode started, resuming NORMAL mode and
                               immediately re-triggering DRAWDOWN_MODE_ENTER
                               the next day off that stale, much higher
                               value -- a false "pay attention" while the
                               price is actually still recovering.
    """
    events: list[dict] = []

    mode = NORMAL
    episode_high = None  # fixed for the whole episode; gates NORMAL_RESUME
    reference_high = None  # current working reference; relocks on RENEWED_DECLINE
    triggered_levels: set[float] = set()
    lowest_close = None
    lowest_close_date = None
    lowest_close_index = None
    recovery_confirmed = False
    confirmed_low = None
    post_recovery_peak = None

    for i, (date, price) in enumerate(close.items()):
        if mode == NORMAL:
            reference_high = reference_high_series.loc[date]
            if pd.isna(reference_high):
                continue  # not enough history yet for a real reference high
            dd_pct = (price / reference_high - 1) * 100

            if dd_pct <= config.watch_threshold:
                mode = DRAWDOWN
                episode_high = reference_high
                triggered_levels = set()
                lowest_close = price
                lowest_close_date = date
                lowest_close_index = i
                recovery_confirmed = False
                confirmed_low = None
                post_recovery_peak = None
                threshold_price = reference_high * (1 + config.watch_threshold / 100)
                events.append(
                    {
                        "date": date,
                        "event": "DRAWDOWN_MODE_ENTER",
                        "close": price,
                        "reference_high": reference_high,
                        "drawdown_pct": dd_pct,
                        "streak_trading_days": _streak_length(
                            close, date, threshold_price
                        ),
                    }
                )
            continue

        # mode == DRAWDOWN: reference_high stays locked until NORMAL_RESUME
        # or a renewed decline relocks it (see RENEWED_DECLINE, below).
        dd_pct = (price / reference_high - 1) * 100

        if price < lowest_close:
            lowest_close = price
            lowest_close_date = date
            lowest_close_index = i
            if recovery_confirmed and lowest_close < confirmed_low:
                recovery_confirmed = False
                post_recovery_peak = None
                events.append(
                    {
                        "date": date,
                        "event": "RECOVERY_UNDERCUT",
                        "close": price,
                        "confirmed_low": confirmed_low,
                    }
                )
                confirmed_low = None

        for level_index, level in enumerate(config.levels, start=1):
            if level not in triggered_levels and dd_pct <= level:
                triggered_levels.add(level)
                threshold_price = reference_high * (1 + level / 100)
                events.append(
                    {
                        "date": date,
                        "event": "LEVEL_TRIGGER",
                        "level": level,
                        "level_index": level_index,
                        "close": price,
                        "reference_high": reference_high,
                        "drawdown_pct": dd_pct,
                        "streak_trading_days": _streak_length(
                            close, date, threshold_price
                        ),
                    }
                )

        if not recovery_confirmed:
            days_since_low = i - lowest_close_index
            recovery_pct = (price / lowest_close - 1) * 100
            if (
                days_since_low >= config.recovery_confirm_days
                and recovery_pct >= config.recovery_threshold
            ):
                recovery_confirmed = True
                confirmed_low = lowest_close
                post_recovery_peak = price
                events.append(
                    {
                        "date": date,
                        "event": "RECOVERY_CONFIRMED",
                        "close": price,
                        "lowest_close": lowest_close,
                        "lowest_close_date": lowest_close_date,
                        "recovery_pct": recovery_pct,
                        "days_since_low": days_since_low,
                    }
                )
        else:
            # Only once a recovery is confirmed do we watch for a fresh
            # leg down from whatever high has been made since -- a dip
            # back toward the old, still-locked reference_high is normal
            # noise, not a new crash (see docs/strategy.md).
            if price > post_recovery_peak:
                post_recovery_peak = price
            renewed_dd = (price / post_recovery_peak - 1) * 100
            if renewed_dd <= config.watch_threshold:
                # Treat this like a fresh DRAWDOWN_MODE_ENTER: relock to the
                # post-recovery high and reset level/recovery tracking.
                reference_high = post_recovery_peak
                triggered_levels = set()
                lowest_close = price
                lowest_close_date = date
                lowest_close_index = i
                recovery_confirmed = False
                confirmed_low = None
                post_recovery_peak = None
                threshold_price = reference_high * (1 + config.watch_threshold / 100)
                events.append(
                    {
                        "date": date,
                        "event": "RENEWED_DECLINE",
                        "close": price,
                        "reference_high": reference_high,
                        "drawdown_pct": renewed_dd,
                        "streak_trading_days": _streak_length(
                            close, date, threshold_price
                        ),
                    }
                )
                continue  # this day already re-seeded a fresh (sub-)episode

        if price >= episode_high:
            events.append(
                {
                    "date": date,
                    "event": "NORMAL_RESUME",
                    "close": price,
                    "reference_high": episode_high,
                    "lowest_close": lowest_close,
                    "lowest_close_date": lowest_close_date,
                }
            )
            mode = NORMAL
            episode_high = None
            reference_high = None
            triggered_levels = set()
            lowest_close = None
            lowest_close_date = None
            lowest_close_index = None
            recovery_confirmed = False
            confirmed_low = None
            post_recovery_peak = None

    return events
