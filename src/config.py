"""Shared config loading for backtest.py and main.py."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.state_machine import TickerConfig


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["tickers"]


def ticker_config(cfg: dict) -> TickerConfig:
    return TickerConfig(
        watch_threshold=cfg["watch_threshold"],
        levels=cfg["levels"],
        recovery_threshold=cfg["recovery_threshold"],
        recovery_confirm_days=cfg["recovery_confirm_days"],
        hold_until_multiple=cfg.get("hold_until_multiple", 2.0),
        trail_from_peak=cfg.get("trail_from_peak"),
    )
