"""Pure maths on a price frame. No I/O, no config, no opinions.

Every function here takes data and returns data. That makes them trivial to
test, because a test is just "here are twenty numbers, here is the answer I
worked out by hand".

Keep this file boring. Judgment belongs in `screens/`, not here.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average.

    Uses `min_periods=window`, so the first `window - 1` values are NaN rather
    than a partial average computed from too few points. A partial average looks
    like a number and lies like one.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    return series.rolling(window=window, min_periods=window).mean()


def average_volume(volume: pd.Series, window: int = 20) -> float:
    """Mean volume over the last `window` sessions."""
    if len(volume) < window:
        window = len(volume)
    if window == 0:
        return 0.0
    return float(volume.tail(window).mean())


def pct_gap(fast: float, slow: float) -> float:
    """Gap between two moving averages, as a percentage of the slower one.

    Positive means the fast average is above the slow one, which the rulebook
    reads as an uptrend. Magnitude is the strength of that read.
    """
    if slow == 0:
        return 0.0
    return (fast - slow) / slow * 100.0


def swing_points(high: pd.Series, low: pd.Series, lookback: int = 5) -> tuple[pd.Series, pd.Series]:
    """Local highs and lows: a bar higher (or lower) than `lookback` bars either side.

    These are the raw material for support and resistance levels. Clustering
    them into levels, and applying the three-touch rule, is your job in the
    breakout screen. This function only finds the candidates.
    """
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    window = 2 * lookback + 1
    is_high = high == high.rolling(window, center=True).max()
    is_low = low == low.rolling(window, center=True).min()
    return high[is_high], low[is_low]


def true_range(df: pd.DataFrame) -> pd.Series:
    """Classic true range: the widest of today's span and the two gap measures."""
    prev_close = df["close"].shift(1)
    spans = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return spans.max(axis=1)


def body_and_wick(row: pd.Series) -> tuple[float, float]:
    """Candle body size and total wick size for one bar.

    The rulebook's ignition-bar test needs both: a strong igniting bar is a big
    body, and massive wicks disqualify the small bar before it.
    """
    body = abs(float(row["close"]) - float(row["open"]))
    span = float(row["high"]) - float(row["low"])
    return body, max(span - body, 0.0)
