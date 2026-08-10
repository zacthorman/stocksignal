"""Pure maths on a price frame. No I/O, no config, no opinions.

Every function here takes data and returns data. That makes them trivial to
test, because a test is just "here are twenty numbers, here is the answer I
worked out by hand".

Keep this file boring. Judgment belongs in `screens/`, not here.
"""

from __future__ import annotations

import numpy as np
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


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index, using Wilder's original smoothing.

    Gate 3 of the entry checklist is "is this a good deal", answered by where
    price sits against the oversold and overbought lines. This is that reading.

    Wilder's method, not an exponential moving average that merely resembles it:
    the first average gain and loss are the plain mean of the first `period`
    changes, and every value after that is `(previous * (period - 1) + today) /
    period`. Seeding the recursion off a single bar instead, which is what
    `ewm(adjust=False)` does if you point it at the raw series, gives numbers
    that differ from the chart for the first hundred bars or so. The whole point
    of this reading is to agree with what the platform draws.

    The first `period` values are NaN, for the same reason `sma` leaves them NaN.
    A flat stretch with no gains and no losses returns 50, the neutral reading,
    because 0/0 is not information.
    """
    if period < 2:
        raise ValueError("period must be at least 2")

    delta = series.astype(float).diff()
    gains = delta.clip(lower=0.0).to_numpy()
    losses = (-delta).clip(lower=0.0).to_numpy()

    n = len(series)
    out = np.full(n, np.nan)
    if n <= period:
        return pd.Series(out, index=series.index, name="rsi")

    # Index 0 is the NaN from .diff(), so the seed window is 1..period inclusive.
    avg_gain = float(np.mean(gains[1 : period + 1]))
    avg_loss = float(np.mean(losses[1 : period + 1]))
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = _rsi_from(avg_gain, avg_loss)

    return pd.Series(out, index=series.index, name="rsi")


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    """One RSI value from a smoothed gain and loss, with the edges pinned."""
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def beta(closes: pd.Series, benchmark_closes: pd.Series, window: int = 252) -> float | None:
    """Beta of a stock against a benchmark, from daily returns.

    The course's third scan filter wants beta of at least 2, on the reasoning
    that swing setups need something that moves more than the market does.

    Returns None rather than a number when it cannot be measured honestly:
    fewer than two overlapping sessions, or a benchmark that never moved. None
    means unknown, and unknown is handled as a warning upstream, not as a zero.

    Both series are aligned on their index before anything is computed, so a
    ticker that was not trading on some of the benchmark's sessions contributes
    only the days the two genuinely share.
    """
    if window < 2:
        raise ValueError("window must be at least 2")

    paired = pd.concat(
        [closes.astype(float).rename("asset"), benchmark_closes.astype(float).rename("bench")],
        axis=1,
        join="inner",
    ).dropna()
    if len(paired) < 2:
        return None

    returns = paired.pct_change().dropna().tail(window)
    if len(returns) < 2:
        return None

    bench_var = float(returns["bench"].var())
    if bench_var == 0.0:
        return None

    return float(returns["asset"].cov(returns["bench"]) / bench_var)


def body_and_wick(row: pd.Series) -> tuple[float, float]:
    """Candle body size and total wick size for one bar.

    The rulebook's ignition-bar test needs both: a strong igniting bar is a big
    body, and massive wicks disqualify the small bar before it.
    """
    body = abs(float(row["close"]) - float(row["open"]))
    span = float(row["high"]) - float(row["low"])
    return body, max(span - body, 0.0)
