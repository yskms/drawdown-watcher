"""Human-readable formatting of state_machine events.

Two formatters on purpose, not one: `format_event` (English, fixed-width,
for backtest.py and dry-run output, where events are scanned as a column) and
`event_title_ja`/`format_event_ja` (Japanese prose, for the emails notifier.py
sends to the one person who reads them). Merging them would either make the
backtest output prose or put "RECOVERY CONFIRMED close=..." in the inbox.
"""

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


def event_title_ja(e: dict) -> str:
    """One-line headline for an emailed event (the subject line)."""
    kind = e["event"]
    if kind == "DRAWDOWN_MODE_ENTER":
        return "下落局面に入りました"
    if kind == "LEVEL_TRIGGER":
        return f"警戒ライン{e['level_index']}（{e['level']:.0f}%）に到達しました"
    if kind == "RECOVERY_CONFIRMED":
        return "底打ちを確認しました"
    if kind == "RECOVERY_UNDERCUT":
        return "底打ちの確認が取り消されました"
    if kind == "RENEWED_DECLINE":
        return "再び大きく下落しました（新たな下落局面）"
    if kind == "UPTREND_ARMED":
        return f"底打ち確認時の{e['multiple']:.1f}倍に到達しました（売りルール有効）"
    if kind == "UPTREND_EXIT":
        if e["reason"] == "undercut":
            return "底打ちの確認が取り消されたため、上昇の追跡を終了します"
        return "上昇が一巡した可能性があります（売りラインを割り込み）"
    if kind == "NORMAL_RESUME":
        return "高値を回復し、平常に戻りました"
    return kind


def format_event_ja(e: dict) -> str:
    """Body text for an emailed event: what happened, in concrete numbers.

    Never shows `streak_trading_days`, for the same reason `format_event`'s
    `show_streak` is off in production: an emailed event is always today's,
    so it would always read 1.
    """
    kind = e["event"]
    date = e["date"].date()
    if kind == "DRAWDOWN_MODE_ENTER":
        return (
            f"{date}の終値 {e['close']:.2f} が、高値 {e['reference_high']:.2f} から "
            f"{e['drawdown_pct']:.1f}% まで下落しました。\n"
            "高値を回復するまで、下落局面として追跡します。"
        )
    if kind == "LEVEL_TRIGGER":
        return (
            f"{date}の終値 {e['close']:.2f} が、高値 {e['reference_high']:.2f} から "
            f"{e['drawdown_pct']:.1f}% まで下落しました。"
        )
    if kind == "RECOVERY_CONFIRMED":
        return (
            f"{date}の終値 {e['close']:.2f}。最安値 {e['lowest_close']:.2f}"
            f"（{e['lowest_close_date'].date()}）から +{e['recovery_pct']:.1f}% 戻し、"
            f"その後 {e['days_since_low']} 営業日、安値を更新していません。"
        )
    if kind == "RECOVERY_UNDERCUT":
        return (
            f"{date}の終値 {e['close']:.2f} が、確認済みの安値 {e['confirmed_low']:.2f} を"
            "割り込みました。まだ下落が続いている可能性があります。"
        )
    if kind == "RENEWED_DECLINE":
        return (
            f"{date}の終値 {e['close']:.2f} が、底打ち後の高値 {e['reference_high']:.2f} から "
            f"{e['drawdown_pct']:.1f}% まで下落しました。\n"
            "この高値を基準に、新たな下落局面として追跡し直します。"
        )
    if kind == "UPTREND_ARMED":
        return (
            f"{date}の終値 {e['close']:.2f}。底打ち確認日（{e['base_date'].date()}）の "
            f"{e['base_close']:.2f} から ×{e['multiple']:.1f}。\n"
            f"今後は、高値から下落したら売る、というルールになります。"
            f"現在の売りライン: {e['sell_line']:.2f}（高値が上がれば売りラインも上がります）"
        )
    if kind == "UPTREND_EXIT":
        multiple = f"底打ち確認日（{e['base_date'].date()}）の {e['base_close']:.2f} から ×{e['multiple']:.1f}"
        if e["reason"] == "undercut":
            return (
                f"{date}の終値 {e['close']:.2f}（{multiple}）。\n"
                "目標の倍率に届く前に、確認済みの安値を割り込んだため、"
                "持ち続ける前提が崩れました。"
            )
        peak_pct = (e["close"] / e["peak"] - 1) * 100
        return (
            f"{date}の終値 {e['close']:.2f}。高値 {e['peak']:.2f}（{e['peak_date'].date()}）から "
            f"{peak_pct:.1f}%。{multiple}。\n"
            "上昇の追跡を終了します。"
        )
    if kind == "NORMAL_RESUME":
        return (
            f"{date}の終値 {e['close']:.2f} が、下落局面の元の高値 {e['reference_high']:.2f} を"
            f"回復しました。\nこの局面の最安値: {e['lowest_close']:.2f}（{e['lowest_close_date'].date()}）"
        )
    return str(e)
