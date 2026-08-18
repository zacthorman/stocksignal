"""Screen 2: is this in an uptrend by the rulebook's definition?

From the rulebook:
  * Short SMA above long SMA means uptrend, below means downtrend.
  * The wider the gap, the stronger the move.
  * Only take trades above BOTH moving averages.

Three separate conditions, all required. The score is the gap width, normalised
so that a gap at or beyond `sma_gap_strong_pct` scores a full 1.0.

The periods are settled: 9 and 180, read off page 44 of the course on
2026-08-10. See `Config.sma_fast`.

WHICH PRICE THE SHORT SMA IS TESTED AGAINST. The OPEN, not the close. Page 116
is explicit and the parenthesis is the whole point: "FIRST CANDLESTICK HOLDING
(OPENING) ABOVE THE BLUE SMA LINE". Page 111 states the mirror of it for the
exit, on AMRN: a candle that dipped below the line "didn't open below the line.
That means it was not a Validation." Until 2026-08-14 this screen tested the
close on both averages, which let in any bar that opened under the 9 and
recovered by the bell. That is a different bar from the one the course names.

The LONG SMA is still tested on the close. Page 115 item 4 asks only whether you
are "trading above the long-term SMA line" and never specifies a price field, so
there is nothing to correct there.

STILL OPEN, and deliberately not changed here. The course's entry trigger is an
EVENT, the first candlestick holding above the line, and this screen asks a
STATE question: is it above the line at all. One fires once per move, the other
every day of it. The price-field fix above does not settle that; it is a
separate decision and `Config.trend_entry` already carries it for the backtest.
"""

from __future__ import annotations

import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import pct_gap, sma
from stocksignal.models import Quote, ScreenResult

NAME = "trend"


def screen_trend(df: pd.DataFrame, quote: Quote, cfg: Config) -> ScreenResult:
    if len(df) < cfg.sma_slow:
        return ScreenResult(
            name=NAME,
            passed=False,
            reasons=(f"not enough history for a {cfg.sma_slow}-day average",),
        )

    fast = sma(df["close"], cfg.sma_fast).iloc[-1]
    slow = sma(df["close"], cfg.sma_slow).iloc[-1]
    if pd.isna(fast) or pd.isna(slow):
        return ScreenResult(name=NAME, passed=False, reasons=("moving averages not yet defined",))

    close = quote.close
    open_ = float(df["open"].iloc[-1])
    gap = pct_gap(float(fast), float(slow))

    failures: list[str] = []
    if fast <= slow:
        failures.append(
            f"fast SMA {fast:.2f} is not above slow SMA {slow:.2f} (downtrend by the rulebook)"
        )
    if not (open_ > fast):
        failures.append(f"open {open_:.2f} is not above the {cfg.sma_fast}-day SMA {fast:.2f}")
    if close <= slow:
        failures.append(f"close {close:.2f} is not above the {cfg.sma_slow}-day SMA {slow:.2f}")
    if 0 < gap < cfg.min_sma_gap_pct:
        failures.append(
            f"SMA gap {gap:.2f}% is under the {cfg.min_sma_gap_pct:.2f}% floor, "
            "this is chop rather than a trend"
        )

    if failures:
        return ScreenResult(name=NAME, passed=False, score=0.0, reasons=tuple(failures))

    strength, note = _score_gap(df, cfg, gap)
    reasons = (
        f"opened {open_:.2f} above the {cfg.sma_fast}-day SMA {fast:.2f}, "
        f"close {close:.2f} above the {cfg.sma_slow}-day {slow:.2f}",
        note,
    )
    return ScreenResult(name=NAME, passed=True, score=strength, reasons=reasons)


def qualifying_gap_history(df: pd.DataFrame, cfg: Config) -> pd.Series:
    """Every past gap reading on a bar this screen would have been scoring.

    Relative scoring compares today against the stock's own past, and the only
    honest comparison set is bars that cleared the same conditions today did.
    Including downtrends would drag the distribution negative and flatter any
    uptrend into looking exceptional.
    """
    fast = sma(df["close"], cfg.sma_fast)
    slow = sma(df["close"], cfg.sma_slow)
    close = df["close"]
    qualifies = (fast > slow) & (close > fast) & (close > slow)
    gaps = ((fast - slow) / slow * 100.0)[qualifies].dropna()
    return gaps.tail(cfg.gap_relative_lookback)


def _score_gap(df: pd.DataFrame, cfg: Config, gap: float) -> tuple[float, str]:
    """Turn today's gap into a 0 to 1 score, plus the sentence explaining it."""
    if cfg.gap_scoring == "relative":
        history = qualifying_gap_history(df, cfg)
        if len(history) >= cfg.gap_relative_min_samples:
            strength = float((history < gap).mean())
            label = "strong" if strength >= 0.9 else "modest" if strength >= 0.5 else "weak"
            return strength, (
                f"SMA gap {gap:.2f}% is wider than {strength:.0%} of this ticker's own "
                f"{len(history)} past uptrend readings, a {label} trend for this stock"
            )
        # Not enough of its own history to rank against, so fall back rather
        # than quote a percentile computed from a handful of points.
        strength = _absolute(gap, cfg)
        return strength, (
            f"SMA gap {gap:.2f}% scored against the fixed {cfg.sma_gap_strong_pct:.1f}% ceiling: "
            f"only {len(history)} past readings, under the {cfg.gap_relative_min_samples} "
            "needed to rank it against itself"
        )

    strength = _absolute(gap, cfg)
    label = "strong" if strength >= 1.0 else "modest" if strength >= 0.4 else "weak"
    return strength, f"SMA gap {gap:.2f}% reads as a {label} uptrend"


def _absolute(gap: float, cfg: Config) -> float:
    if cfg.sma_gap_strong_pct <= 0:
        return 0.0
    return min(gap / cfg.sma_gap_strong_pct, 1.0)
