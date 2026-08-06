"""Screen 2: is this in an uptrend by the rulebook's definition?

From the rulebook:
  * Short SMA above long SMA means uptrend, below means downtrend.
  * The wider the gap, the stronger the move.
  * Only take trades above BOTH moving averages.

Three separate conditions, all required. The score is the gap width, normalised
so that a gap at or beyond `sma_gap_strong_pct` scores a full 1.0.

OPEN QUESTION carried from the strategy notes: the real periods for the red and
blue lines on your charting setup are still unconfirmed. `Config.sma_fast` and
`Config.sma_slow` default to 10 and 20 as a placeholder. Change them in one
place the moment you know, and rerun the tests.
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
    gap = pct_gap(float(fast), float(slow))

    failures: list[str] = []
    if fast <= slow:
        failures.append(
            f"fast SMA {fast:.2f} is not above slow SMA {slow:.2f} (downtrend by the rulebook)"
        )
    if close <= fast:
        failures.append(f"close {close:.2f} is not above the {cfg.sma_fast}-day SMA {fast:.2f}")
    if close <= slow:
        failures.append(f"close {close:.2f} is not above the {cfg.sma_slow}-day SMA {slow:.2f}")
    if 0 < gap < cfg.min_sma_gap_pct:
        failures.append(
            f"SMA gap {gap:.2f}% is under the {cfg.min_sma_gap_pct:.2f}% floor, "
            "this is chop rather than a trend"
        )

    if failures:
        return ScreenResult(name=NAME, passed=False, score=0.0, reasons=tuple(failures))

    strength = min(gap / cfg.sma_gap_strong_pct, 1.0) if cfg.sma_gap_strong_pct > 0 else 0.0
    label = "strong" if strength >= 1.0 else "modest" if strength >= 0.4 else "weak"
    reasons = (
        f"close {close:.2f} is above both averages ({fast:.2f} / {slow:.2f})",
        f"SMA gap {gap:.2f}% reads as a {label} uptrend",
    )
    return ScreenResult(name=NAME, passed=True, score=strength, reasons=reasons)
