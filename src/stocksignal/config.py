"""Every tunable number in one place.

Rule of thumb for this project: if a number appears in a screen, it lives here,
not inline in the screen. That way a change of strategy is a config edit, and
the tests can build a config with deliberately silly values to prove the screen
actually reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Where runtime output goes. Both are gitignored.
CACHE_DIR = Path("cache")
OUT_DIR = Path("out")
DB_PATH = Path("signals.db")


@dataclass(frozen=True)
class Config:
    """Screen thresholds.

    Attributes
    ----------
    sma_fast, sma_slow:
        The two moving averages the rulebook calls "red" and "blue".
        OPEN QUESTION: confirm what these actually are on your charting setup.
        The defaults below (10 and 20) are a placeholder, not a decision.
    min_avg_volume:
        The rulebook says do not trade anything under 200k average volume,
        because getting in and out is too hard.
    min_float:
        Low float means unpredictable. 20 million shares is the proposed floor.
    avg_volume_window:
        How many sessions the average volume is measured over.
    min_history_days:
        Refuse to score a ticker with less history than this. Guards against
        newly listed tickers producing garbage moving averages.
    min_sma_gap_pct:
        The smallest gap that counts as a trend at all. Without this, sideways
        chop where the fast average sits a hair above the slow one reads as a
        (very weak) uptrend and clutters the digest. Anything under this is
        noise, not a trend.
    sma_gap_strong_pct:
        Gap between the two SMAs, as a percentage of the slow SMA, at which the
        trend counts as strong. The rulebook says the wider the gap, the
        stronger the move, so this becomes the score's ceiling.
    level_swing_lookback:
        How many bars either side a bar must beat to count as a swing point.
        Bigger means fewer, more significant pivots.
    level_tolerance_pct:
        How far apart two swing points can be and still be the same level, as a
        percentage of price. A percentage rather than an absolute amount because
        a 1.50 band is a 7.5% zone on a 20 dollar stock and a 0.4% hairline on a
        400 dollar one, and those are not the same claim.
    level_min_touches:
        The rulebook's three-confirmation rule. Fewer touches than this and it is
        a coincidence, not a level.
    level_lookback_days:
        Only swing points inside this many sessions count as touches. Three
        touches spread over two years is not evidence about where price is
        respected now. Roughly one trading year by default.
    level_fresh_days:
        A level last touched within this many sessions scores a full 1.0 for
        recency. Beyond it the score decays in a straight line to 0.0 at
        `level_lookback_days`, so a stale level survives but ranks below a fresh
        one rather than being thrown away.
    level_break_lookback:
        A level that price crossed within this many sessions is flagged as
        flipped. A flip is news; price living above an old ceiling for six months
        is not.
    """

    sma_fast: int = 10
    sma_slow: int = 20
    min_avg_volume: float = 200_000
    min_float: float = 20_000_000
    avg_volume_window: int = 20
    min_history_days: int = 60
    min_sma_gap_pct: float = 0.5
    sma_gap_strong_pct: float = 5.0
    level_swing_lookback: int = 5
    level_tolerance_pct: float = 1.0
    level_min_touches: int = 3
    level_lookback_days: int = 252
    level_fresh_days: int = 21
    level_break_lookback: int = 5

    # Tickers scanned when no watchlist file is given.
    default_watchlist: tuple[str, ...] = field(
        default=("AAPL", "MSFT", "NVDA", "AMD", "TSLA", "SPY", "QQQ", "IWM")
    )

    def __post_init__(self) -> None:
        if self.sma_fast >= self.sma_slow:
            raise ValueError(
                f"sma_fast ({self.sma_fast}) must be shorter than sma_slow ({self.sma_slow})"
            )
        if self.min_history_days < self.sma_slow:
            raise ValueError("min_history_days must cover at least one full slow SMA window")
        if self.min_sma_gap_pct > self.sma_gap_strong_pct:
            raise ValueError("min_sma_gap_pct cannot exceed sma_gap_strong_pct")
        if self.level_tolerance_pct <= 0:
            raise ValueError("level_tolerance_pct must be positive, or nothing ever clusters")
        if self.level_min_touches < 2:
            raise ValueError("level_min_touches must be at least 2, one price is not a level")
        if self.level_fresh_days > self.level_lookback_days:
            raise ValueError("level_fresh_days cannot exceed level_lookback_days")
        if self.level_swing_lookback < 1:
            raise ValueError("level_swing_lookback must be at least 1")


DEFAULT_CONFIG = Config()
