"""Derives a "where things stand today" summary per ticker (Japanese, for the
heartbeat email -- see docs/architecture.md "Notifications").

Deliberately a post-hoc read of the events `state_machine.run` already
produced, rather than new engine state: state_machine.py's internal loop
variables (mode, reference_high, ...) are intentionally not exposed (see
CLAUDE.md on episode_high/reference_high), so this re-derives only what it
needs -- current mode, drawdown%, next level, whether the bottom is
currently confirmed, uptrend peak/sell line -- from the event list plus the
price series. The uptrend peak is recomputed
as `close.loc[base_date:].max()`, which is exactly what track_uptrend's own
peak tracking amounts to (same definition, same tie-break), so this stays
consistent with the engine without duplicating its loop.
"""

from __future__ import annotations

import pandas as pd

from src.state_machine import TickerConfig


def current_status(close: pd.Series, events: list[dict], config: TickerConfig) -> str:
    """The first line says which stage the ticker is in, in one breath
    ("底打ち確認済み。上昇を追跡中..."); indented lines below it carry the
    numbers. The two halves -- drawdown episode and uptrend tracking -- are
    independent in the engine, so the headline names both rather than
    picking one: e.g. an episode is still open (the old high isn't regained)
    while the bottom is already confirmed and the rebound is being followed."""
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
    #
    # `bottom_confirmed` mirrors state_machine.py's recovery_confirmed: set by
    # RECOVERY_CONFIRMED, cleared by RECOVERY_UNDERCUT and by anything that
    # starts a fresh (sub-)episode or ends this one.
    entry = None
    triggered: set[float] = set()
    bottom_confirmed = False
    for e in events:
        if e["event"] in ("DRAWDOWN_MODE_ENTER", "RENEWED_DECLINE"):
            entry = e
            triggered = set()
            bottom_confirmed = False
        elif e["event"] == "NORMAL_RESUME":
            entry = None
            bottom_confirmed = False
        elif e["event"] == "LEVEL_TRIGGER":
            triggered.add(e["level"])
        elif e["event"] == "RECOVERY_CONFIRMED":
            bottom_confirmed = True
        elif e["event"] == "RECOVERY_UNDERCUT":
            bottom_confirmed = False

    uptrend = _uptrend_state(close, events, config)
    hold = f"{config.hold_until_multiple:.1f}倍"

    if entry is None:
        headline = "平常（下落局面ではありません）"
    elif bottom_confirmed:
        headline = "底打ち確認済み"
    else:
        headline = "下落局面の途中（底打ちは未確認）"
    if uptrend is not None:
        if uptrend["armed"]:
            headline += "。上昇を追跡中（売りルール有効中）"
        else:
            headline += f"。上昇を追跡中（{hold}になるまで保有）"

    lines = [f"現在: {headline}"]

    if entry is not None:
        reference_high = entry["reference_high"]
        drawdown_pct = (price / reference_high - 1) * 100
        remaining = [lv for lv in config.levels if lv not in triggered]
        if remaining:
            level_price = reference_high * (1 + remaining[0] / 100)
            next_level = f"次の警戒ライン: {remaining[0]:.0f}%（{level_price:.2f}）"
        elif config.levels:
            next_level = "警戒ラインはすべて到達済み"
        else:
            next_level = ""
        lines.append(
            f"下落局面: {entry['date'].date()}に突入。高値 {reference_high:.2f} から"
            f"現在 {drawdown_pct:.1f}%。高値を回復するまで続きます。{next_level}"
        )

    if uptrend is not None:
        if uptrend["armed"]:
            peak, trail = uptrend["peak"], config.trail_from_peak
            distance_pct = (price / peak - 1) * 100
            sell_line = peak * (1 + trail / 100)
            lines.append(
                f"上昇の追跡: 高値 {peak:.2f}（{uptrend['peak_date'].date()}）から"
                f"現在 {distance_pct:.1f}%。売りライン {sell_line:.2f}（高値から{trail:.0f}%）を"
                "割ると、上昇が一巡したとみなします。"
            )
        else:
            base_close = uptrend["base_close"]
            target = base_close * config.hold_until_multiple
            lines.append(
                f"上昇の追跡: 底打ち確認日（{uptrend['base_date'].date()}）の終値 {base_close:.2f} から"
                f" ×{price / base_close:.2f}。{hold}（{target:.2f}）に達するまでは、"
                "価格による売りルールは動きません。"
            )

    return "\n".join([lines[0], *(f"  {line}" for line in lines[1:])])


def _uptrend_state(close: pd.Series, events: list[dict], config: TickerConfig) -> dict | None:
    """The uptrend being tracked right now, or None if there isn't one (or
    tracking is disabled for this ticker)."""
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
        return None

    return {
        "armed": armed,
        "base_date": base_date,
        "base_close": base_close,
        "peak": close.loc[base_date:].max(),
        "peak_date": close.loc[base_date:].idxmax(),
    }
