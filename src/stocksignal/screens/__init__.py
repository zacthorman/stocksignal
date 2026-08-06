"""One module per screen.

A screen is a function with this shape:

    def screen_x(df: pd.DataFrame, quote: Quote, cfg: Config) -> ScreenResult

It reads price data plus config, and returns a pass/fail with a score and the
reasons behind it. It does no I/O and it never prints. That keeps every screen
independently testable and lets the scanner compose them freely.

Shipped: tradability, trend.
Yours to build: breakout, levels, dilution, red-day, exits. See BUILD-PLAN.md.
"""

from stocksignal.screens.tradability import screen_tradability
from stocksignal.screens.trend import screen_trend

__all__ = ["screen_tradability", "screen_trend"]
