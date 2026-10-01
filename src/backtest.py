"""Backtest runner: compares the 52-week-high method against all-time-high,
and reports when Drawdown Watcher would have historically fired.

Usage:
    python -m src.backtest [--config config/config.example.yaml] [--refresh]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from src.drawdown import all_time_high, rolling_high
from src.market_data import fetch_history
from src.state_machine import TickerConfig, run


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["tickers"]


def ticker_config(cfg: dict) -> TickerConfig:
    return TickerConfig(
        watch_threshold=cfg["watch_threshold"],
        levels=cfg["levels"],
        recovery_threshold=cfg["recovery_threshold"],
        recovery_confirm_days=cfg["recovery_confirm_days"],
    )


def format_event(e: dict) -> str:
    date = e["date"].date()
    if e["event"] == "DRAWDOWN_MODE_ENTER":
        return (
            f"{date}  DRAWDOWN MODE ENTER   close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  drawdown={e['drawdown_pct']:.1f}%  "
            f"streak={e['streak_trading_days']}d"
        )
    if e["event"] == "LEVEL_TRIGGER":
        return (
            f"{date}  LEVEL {e['level_index']} ({e['level']:.0f}%)     "
            f"close={e['close']:.2f}  ref_high={e['reference_high']:.2f}  "
            f"drawdown={e['drawdown_pct']:.1f}%  streak={e['streak_trading_days']}d"
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
        return (
            f"{date}  RENEWED DECLINE       close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  drawdown={e['drawdown_pct']:.1f}%  "
            f"streak={e['streak_trading_days']}d"
        )
    if e["event"] == "NORMAL_RESUME":
        return (
            f"{date}  NORMAL RESUME         close={e['close']:.2f}  "
            f"ref_high={e['reference_high']:.2f}  "
            f"low={e['lowest_close']:.2f} on {e['lowest_close_date'].date()}"
        )
    return str(e)


def summarize_ticker(ticker: str, close: pd.Series, cfg: dict) -> None:
    config = ticker_config(cfg)

    print(f"\n{'=' * 78}")
    print(
        f"{ticker}  ({close.index[0].date()} - {close.index[-1].date()}, "
        f"{len(close)} trading days)"
    )
    print(f"{'=' * 78}")

    print("\n-- 52-week high method --")
    events_52w = run(close, rolling_high(close), config)
    if not events_52w:
        print("  (no events)")
    for e in events_52w:
        print(" ", format_event(e))

    print("\n-- All-time-high method (comparison) --")
    events_ath = run(close, all_time_high(close), config)
    if not events_ath:
        print("  (no events)")
    for e in events_ath:
        print(" ", format_event(e))

    enters_52w = [e["date"] for e in events_52w if e["event"] == "DRAWDOWN_MODE_ENTER"]
    enters_ath = [e["date"] for e in events_ath if e["event"] == "DRAWDOWN_MODE_ENTER"]
    if enters_52w != enters_ath:
        print("\n  !! 52-week vs all-time-high DIVERGE on DRAWDOWN MODE ENTER dates:")
        print(f"     52w : {[d.date() for d in enters_52w]}")
        print(f"     ath : {[d.date() for d in enters_ath]}")

    max_dd = (close / rolling_high(close) - 1).min() * 100
    print(f"\n  Max drawdown (52w method): {max_dd:.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument(
        "--refresh", action="store_true", help="ignore data/ cache and refetch"
    )
    args = parser.parse_args()

    tickers_cfg = load_config(Path(args.config))

    for ticker, cfg in tickers_cfg.items():
        close = fetch_history(ticker, refresh=args.refresh)
        summarize_ticker(ticker, close, cfg)


if __name__ == "__main__":
    main()
