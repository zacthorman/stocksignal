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
        The two moving averages the rulebook calls "blue" and "red". Settled
        2026-08-10 from the course itself, page 44, which states the setup
        verbatim: long term (directional strength) is (Close, 180), short term
        (price strength) is (Close, 9). Blue is the 9 and measures price
        strength; red is the 180 and measures directional strength.

        These were 10 and 20 as a placeholder until that page was read. Note
        what a 180 really is: at roughly 8 to 9 months of trading days it is a
        regime line, not a swing filter. Anything tuned against the old pair
        needs re-deriving, not nudging.
    min_price:
        The course scans with a 15 dollar floor (page 142). Reasoning given:
        below that, moves get sporadic, which is tolerable when you are out the
        same day and dangerous when you are holding for a week.
    min_avg_volume:
        100k, from the same scan filter on page 142. Below it, getting out of a
        swing position inside a week becomes the problem. This was 200k, which
        was stricter than the source it came from.
    min_beta, beta_window, beta_benchmark:
        The third of the course's three scan filters: beta of at least 2,
        because swing setups want volatility relative to the market. The course
        specifies the threshold but never the measurement window, so 252
        sessions (about a trading year) against SPY is this project's choice,
        not the course's. Beta is unknown unless a benchmark series is supplied,
        and unknown is a warning rather than a rejection, exactly as float is.
    rsi_period, rsi_oversold, rsi_overbought:
        Gate 3 of the entry checklist (page 115) asks whether the stock is a
        "good deal": below fair value is an okay deal, oversold is a good deal.
        The course reads oversold and overbought off the chart's own lines and
        never prints the numbers, so 14 / 30 / 70 here are the Thinkorswim
        defaults it would have been using. Assumption, not scripture: worth
        confirming against the platform.
    min_float:
        Low float means unpredictable. 20 million shares is the proposed floor.
    avg_volume_window:
        How many sessions the average volume is measured over.
    min_history_days:
        Refuse to score a ticker with less history than this. Guards against
        newly listed tickers producing garbage moving averages. Must clear
        `sma_slow`, so a 180-period slow average drags this from 60 up to 200.
        See also the `required_history` property, which is what callers should
        ask for when fetching.
    min_sma_gap_pct:
        The smallest gap that counts as a trend at all. Without this, sideways
        chop where the fast average sits a hair above the slow one reads as a
        (very weak) uptrend and clutters the digest. Anything under this is
        noise, not a trend.
    sma_gap_strong_pct:
        Gap between the two SMAs, as a percentage of the slow SMA, at which the
        trend counts as strong. The rulebook says the wider the gap, the
        stronger the move, so this becomes the score's ceiling.

        MEASURED 2026-08-10 by `scripts/calibrate.py`, over 8,859 qualifying
        bars across the 19-ticker watchlist and roughly six years of history.
        Qualifying means the bars the trend screen would actually be scoring:
        fast above slow, close above both. Measuring across all bars instead
        would describe a population these numbers are never applied to.

            p5   1.46      p50  11.50      p90  38.95
            p10  2.79      p75  20.70      p99  85.74

        `min_sma_gap_pct` sits at roughly the 10th percentile. The floor exists
        to reject a fast average sitting a hair above a slow one, and 2.8 is a
        hair where the 25th percentile at 6.4 would have been throwing away
        real trends. `sma_gap_strong_pct` sits at the 90th, so about one
        qualifying bar in ten earns a full 1.0. Both percentile choices are
        conventions, not findings.

        The two previous values, 2.0 and 20.0, were guesses made before any
        data was available. The measurement says 2.0 sat near the 7th
        percentile and barely filtered anything, while 20.0 sat near the 74th,
        so a quarter of all qualifying bars were scoring maximum strength.

        KNOWN LIMITATION, and it is a real one. With a 180-period slow average
        the gap is driven mostly by how volatile the stock is, not by how good
        its trend is. A high-beta name shows a wider 9-against-180 gap than an
        index fund in every regime, so a single absolute percentage applied
        across all tickers scores volatility and calls it trend strength. See
        `gap_scoring` for the alternative.
    gap_scoring:
        How the trend score is computed once a ticker has cleared the floor.

        "absolute" divides the gap by `sma_gap_strong_pct`. Simple, comparable
        across tickers, and biased towards volatile names for the reason set
        out above.

        "relative" scores today's gap as its percentile rank within that
        ticker's own history of qualifying gaps. A 12% gap on an index fund is
        then remarkable and a 12% gap on a crypto miner is a Tuesday, which is
        closer to what "the wider the gap, the stronger the move" was actually
        getting at. It costs more history and it cannot say a stock is in a
        strong trend when it has never had one, only that this is strong for
        that stock.

        Neither is known to pick better trades. Both exist so the backtest can
        run the same screens twice and answer that with evidence.
    gap_relative_lookback:
        Sessions of gap readings that relative scoring wants behind it. Only
        affects `required_history` when relative scoring is on.
    gap_relative_min_samples:
        Below this many qualifying readings a percentile is noise pretending to
        be a measurement, so relative scoring falls back to absolute and says
        so in the reasons rather than quietly returning a made-up number.
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
        is not. The breakout screen reuses this as its "broke out in the last
        few sessions" window, so there is one dial for "recent" rather than two.
    breakout_volume_spike_min, breakout_volume_spike_strong:
        The breaking bar's volume, as a multiple of the average volume in the
        sessions before it, must clear `breakout_volume_spike_min` to count as a
        spike at all. The volume component of the score ramps from 0 at that
        floor to 1.0 at `breakout_volume_spike_strong`.
    breakout_ignition_min_body_pct:
        The igniting bar's body, as a percentage of its own close, must clear
        this floor. The rulebook says the igniting bar "must be big", which is
        an absolute claim, not just "bigger than a small baby bar".
    breakout_ignition_strong_ratio:
        The igniting bar's body divided by the baby bar's body must exceed 1.0
        to pass at all (the rulebook's "bigger than the baby bar before it").
        The ignition component of the score ramps from 0 at a ratio of 1.0 to
        1.0 at this ratio.
    breakout_baby_max_wick_pct:
        The baby bar's wick, as a percentage of its own high-low range, above
        which the rulebook's "massive wicks disqualify it" rejects the setup
        outright.
    breakout_dip_tolerance_pct:
        How close a post-breakout pullback's low must get to the broken level,
        as a percentage of the level's price, to count as "the dip" in the
        dip-and-reject bonus pattern.
    breakout_dip_reject_bonus:
        Flat addition to the score when the dip-and-reject pattern confirms
        (a pullback to the level followed by a close back above it). Additive
        rather than another weighted term, because the rulebook treats this as
        a bonus on top of a setup that already qualifies, not a fourth thing
        that setup must be good at.
    w_breakout_volume, w_breakout_ignition, w_breakout_recency:
        Weights for the three continuous readings that make up the breakout
        score before the dip-and-reject bonus: how strong the volume spike is,
        how strong the ignition bar is, and how fresh the broken level is.
        Deliberately equal. There is no backtest evidence yet that any one of
        these three matters more than the others for picking winners; the
        Session 4 backtest is what earns the right to move them apart, not a
        guess made while writing the screen.
    """

    sma_fast: int = 9
    sma_slow: int = 180
    min_price: float = 15.0
    min_avg_volume: float = 100_000
    min_beta: float = 2.0
    beta_window: int = 252
    beta_benchmark: str = "SPY"
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    min_float: float = 20_000_000
    avg_volume_window: int = 20
    min_history_days: int = 200
    min_sma_gap_pct: float = 2.8
    sma_gap_strong_pct: float = 39.0
    gap_scoring: str = "absolute"
    gap_relative_lookback: int = 500
    gap_relative_min_samples: int = 40
    level_swing_lookback: int = 5
    level_tolerance_pct: float = 1.0
    level_min_touches: int = 3
    level_lookback_days: int = 252
    level_fresh_days: int = 21
    level_break_lookback: int = 5
    breakout_volume_spike_min: float = 1.5
    breakout_volume_spike_strong: float = 3.0
    breakout_ignition_min_body_pct: float = 1.5
    breakout_ignition_strong_ratio: float = 3.0
    breakout_baby_max_wick_pct: float = 60.0
    breakout_dip_tolerance_pct: float = 1.5
    breakout_dip_reject_bonus: float = 0.3
    w_breakout_volume: float = 1 / 3
    w_breakout_ignition: float = 1 / 3
    w_breakout_recency: float = 1 / 3

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
        if self.breakout_volume_spike_min <= 1.0:
            raise ValueError("breakout_volume_spike_min must be above 1.0, or it is not a spike")
        if self.breakout_volume_spike_strong <= self.breakout_volume_spike_min:
            raise ValueError("breakout_volume_spike_strong must exceed breakout_volume_spike_min")
        if self.breakout_ignition_strong_ratio <= 1.0:
            raise ValueError("breakout_ignition_strong_ratio must be above 1.0")
        if not 0 < self.breakout_baby_max_wick_pct <= 100:
            raise ValueError("breakout_baby_max_wick_pct must be between 0 and 100")
        if self.breakout_dip_tolerance_pct <= 0:
            raise ValueError("breakout_dip_tolerance_pct must be positive")
        if self.min_price < 0:
            raise ValueError("min_price cannot be negative")
        if self.min_beta < 0:
            raise ValueError("min_beta cannot be negative")
        if self.beta_window < 2:
            raise ValueError("beta_window must be at least 2, one return has no variance")
        if self.rsi_period < 2:
            raise ValueError("rsi_period must be at least 2")
        if not 0 < self.rsi_oversold < self.rsi_overbought < 100:
            raise ValueError("need 0 < rsi_oversold < rsi_overbought < 100")
        if self.gap_scoring not in {"absolute", "relative"}:
            raise ValueError(
                f"gap_scoring must be 'absolute' or 'relative', got {self.gap_scoring!r}"
            )
        if self.gap_relative_min_samples < 2:
            raise ValueError("gap_relative_min_samples must be at least 2")

    @property
    def required_history(self) -> int:
        """Sessions to fetch so every indicator is actually defined at the last bar.

        One place to answer "how much data do I need", because the answer moved
        the moment the slow SMA went from 20 to 180 and there were two separate
        callers each guessing at it. The slow SMA needs `sma_slow` bars before it
        returns a number at all, level detection looks back `level_lookback_days`,
        and beta needs `beta_window` returns. Take the largest, then add a month
        of slack for holidays and for the swing-point window, which cannot find a
        pivot in the last few bars.
        """
        needed = [
            self.min_history_days,
            self.sma_slow,
            self.level_lookback_days,
            self.beta_window,
        ]
        if self.gap_scoring == "relative":
            # The gap does not exist until the slow average does, so a run of
            # readings costs `sma_slow` bars before the first one arrives.
            needed.append(self.sma_slow + self.gap_relative_lookback)
        return max(needed) + 21


DEFAULT_CONFIG = Config()
