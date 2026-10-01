"""Derives a one-line "where things stand today" summary per ticker, for the
heartbeat notification (see docs/architecture.md "Notifications").

Deliberately a post-hoc read of the events `state_machine.run` already
produced, rather than new engine state: state_machine.py's internal loop
variables (mode, reference_high, ...) are intentionally not exposed (see
CLAUDE.md on episode_high/reference_high), so this re-derives only what it
needs -- current mode, drawdown%, next level, uptrend peak/sell line --
from the event list plus the price series. The uptrend peak is recomputed
as `close.loc[base_date:].max()`, which is exactly what track_uptrend's own
peak tracking amounts to (same definition, same tie-break), so this stays
consistent with the engine without duplicating its loop.
"""

from __future__ import annotations

import pandas as pd

from src.state_machine import TickerConfig


def current_status(close: pd.Series, events: list[dict], config: TickerConfig) -> str:
    price = close.iloc[-1]

    # Single forward pass, resetting `triggered` exactly when `entry` does,
    # rather than filtering LEVEL_TRIGGER events by `date >= entry["date"]`.
    # state_machine.py checks levels against the *old* reference_high before
    # a same-day RENEWED_DECLINE relocks it, so a LEVEL_TRIGGER can in
    # principle share its date with the RENEWED_DECLINE that follows it in
    # the event list -- a date comparison can't tell the two apart, but
    # position can. (In practice state_machine.py's invariants mean that
    # exact collision can't carry an untriggered level -- RECOVERY_UNDERCUT
    # would fire first whenever one could -- but resetting by position is no
    # more complex than by date, and doesn't depend on that invariant holding.)
    entry = None
    triggered: set[float] = set()
    for e in events:
        if e["event"] in ("DRAWDOWN_MODE_ENTER", "RENEWED_DECLINE"):
            entry = e
            triggered = set()
        elif e["event"] == "NORMAL_RESUME":
            entry = None
        elif e["event"] == "LEVEL_TRIGGER":
            triggered.add(e["level"])

    if entry is None:
        line = "NORMAL (no active drawdown episode)"
    else:
        reference_high = entry["reference_high"]
        drawdown_pct = (price / reference_high - 1) * 100
        remaining = [lv for lv in config.levels if lv not in triggered]
        next_level = f"{remaining[0]:.0f}%" if remaining else "none left"
        line = (
            f"DRAWDOWN MODE since {entry['date'].date()}: "
            f"{drawdown_pct:.1f}% off {reference_high:.2f}, next level {next_level}"
        )

    uptrend_line = _uptrend_status(close, events, config)
    if uptrend_line:
        line = f"{line} | {uptrend_line}"
    return f"{line} (as of {close.index[-1].date()})"


def _uptrend_status(close: pd.Series, events: list[dict], config: TickerConfig) -> str | None:
    if config.trail_from_peak is None:
        return None

    tracking = False
    armed = False
    base_date = None
    base_close = None

    for e in events:
        if e["event"] == "RECOVERY_CONFIRMED" and e.get("starts_uptrend"):
            tracking, armed = True, False
            base_date, base_close = e["date"], e["close"]
        elif e["event"] == "UPTREND_ARMED":
            armed = True
        elif e["event"] == "UPTREND_EXIT":
            tracking = False

    if not tracking:
        return "not tracking an uptrend"

    price = close.iloc[-1]
    peak = close.loc[base_date:].max()
    peak_date = close.loc[base_date:].idxmax()

    if not armed:
        multiple = price / base_close
        return (
            f"UPTREND (holding to {config.hold_until_multiple:.1f}x): "
            f"x{multiple:.2f} from bottom call {base_close:.2f} on {base_date.date()}"
        )

    distance_pct = (price / peak - 1) * 100
    sell_line = peak * (1 + config.trail_from_peak / 100)
    return (
        f"UPTREND ARMED: peak {peak:.2f} on {peak_date.date()}, "
        f"now {distance_pct:.1f}% off peak, sell line {sell_line:.2f}"
    )
