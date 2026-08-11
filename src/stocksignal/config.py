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

        MEASURED 2026-08-10 by `scripts/calibrate.py`, over 89,859 qualifying
        bars across the 256-ticker screened watchlist and roughly six years of
        history. Qualifying means the bars the trend screen would actually be
        scoring: fast above slow, close above both. Measuring across all bars
        instead would describe a population these numbers are never applied to.

            p5   1.74      p50  21.16      p90  67.92
            p10  3.61      p75  40.16      p99 170.17

        `min_sma_gap_pct` sits at roughly the 10th percentile. The floor exists
        to reject a fast average sitting a hair above a slow one, and 3.6 is a
        hair where the 25th percentile at 9.8 would have been throwing away
        real trends. `sma_gap_strong_pct` sits at the 90th, so about one
        qualifying bar in ten earns a full 1.0. Both percentile choices are
        conventions, not findings.

        CALIBRATION IS UNIVERSE-SPECIFIC, WHICH IS THE REAL LESSON HERE. The
        first measurement was taken against the old 19-ticker watchlist of index
        funds and megacaps and produced 2.8 and 39.0. Screening the whole market
        for beta above 2 replaced that with 256 names selected precisely for
        moving harder than the market, and the same percentiles moved to 3.6 and
        67.9. Nothing about the strategy changed; only the population did. Under
        the old ceiling a large share of the new universe pinned at maximum
        strength and the score stopped ranking anything.

        So these two numbers go stale every time the watchlist is rebuilt, and
        rebuilding is meant to be monthly. Rerun `scripts/calibrate.py` whenever
        `build_watchlist.py` runs, or use `gap_scoring="relative"`, which ranks
        each reading against the ticker's own history and therefore does not
        care what else is in the universe.

        Values before any data existed at all were 2.0 and 20.0, both guesses.

        KNOWN LIMITATION, and it is a real one. With a 180-period slow average
        the gap is driven mostly by how volatile the stock is, not by how good
        its trend is. A high-beta name shows a wider 9-against-180 gap than an
        index fund in every regime, so a single absolute percentage applied
        across all tickers scores volatility and calls it trend strength. See
        `gap_scoring` for the alternative.
    max_entry_rsi:
        Gate 3 of the entry checklist, page 115: "Is this a good deal?" Below
        fair value on RSI is an okay deal, oversold is a good deal. Set this and
        no entry is taken unless RSI is at or under it. None means the gate is
        off, which is how every backtest so far has run.

        This is the gate that makes the strategy directionally different rather
        than merely stricter. Everything else in the rulebook buys strength:
        above both averages, breaking a level, an ignition bar. RSI oversold
        inside an uptrend buys WEAKNESS INSIDE STRENGTH, which is what pages 75
        and 76 mean by taking the pushback rather than the breakout candle. The
        first backtest measured strength alone and found no edge over a random
        pick. That is not evidence about this, because in one important respect
        this is the opposite trade.

        Two values worth testing and no more, because every extra variant spends
        significance: `rsi_oversold` for the course's "good deal", or 50 for
        "below fair value".
    min_reward_risk:
        Gate 1 of the entry checklist, page 115, and the last gate to be
        measured: "more upward potential than downward". The distance to the
        next resistance divided by the distance to the next support, both from
        today's close, both from swing points confirmed on or before today. Set
        it and no entry is taken unless that ratio clears it. None means the
        gate is off.

        1.0 is the rulebook read literally: more room up than down. 2.0 is the
        conventional two-to-one a risk manager would ask for and is stricter
        than anything the course actually says, so it is a separate claim rather
        than a tightening of the same one.

        WHY THIS GATE IS DIFFERENT FROM THE OTHERS, and why it was worth
        building a causal level engine for. Every screen measured so far asks
        about the stock: is it trending, is it strong, is it oversold. This one
        asks about the TRADE: given where price sits between the last place it
        turned down and the last place it turned up, is the payoff shaped in
        your favour. A screen can be right about direction and still lose money
        by buying with two percent of room above and eight below. Nothing tested
        before this could see that distinction at all.

        The honest caveat: the course frames gate 1 alongside a hard stop placed
        at a previous support level. This gate tests only the entry half. A
        backtest with no stop holds every position for the full horizon, so it
        measures whether the ratio predicts returns, not whether the ratio plus
        the stop makes money. Those are different questions and only the first
        one is answered here.
    exit_rule:
        What ends a position, and it is the half of the strategy the first
        fifteen backtests left out entirely.

        "hold" sells at the close `horizon` sessions after entry, come what may.
        Simple, and it is what every result before this one measured. It is also
        not a strategy anybody trades: it lets a position run to minus fifty-
        eight percent without flinching, which is exactly what happened.

        "stops" is section 4 of the rulebook. A hard stop sits at the previous
        support level, chosen before entry so it cannot be argued away, and once
        the target is reached a trailing stop follows price up at `trail_pct`.
        This changes what a loser COSTS rather than which trades get taken, so
        it is a genuinely different question from the four entry gates and not
        another variant of them.
    exit_requires_levels:
        Under "stops", take a trade only when BOTH a stop below and a target
        above actually exist. On by default, and the reason is a trap that was
        very nearly reported as a discovery.

        The first version let a trade run with whatever levels happened to be
        there. A trend screen picks names near their highs, so those names
        frequently have NO resistance above them: no target, therefore the
        trailing stop never arms, therefore their winners run uncapped. They
        also more often have a swing low close beneath, so they more often get
        a protective stop at all. Measured on the synthetic feed, which contains
        no predictive signal by construction: screened picks had a target 69.1%
        of the time against the universe's 78.0%, and a stop 84.0% against
        74.1%. Both asymmetries pay the screens, neither is skill, and together
        they put the screens at the 96th percentile against controls on data
        where there was nothing whatsoever to find.

        That is not a bug in the exit engine. It is a bug in the COMPARISON: the
        control was being handicapped by a rule the screens escaped. Requiring
        both levels in both arms makes the geometry identical and the only
        remaining difference the choice of names, which is the thing under test.

        Turning it off measures something real but different — what the rules
        would actually do in live trading, uncapped highs included. Just do not
        read the percentile from that run as evidence about stock selection.
    trail_pct:
        How far the trailing stop sits below the highest high since the target
        was reached. 5% is the rulebook's number, page 234. It applies only
        after the target is hit; before that the hard stop at support is what
        protects the position, because a trailing stop from entry would be shaken
        out by ordinary noise in a name chosen for having a beta above 2.
    rsi_lookback:
        How many sessions back the RSI gate is allowed to look for its reading.

        THIS EXISTS BECAUSE THE FIRST VERSION WAS WRONG. It required the RSI
        condition on the signal bar itself, which produced exactly zero trades
        across six years at a threshold of 30, and that is not a fact about the
        market. A bar crossing up through the 9-day average is by definition
        showing strength, so its RSI sits around 50 to 70. Oversold describes
        the opposite kind of bar. Demanding both at once asks for a candle that
        cannot exist.

        The course never meant them simultaneously. Pages 75 and 76 describe a
        SEQUENCE: the pushback takes it oversold, then it turns and holds, and
        the turn is the entry. So the gate now asks whether RSI dipped to or
        below the ceiling at any point in the last `rsi_lookback` sessions, with
        confirmation as the trigger. Weakness recently, strength today.
    trend_entry:
        What counts as a trend signal, and it is the difference between two
        strategies rather than a tuning knob.

        "state" fires on every session price is above both averages with the
        fast above the slow. That is what the scaffold shipped, and it means a
        name in a three-month uptrend signals sixty times.

        "confirmation" fires only on the session the condition first becomes
        true, which is the course's actual rule: page 116 defines CONFIRMATION
        as "the first candlestick holding (OPENING) above the blue SMA line".

        NOTE THE WORD IN BRACKETS, which this project dropped from the quote and
        from the code. The course names the OPEN as the thing that has to hold
        above the line; every implementation here tests the CLOSE. That is a
        real difference on every confirmation signal, it was never a considered
        decision, and it is not fixed yet. One signal per move rather than one
        per day is right; which price defines the signal is not.

        The first out-of-sample backtest measured "state" and found no edge over
        a random pick from the same universe. That is a result about the state
        version only. 1,658 trades from a screen that fires daily is largely the
        same moves counted again and again, which is precisely how a real effect
        gets buried inside its own noise. "confirmation" is what the rulebook
        says and what has never been measured.
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
    level_source:
        What counts as a level for gate 1 and for stop placement.

        "touches" applies the rulebook's three-confirmation rule: swing points
        are clustered and only a cluster with `level_min_touches` members counts.
        This is the course's definition and the default.

        "swings" uses raw single swing points. That is what shipped first, and a
        fidelity audit against the course found it was a silent departure rather
        than an interpretation: a one-touch swing low is not "a previous support
        level" in the sense page 234 means. It also had teeth. Single swing
        points sit far closer to price, so stops measured about 3.2% wide on a
        universe of beta-2 names, which is inside ordinary daily noise, and the
        hit rate collapsed to 22%. The setting is kept only so the two can be
        compared directly.
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
        to pass at all. The words "bigger than the baby bar BEFORE IT" were
        quoted here from the rulebook and the rulebook does not contain them:
        "before it" was added, and it inverts the course's 3-bar setup, where
        the baby bar is the small bar that TESTS the ignition bar afterwards.
        See the note at the top of `screens/breakout.py`.
        The ignition component of the score ramps from 0 at a ratio of 1.0 to
        1.0 at this ratio.
    breakout_baby_max_wick_pct:
        The baby bar's wick, as a percentage of its own high-low range, above
        which the rulebook's "massive wicks disqualify it" rejects the setup
        outright.
    breakout_dip_tolerance_pct:
        How close the post-breakout pullback's low must get to the broken level,
        as a percentage of the level's price, to count as a genuine retest.
    breakout_require_retest:
        Whether the retest is a GATE. It is, and making it one was the single
        largest correction this screen has had.

        The first version scored it as a small bonus and justified that with a
        quote attributed to the rulebook saying the pattern "does not always
        appear". No source contains that sentence. What page 75 actually says is
        "if you want to trade a quality breakout, WAIT UNTIL A PUSH BACK and
        start showing price strength again", and page 76 closes the section with
        "when there is change of direction we usually test it... This
        reassurance is key". The chapter's own takeaway box lists exactly two
        things, and both of them are the retest.

        So the course's edge is not in the breakout candle. It is in what
        happens afterwards, and a screen that fires on the candle and treats
        the retest as a garnish has inverted the source. A breakout with no
        pullback yet is not a failed setup, it is an unfinished one, and the
        rejection reason says so.
    breakout_retest_window:
        How many sessions after the break to keep looking for the pullback
        before giving up on it. Not a course number. Long enough for a real
        pullback to develop, short enough that a test three months later is not
        credited to a breakout everyone has forgotten.
    breakout_overbought_penalty:
        Subtracted from the score when RSI is at or above the overbought line on
        the signal bar. A PENALTY rather than a gate, because that is exactly
        how pages 72 to 74 frame it: an extreme entry is a "deprecating factor"
        on an otherwise good breakout, not a disqualification. The course's own
        example takes a breakout that was near overbought and calls it "not so
        much quality... but still better than the first one".
    w_breakout_volume, w_breakout_three_bar, w_breakout_recency:
        Weights for the three ELEVATING FACTORS that make up the breakout score:
        how strong the volume spike is, whether the 3-bar setup is present and
        how clean it is, and how fresh the broken level is.

        Elevating is the right word and it is the course's. Page 79 says of the
        3-bar setup: "this doesn't mean that whenever you see a 3-bar setup it
        will run, this is just another elevating factor in our favor". The first
        version made the ignition bar and its wick HARD GATES, which is stricter
        than the course anywhere is, and which rejected quality breakouts for
        failing a test the source never sets.
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
    min_sma_gap_pct: float = 3.6
    sma_gap_strong_pct: float = 67.9
    trend_entry: str = "state"
    max_entry_rsi: float | None = None
    min_reward_risk: float | None = None
    exit_rule: str = "hold"
    trail_pct: float = 5.0
    exit_requires_levels: bool = True
    rsi_lookback: int = 10
    gap_scoring: str = "absolute"
    gap_relative_lookback: int = 500
    gap_relative_min_samples: int = 40
    level_swing_lookback: int = 5
    level_source: str = "touches"
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
    breakout_require_retest: bool = True
    breakout_retest_window: int = 15
    breakout_overbought_penalty: float = 0.25
    w_breakout_volume: float = 1 / 3
    w_breakout_three_bar: float = 1 / 3
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
        if self.min_reward_risk is not None and self.min_reward_risk <= 0:
            raise ValueError("min_reward_risk must be positive, or None to disable gate 1")
        if self.level_source not in ("touches", "swings"):
            raise ValueError(
                f"level_source must be 'touches' or 'swings', got {self.level_source!r}"
            )
        if self.exit_rule not in ("hold", "stops"):
            raise ValueError(f"exit_rule must be 'hold' or 'stops', got {self.exit_rule!r}")
        if not 0 < self.trail_pct < 100:
            raise ValueError("trail_pct must be between 0 and 100")
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
        if self.max_entry_rsi is not None and not 0 < self.max_entry_rsi < 100:
            raise ValueError("max_entry_rsi must sit between 0 and 100, or be None")
        if self.trend_entry not in {"state", "confirmation"}:
            raise ValueError(
                f"trend_entry must be 'state' or 'confirmation', got {self.trend_entry!r}"
            )
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
