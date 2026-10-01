"""Fetches and caches daily closing prices for a ticker.

Raw price data isn't redistributable, so it's cached under data/ (gitignored)
rather than committed. See docs/architecture.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def cache_path(ticker: str) -> Path:
    return DATA_DIR / f"{ticker}.csv"


def fetch_history(ticker: str, start: str = "2005-01-01", refresh: bool = False) -> pd.Series:
    """Daily close prices for `ticker`, indexed by date. Cached under data/."""
    path = cache_path(ticker)

    if not refresh and path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df["Close"]

    import yfinance as yf

    df = yf.Ticker(ticker).history(start=start, auto_adjust=False)
    if df.empty:
        raise ValueError(f"No data returned for {ticker}")

    close = df["Close"]
    close.index = close.index.tz_localize(None)
    close.index.name = "Date"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    close.to_frame(name="Close").to_csv(path)

    return close
