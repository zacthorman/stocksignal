"""Test helpers: builders for price frames with a deliberate shape.

Kept separate from conftest.py so they can be imported explicitly. Fixtures are
for things pytest injects; plain builders are for things you call.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stocksignal.models import Quote


def make_bars(closes: list[float], volume: float = 1_000_000) -> pd.DataFrame:
    """Build a bar frame from a list of closing prices."""
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp("2026-08-05"), periods=n)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, float(volume)),
        },
        index=idx,
    )


def quote_from(
    df: pd.DataFrame,
    ticker: str = "TEST",
    shares_float: float | None = 50_000_000,
    beta: float | None = None,
) -> Quote:
    last = df.iloc[-1]
    stamp = df.index[-1]
    return Quote(
        ticker=ticker,
        as_of=stamp.date() if hasattr(stamp, "date") else date.today(),
        close=float(last["close"]),
        avg_volume=float(df["volume"].tail(10).mean()),
        latest_volume=float(last["volume"]),
        shares_float=shares_float,
        beta=beta,
    )
