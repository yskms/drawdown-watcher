"""Backtest runner: compares the 52-week-high method against all-time-high,
and reports when Drawdown Watcher would have historically fired.

Usage:
    python -m src.backtest [--config config/config.example.yaml] [--refresh] [--synthetic]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.config import load_config, ticker_config
from src.drawdown import all_time_high, rolling_high
from src.event_format import format_event
from src.market_data import fetch_history
from src.state_machine import run
from src.synthetic import synthetic_history


def load_close(ticker: str, refresh: bool = False, synthetic: bool = False) -> pd.Series:
    """Daily closes, with missing values dropped -- a NaN close silently
    compares false everywhere in the state machine instead of failing."""
    if synthetic:
        return synthetic_history(ticker)
    return fetch_history(ticker, refresh=refresh).dropna()


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
    parser.add_argument(
        "--synthetic", action="store_true",
        help="use the synthetic long history built from each ticker's underlying index",
    )
    args = parser.parse_args()

    tickers_cfg = load_config(Path(args.config))

    for ticker, cfg in tickers_cfg.items():
        close = load_close(ticker, refresh=args.refresh, synthetic=args.synthetic)
        summarize_ticker(ticker, close, cfg)


if __name__ == "__main__":
    main()
