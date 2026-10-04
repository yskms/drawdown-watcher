import pandas as pd

from src.event_format import event_title_ja, format_event_ja

_D = pd.Timestamp("2026-03-10")
_LOW_DATE = pd.Timestamp("2026-02-20")
_BASE_DATE = pd.Timestamp("2026-01-05")
_PEAK_DATE = pd.Timestamp("2026-03-01")


def test_drawdown_mode_enter():
    e = {
        "date": _D, "event": "DRAWDOWN_MODE_ENTER", "close": 70.0,
        "reference_high": 100.0, "drawdown_pct": -30.0, "streak_trading_days": 1,
    }

    assert event_title_ja(e) == "下落局面に入りました"
    body = format_event_ja(e)
    assert "2026-03-10の終値 70.00" in body
    assert "高値 100.00 から -30.0%" in body
    assert "streak" not in body


def test_level_trigger_names_the_level():
    e = {
        "date": _D, "event": "LEVEL_TRIGGER", "level": -50.0, "level_index": 2, "close": 48.0,
        "reference_high": 100.0, "drawdown_pct": -52.0, "streak_trading_days": 1,
    }

    assert event_title_ja(e) == "警戒ライン2（-50%）に到達しました"
    assert "高値 100.00 から -52.0%" in format_event_ja(e)


def test_recovery_confirmed():
    e = {
        "date": _D, "event": "RECOVERY_CONFIRMED", "close": 60.0, "lowest_close": 50.0,
        "lowest_close_date": _LOW_DATE, "recovery_pct": 20.0, "days_since_low": 12,
    }

    assert event_title_ja(e) == "底打ちを確認しました"
    body = format_event_ja(e)
    assert "最安値 50.00（2026-02-20）から +20.0%" in body
    assert "12 営業日" in body


def test_recovery_undercut():
    e = {"date": _D, "event": "RECOVERY_UNDERCUT", "close": 49.0, "confirmed_low": 50.0}

    assert event_title_ja(e) == "底打ちの確認が取り消されました"
    assert "確認済みの安値 50.00" in format_event_ja(e)


def test_renewed_decline():
    e = {
        "date": _D, "event": "RENEWED_DECLINE", "close": 56.0, "reference_high": 80.0,
        "drawdown_pct": -30.0, "streak_trading_days": 1,
    }

    assert "新たな下落局面" in event_title_ja(e)
    assert "底打ち後の高値 80.00 から -30.0%" in format_event_ja(e)


def test_uptrend_armed_states_the_sell_line():
    e = {
        "date": _D, "event": "UPTREND_ARMED", "close": 204.0, "base_close": 100.0,
        "base_date": _BASE_DATE, "multiple": 2.04, "sell_line": 142.8,
    }

    assert event_title_ja(e) == "底打ち確認時の2.0倍に到達しました（売りルール有効）"
    body = format_event_ja(e)
    assert "底打ち確認日（2026-01-05）の 100.00 から ×2.0" in body
    assert "売りライン: 142.80" in body


def test_uptrend_exit_by_trail_reports_the_drop_from_peak():
    e = {
        "date": _D, "event": "UPTREND_EXIT", "reason": "trail", "close": 140.0,
        "base_close": 100.0, "base_date": _BASE_DATE, "peak": 200.0, "peak_date": _PEAK_DATE,
        "multiple": 1.4,
    }

    assert "上昇が一巡した可能性" in event_title_ja(e)
    body = format_event_ja(e)
    assert "高値 200.00（2026-03-01）から -30.0%" in body
    assert "×1.4" in body


def test_uptrend_exit_by_undercut_says_the_bottom_call_failed():
    e = {
        "date": _D, "event": "UPTREND_EXIT", "reason": "undercut", "close": 85.0,
        "base_close": 100.0, "base_date": _BASE_DATE, "peak": 110.0, "peak_date": _PEAK_DATE,
        "multiple": 0.85,
    }

    assert "底打ちの確認が取り消された" in event_title_ja(e)
    assert "確認済みの安値を割り込んだ" in format_event_ja(e)


def test_normal_resume():
    e = {
        "date": _D, "event": "NORMAL_RESUME", "close": 101.0, "reference_high": 100.0,
        "lowest_close": 50.0, "lowest_close_date": _LOW_DATE,
    }

    assert event_title_ja(e) == "高値を回復し、平常に戻りました"
    body = format_event_ja(e)
    assert "元の高値 100.00 を回復" in body
    assert "最安値: 50.00（2026-02-20）" in body


def test_unknown_event_falls_back_instead_of_raising():
    e = {"date": _D, "event": "SOMETHING_NEW"}

    assert event_title_ja(e) == "SOMETHING_NEW"
    assert "SOMETHING_NEW" in format_event_ja(e)
