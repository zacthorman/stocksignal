"""Screen 1: can I actually get in and out of this thing?

From the rulebook:
  * Only trade stocks with at least 200k volume, otherwise entry and exit are hard.
  * Do not trade low-float stocks. Always check the float.

This is a hard gate, not a score. Anything that fails here never reaches the
digest, no matter how pretty the chart looks.
"""

from __future__ import annotations

import pandas as pd

from stocksignal.config import Config
from stocksignal.models import Quote, ScreenResult

NAME = "tradability"


def screen_tradability(df: pd.DataFrame, quote: Quote, cfg: Config) -> ScreenResult:
    reasons: list[str] = []
    failures: list[str] = []

    if len(df) < cfg.min_history_days:
        failures.append(f"only {len(df)} sessions of history, need {cfg.min_history_days}")

    if quote.avg_volume < cfg.min_avg_volume:
        failures.append(
            f"avg volume {quote.avg_volume:,.0f} is below the {cfg.min_avg_volume:,.0f} floor"
        )
    else:
        reasons.append(
            f"avg volume {quote.avg_volume:,.0f} clears the {cfg.min_avg_volume:,.0f} floor"
        )

    if quote.shares_float is None:
        # Unknown float is a warning, not a rejection. The rulebook says always
        # check the float, so the digest flags it for a manual look rather than
        # silently dropping a candidate the source simply had no data for.
        reasons.append("float unknown, check it by hand before entry")
    elif quote.shares_float < cfg.min_float:
        failures.append(
            f"float {quote.shares_float:,.0f} is below the {cfg.min_float:,.0f} floor (low float)"
        )
    else:
        reasons.append(f"float {quote.shares_float:,.0f} is above the low-float floor")

    if failures:
        return ScreenResult(name=NAME, passed=False, score=0.0, reasons=tuple(failures))

    # Score is liquidity headroom, capped so a mega-cap does not swamp the total.
    score = min(quote.avg_volume / cfg.min_avg_volume, 5.0)
    return ScreenResult(name=NAME, passed=True, score=score, reasons=tuple(reasons))
