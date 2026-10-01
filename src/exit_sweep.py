"""Compares uptrend exit rules (see docs/strategy.md "After the bottom:
holding the uptrend"): how a holder would have done buying at each bottom
call that starts uptrend tracking, then selling per each rule.

Results compound across cycles, sitting in cash (0%) between a sell and
the next bottom call. Two baselines run alongside the trail_from_peak
candidates: selling at a fixed 2x, and never selling.

Usage:
    python -m src.exit_sweep SPXL --trail -20 -30 -40 -50
    python -m src.exit_sweep SPXL --trail -30 -40 --synthetic
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.backtest import load_config, load_close, ticker_config
from src.drawdown import rolling_high
from src.state_machine import run


def _trades_by_rule(close: pd.Series, events: list[dict]) -> list[tuple[str, float]]:
    """(label, multiple) per round trip, from run()'s uptrend events."""
    starts = [e for e in events if e.get("starts_uptrend")]
    exits = {e["base_date"]: e for e in events if e["event"] == "UPTREND_EXIT"}
    trades = []
    for s in starts:
        exit_event = exits.get(s["date"])
        if exit_event:
            trades.append((f"{s['date'].year}-{exit_event['date'].year}", exit_event["multiple"]))
        else:
            trades.append((f"{s['date'].year}-open", close.iloc[-1] / s["close"]))
    return trades


def _trades_fixed_multiple(close: pd.Series, buy_dates: set, multiple: float | None) -> list[tuple[str, float]]:
    """Baseline: buy at a bottom call when flat, sell at `multiple` x (never if None)."""
    trades, base = [], None
    for date, price in close.items():
        if base is None:
            if date in buy_dates:
                base = (date, price)
            continue
        if multiple is not None and price >= base[1] * multiple:
            trades.append((f"{base[0].year}-{date.year}", price / base[1]))
            base = None
    if base:
        trades.append((f"{base[0].year}-open", close.iloc[-1] / base[1]))
    return trades


def _summarize(name: str, trades: list[tuple[str, float]]) -> str:
    total = 1.0
    for _, m in trades:
        total *= m
    detail = " ".join(f"{label}:x{m:.1f}" for label, m in trades)
    return f"  {name:<22} total x{total:8.1f}   {detail}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker")
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument("--trail", type=float, nargs="+", default=[-20, -30, -40, -50])
    parser.add_argument("--hold-until", type=float, default=2.0)
    parser.add_argument("--synthetic", action="store_true", help="use the synthetic long history")
    args = parser.parse_args()

    base_config = ticker_config(load_config(Path(args.config))[args.ticker])
    close = load_close(args.ticker, synthetic=args.synthetic)
    high = rolling_high(close)

    print(f"\n{args.ticker}{' (synthetic)' if args.synthetic else ''}  "
          f"{close.index[0].date()} - {close.index[-1].date()}")

    plain = run(close, high, replace(base_config, trail_from_peak=None))
    buy_dates = {e["date"] for e in plain if e["event"] == "RECOVERY_CONFIRMED"}
    print(_summarize("sell at 2x", _trades_fixed_multiple(close, buy_dates, 2.0)))

    for trail in args.trail:
        config = replace(base_config, trail_from_peak=trail, hold_until_multiple=args.hold_until)
        events = run(close, high, config)
        name = f"hold {args.hold_until:g}x, then {trail:g}%"
        print(_summarize(name, _trades_by_rule(close, events)))

    print(_summarize("never sell", _trades_fixed_multiple(close, buy_dates, None)))


if __name__ == "__main__":
    main()
