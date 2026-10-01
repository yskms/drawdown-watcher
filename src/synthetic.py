"""Synthetic long-history price series for leveraged ETFs, built from their
underlying index.

Leveraged ETFs only exist since ~2008, so their own history misses the
2000-2002 crash, the full 2008 crash, and long sideways markets where daily
rebalancing decays a 3x fund. A synthetic series replays the index's daily
returns with the ETF's leverage and costs to cover those periods
(see docs/strategy.md "How deep").

    r_etf = L * r_index - (L - 1) * short_rate - expense_ratio   (per day)

The (L - 1) * short_rate term approximates the cost of borrowing the extra
exposure; ^IRX (13-week T-bill) stands in for the short rate. Dividends are
ignored on both sides, consistent with the unadjusted closes used elsewhere.
This is an approximation — compare it against the real ETF on their overlap
(`python -m src.synthetic SPXL`) before trusting it.
"""

from __future__ import annotations

import argparse

import pandas as pd

from src.market_data import fetch_history

TRADING_DAYS = 252
RATE_TICKER = "^IRX"

# ticker -> (underlying index, leverage, annual expense ratio)
# TECL's real underlying (Technology Select Sector Index) has no long public
# history, so the Nasdaq-100 is used as the closest long-lived proxy.
UNDERLYING = {
    "SPXL": ("^GSPC", 3, 0.0091),
    "TECL": ("^NDX", 3, 0.0085),
    "SOXL": ("^SOX", 3, 0.0075),
    "VOO": ("^GSPC", 1, 0.0003),
}


def synthetic_history(ticker: str, start: str = "1960-01-01") -> pd.Series:
    """Synthetic daily closes for `ticker`, scaled to start at 100."""
    index_ticker, leverage, expense = UNDERLYING[ticker]
    index_close = fetch_history(index_ticker, start=start).dropna()
    daily = index_close.pct_change().dropna()

    cost = expense / TRADING_DAYS
    if leverage > 1:
        rate = fetch_history(RATE_TICKER, start=start).dropna() / 100 / TRADING_DAYS
        rate = rate.reindex(daily.index).ffill()
        daily = daily[rate.notna()]
        cost = cost + (leverage - 1) * rate[rate.notna()]

    synthetic_return = (leverage * daily - cost).clip(lower=-0.99)
    return 100 * (1 + synthetic_return).cumprod()


def compare_with_actual(ticker: str) -> None:
    """Prints how closely the synthetic series tracks the real ETF."""
    actual = fetch_history(ticker).dropna()
    synthetic = synthetic_history(ticker)
    common = actual.index.intersection(synthetic.index)
    actual, synthetic = actual.loc[common], synthetic.loc[common]

    years = (common[-1] - common[0]).days / 365.25
    actual_total = actual.iloc[-1] / actual.iloc[0]
    synthetic_total = synthetic.iloc[-1] / synthetic.iloc[0]
    correlation = actual.pct_change().corr(synthetic.pct_change())

    print(f"{ticker} vs synthetic ({UNDERLYING[ticker][0]} x{UNDERLYING[ticker][1]}), "
          f"{common[0].date()} - {common[-1].date()} ({years:.1f}y)")
    print(f"  total return: actual x{actual_total:.1f}, synthetic x{synthetic_total:.1f}")
    print(f"  daily return correlation: {correlation:.3f}")
    print(f"  max drawdown: actual {(actual / actual.cummax() - 1).min() * 100:.1f}%, "
          f"synthetic {(synthetic / synthetic.cummax() - 1).min() * 100:.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+", choices=sorted(UNDERLYING))
    args = parser.parse_args()
    for ticker in args.tickers:
        compare_with_actual(ticker)


if __name__ == "__main__":
    main()
