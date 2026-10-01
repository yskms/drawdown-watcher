"""Human-readable formatting of state_machine events, shared by backtest.py
(printed) and notifier.py (emailed)."""

from __future__ import annotations


def format_event(e: dict, *, show_streak: bool = True) -> str:
    """`show_streak` defaults on for backtest.py, where `streak_trading_days`
    (how many days the price stayed past the threshold) is meaningful because
    the full future is already known. In production, the event being emailed
    is always today's -- there is no future yet -- so it would always read
    "streak=1d", a meaningless number dressed up as data; `notifier.py` turns
    this off.
    """
    date = e["date"].date()
    if e["event"] == "DRAWDOWN_MODE_ENTER":
        streak = f"  streak={e['streak_trading_days']}d" if show_streak else ""
        return (
            f"{date}  DRAWDOWN MODE ENTER   close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  drawdown={e['drawdown_pct']:.1f}%{streak}"
        )
    if e["event"] == "LEVEL_TRIGGER":
        streak = f"  streak={e['streak_trading_days']}d" if show_streak else ""
        return (
            f"{date}  LEVEL {e['level_index']} ({e['level']:.0f}%)     "
            f"close={e['close']:.2f}  ref_high={e['reference_high']:.2f}  "
            f"drawdown={e['drawdown_pct']:.1f}%{streak}"
        )
    if e["event"] == "RECOVERY_CONFIRMED":
        return (
            f"{date}  RECOVERY CONFIRMED    close={e['close']:.2f}  "
            f"from low={e['lowest_close']:.2f} on {e['lowest_close_date'].date()}  "
            f"(+{e['recovery_pct']:.1f}%, {e['days_since_low']}d held)"
        )
    if e["event"] == "RECOVERY_UNDERCUT":
        return (
            f"{date}  RECOVERY UNDERCUT     close={e['close']:.2f}  "
            f"broke back below confirmed low {e['confirmed_low']:.2f}"
        )
    if e["event"] == "RENEWED_DECLINE":
        streak = f"  streak={e['streak_trading_days']}d" if show_streak else ""
        return (
            f"{date}  RENEWED DECLINE       close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  drawdown={e['drawdown_pct']:.1f}%{streak}"
        )
    if e["event"] == "UPTREND_ARMED":
        return (
            f"{date}  UPTREND ARMED         close={e['close']:.2f}  "
            f"x{e['multiple']:.1f} from bottom call {e['base_close']:.2f} "
            f"on {e['base_date'].date()}  sell_line={e['sell_line']:.2f}"
        )
    if e["event"] == "UPTREND_EXIT":
        return (
            f"{date}  UPTREND EXIT ({e['reason']:<8}) close={e['close']:.2f}  "
            f"x{e['multiple']:.1f} from bottom call {e['base_close']:.2f}  "
            f"peak={e['peak']:.2f} on {e['peak_date'].date()}"
        )
    if e["event"] == "NORMAL_RESUME":
        return (
            f"{date}  NORMAL RESUME         close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  "
            f"low={e['lowest_close']:.2f} on {e['lowest_close_date'].date()}"
        )
    return str(e)
