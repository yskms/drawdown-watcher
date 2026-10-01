"""Sweeps watch_threshold candidates against history to support Phase 2
threshold decisions (see docs/strategy.md): how often would Drawdown Mode
have fired at each depth, and how does the recovery timeline look once in
it.

Usage:
    python -m src.threshold_sweep SPXL --watch -20 -25 -30 -35
    python -m src.threshold_sweep SPXL --watch -30 --profile-at -30
    python -m src.threshold_sweep SPXL --watch -40 -45 -50 --synthetic
"""

from __future__ import annotations

import argparse

from src.backtest import format_event, load_close
from src.drawdown import rolling_high
from src.state_machine import TickerConfig, run

DEFAULT_RECOVERY_THRESHOLD = 15
DEFAULT_RECOVERY_CONFIRM_DAYS = 10


def sweep_watch_threshold(
    ticker: str,
    thresholds: list[float],
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD,
    recovery_confirm_days: int = DEFAULT_RECOVERY_CONFIRM_DAYS,
    synthetic: bool = False,
) -> None:
    close = load_close(ticker, synthetic=synthetic)
    high = rolling_high(close)
    years = (close.index[-1] - close.index[0]).days / 365.25

    print(f"\n{ticker}  ({close.index[0].date()} - {close.index[-1].date()}, {years:.1f}y)")

    for wt in thresholds:
        config = TickerConfig(
            watch_threshold=wt,
            levels=[],
            recovery_threshold=recovery_threshold,
            recovery_confirm_days=recovery_confirm_days,
        )
        events = run(close, high, config)
        # Both are the tier-1 "pay attention" alert. Counting only ENTER
        # misses every crash inside a long episode (e.g. a 3x fund that never
        # regains its 2000 high, so 2008 arrives as a RENEWED_DECLINE).
        enters = [
            e for e in events if e["event"] in ("DRAWDOWN_MODE_ENTER", "RENEWED_DECLINE")
        ]
        enter_years = [
            f"{e['date'].year}{'r' if e['event'] == 'RENEWED_DECLINE' else ''}" for e in enters
        ]
        avg_interval = years / len(enters) if enters else float("inf")
        print(
            f"  watch={wt:>5.0f}%  count={len(enters):>2}  "
            f"avg_interval={avg_interval:4.1f}y  years={' '.join(enter_years)}"
        )
    print("  (r = RENEWED_DECLINE inside a still-open episode)")


def recovery_profile(
    ticker: str,
    watch_threshold: float,
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD,
    recovery_confirm_days: int = DEFAULT_RECOVERY_CONFIRM_DAYS,
    synthetic: bool = False,
) -> None:
    close = load_close(ticker, synthetic=synthetic)
    high = rolling_high(close)
    config = TickerConfig(
        watch_threshold=watch_threshold,
        levels=[],
        recovery_threshold=recovery_threshold,
        recovery_confirm_days=recovery_confirm_days,
    )
    events = run(close, high, config)

    print(f"\n{ticker}  watch_threshold={watch_threshold:.0f}%  recovery profile")
    for e in events:
        print(" ", format_event(e))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker")
    parser.add_argument("--watch", type=float, nargs="+", default=[-20, -25, -30, -35, -40])
    parser.add_argument(
        "--profile-at", type=float, help="also print the recovery profile at this watch_threshold"
    )
    parser.add_argument("--recovery-threshold", type=float, default=DEFAULT_RECOVERY_THRESHOLD)
    parser.add_argument("--recovery-confirm-days", type=int, default=DEFAULT_RECOVERY_CONFIRM_DAYS)
    parser.add_argument(
        "--synthetic", action="store_true", help="use the synthetic long history (see src/synthetic.py)"
    )
    args = parser.parse_args()

    sweep_watch_threshold(
        args.ticker, args.watch, args.recovery_threshold, args.recovery_confirm_days, args.synthetic
    )
    if args.profile_at is not None:
        recovery_profile(
            args.ticker,
            args.profile_at,
            args.recovery_threshold,
            args.recovery_confirm_days,
            args.synthetic,
        )


if __name__ == "__main__":
    main()
