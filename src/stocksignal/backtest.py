"""Walk-forward backtest. The session that decides whether any of this is worth running.

The honesty gate from the project overview: if the screens do not beat a tracker
after costs, the correct outcome is to buy the tracker and keep this as a monitor
on positions already held. That deal is not renegotiated because a number came
back disappointing.

HOW LOOKAHEAD IS PREVENTED, which is the whole design rather than a feature of it.

1.  The simulated day. The scanner sees bars up to and including T's close,
    because that is when you would really run it, and trades at the T+1 OPEN.
    Measuring from the T close measures a fill nobody can get: breakouts gap
    overnight, so close-to-close looks excellent and is unreachable.

2.  `swing_points` looks forward by construction. It uses a centred rolling
    window, so a swing high at bar i is confirmed by bars i+1 to i+lookback.
    Truncating the frame at T handles this automatically, because the centred
    window returns nothing for the final bars. That is why truncation is the
    ONLY mechanism here: nothing in this module is ever handed a full frame plus
    a date, so no future bar is reachable even by mistake.

3.  Split and dividend adjustment. Both providers back-adjust using corporate
    actions known today, so a stock that traded at 5 dollars in 2021 and later
    split appears in the adjusted series at 50. The `min_price` gate would pass
    a stock you could never have bought. `price_is_adjusted` records that this
    is unfixable with the data to hand, and the report says so out loud rather
    than quietly carrying the bias.

4.  The watchlist. `data/watchlist.txt` was screened on beta as of today, so
    using it would pick 2020's stocks with 2026's knowledge. This module never
    reads it. The universe is rebuilt at every simulated session from bars dated
    T or earlier.

5.  Your own thresholds. The gap floor and ceiling were measured across all six
    years, including whatever period gets reported. `fit_end` splits the run: it
    is the last date any calibration was allowed to see, and results before it
    are marked in-sample and should not be quoted.

6.  Survivorship. Not preventable with free data: the symbol directory lists
    what exists now, so companies that went bankrupt or delisted are absent, and
    they skew towards losers. The mitigation is the RANDOM arm below, which
    carries the identical bias, so the difference between it and the screens
    measures the screens rather than the universe.

THE THREE ARMS, and why SPY alone is not enough. SPY has no survivorship bias
and the screened universe does, so any outperformance against it is partly just
that gap. The random arm buys a randomly chosen name from the same reconstituted
universe on the same dates. If the screens cannot beat a coin toss inside their
own universe, they are not screens, they are a stock list.

WHY THE RANDOM ARM IS DRAWN THE WAY IT IS, which took an outside review to get
right. The first version drew a flat three names per signal date while the
screens arm recorded however many names fired that day. Those are averages over
two different date weightings, and the difference is not neutral: signal breadth
in a momentum screen peaks when the whole market is extended, so the screens arm
was loaded onto frothy dates and the control was not. A worked example, with
identical pick quality in both arms: one early-recovery date with 1 signal and a
+4% universe, one late-cycle date with 30 signals and a -3% universe. Screens
average (1*4 + 30*-3)/31 = -2.8%. Control averages (3*4 + 3*-3)/6 = +0.5%. The
control "wins" by four points having done nothing at all. So the control now
draws exactly as many names per date as the screens took on that date. Only the
choice of names differs, which is the only thing being tested.

WHAT THE PERCENTILE DOES NOT MEASURE, which belongs next to the claim rather
than in a footnote. Because the control takes the same number of names on the
same dates, every control inherits whatever the screens knew about WHEN to
trade. Date selection is held fixed by construction, so a strategy whose edge
was timing or breadth would score 50 here no matter how good it was. The
question this answers is narrower and should be stated as it is: given these
dates, are these names better than other names from the same universe. For a
cross-sectional screen that is the advertised mechanism, so it is the right
question. It is not the same as "the rules do not work".

WHY ONE CONTROL IS NOT ENOUGH. A single seeded draw is one roll of the dice
printed as though it were a measurement. Reported next to it and quoted to two
decimals, it invites a conclusion it cannot support, and at small trade counts
the ordering of the two arms flips with the seed. `null_distribution` therefore
runs the control many times and reports where the screens' mean falls inside
that spread. That percentile is the result. The single random row remains in the
table because it is legible, but it is an illustration, not evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from stocksignal.breakout_path import breakout_signals
from stocksignal.config import Config
from stocksignal.indicators import rsi, sma
from stocksignal.levels import nearest_levels

log = logging.getLogger(__name__)

HORIZONS = (5, 10, 20)
DEFAULT_COST_PCT = 0.2  # Round trip, in percent. Stated in every report.
REPLICATES = 200  # Independent random controls behind the percentile.
TRIM_PCT = 5.0  # Share of best trades removed for the robustness statistic.
STATS = ("mean", "median", "trimmed")

# How many percentile tests this project has already run against this data.
# Every variant tried costs significance whether or not it is reported, and the
# count only goes up, so it lives here where forgetting to raise it is visible.
#   state; confirmation; confirmation+RSI30; confirmation+RSI50; gate 1 at 1:1;
#   gate 1 at 2:1; confirmation+stops; gate 1 at 2:1 + stops; breakout. Nine
#   configurations, three horizons each. Shuffled runs are controls rather than
#   hypotheses and are deliberately not counted.
#
# The breakout entry was added on 11 August 2026 and raised this from 24 to 27
# BEFORE its first run, not after. That ordering is the only thing that makes
# the number mean anything: a family size chosen once the result is known is not
# a correction, it is a negotiation.
#
# Bonferroni assumes these are independent and they are emphatically not: the
# variants nest inside one another and the three horizons are the same trades
# measured at three lengths. An independent review put the effective count near
# 9. The number is left at the blunt end deliberately, but see `power` below,
# because a bar this high on this much data is not a strict standard, it is an
# unreachable one, and that is a different failure.
TESTS_RUN = 27
ALPHA = 0.05  # The bar before correction: beat 95% of controls.


@dataclass(frozen=True)
class Trade:
    """One simulated position, entered at the open after the signal."""

    arm: str
    ticker: str
    signal_date: date
    entry_date: date
    entry_price: float
    score: float
    returns: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ArmStats:
    """What one arm did, per horizon."""

    name: str
    trades: int
    hit_rate: dict[int, float]
    mean: dict[int, float]
    median: dict[int, float]
    worst: dict[int, float]


@dataclass(frozen=True)
class NullTest:
    """Where the screens' mean sits inside a distribution of random controls.

    This is the only part of the report that answers "could this be luck?".
    Every control draws the same number of names on the same dates as the
    screens did, so the sole difference between a control and the screens is
    which names got picked. `beats_pct` is the share of controls the screens
    beat, which is a permutation test spelled out in plain words: 50 means the
    screens are a coin toss, 95 or better is the conventional bar, and anything
    between is a result you do not have yet.

    THREE STATISTICS, not one, because a mean on its own hides the shape.

    `mean` is the headline. `median` is the typical trade. A mean that passes
    while the median fails is not a mildly weaker result, it is a different
    result: it says the screens' average trade is worse than a random one and
    the average is being carried by a handful of enormous winners. `trimmed`
    removes the best 5% of trades from every arm and asks the question again.
    Genuine positive skew — the real signature of trend following — degrades
    gracefully under that. A few lucky names collapse to a coin toss.

    Controls are trimmed by the same rule, so the comparison stays fair: the
    question is whether the SCREENS' tail is unusual, not whether tails exist.

    THE MEDIAN IS NOT SAFE TO READ UNDER STOPS, and this was learned the hard
    way, twice. With a hard stop the return distribution develops a dense lump
    just below zero where the stopped-out trades pile up, and the median sits
    inside that lump. A small shift in how often an arm gets stopped therefore
    moves the median a long way, and trend-screened names are stopped slightly
    less often for reasons that have nothing to do with prediction: their swing
    low sits marginally further below, 6.13% against the universe's 5.88%.
    Measured on the synthetic feed, which contains no signal at all, the median
    still beat 99% and 100% of controls at 5 and 10 sessions. The real data
    produced the same shape and it would have read exactly like a discovery.

    So under "stops" the median row is printed with a warning and the verdict
    ignores it. The mean is the statistic that decides, because the mean is what
    an account balance actually compounds.
    """

    replicates: int
    period: str
    screen_trades: int
    distinct_tickers: int
    family_size: int
    exit_rule: str
    # Keyed [horizon][statistic] where statistic is one of STATS.
    screens: dict[int, dict[str, float]]
    random_median: dict[int, dict[str, float]]
    random_p05: dict[int, dict[str, float]]
    random_p95: dict[int, dict[str, float]]
    beats_pct: dict[int, dict[str, float]]
    # Percentage points of the mean supplied by the best 5% of trades.
    tail_lift: dict[int, float]

    @property
    def corrected_bar(self) -> float:
        """The percentile a result must clear given how many tests were run.

        Bonferroni, which is the blunt correction and the right one here because
        the alternatives assume independence these tests do not have: the same
        universe, the same dates, overlapping horizons. Blunt and honest beats
        precise and wrong.
        """
        return 100.0 * (1.0 - ALPHA / max(self.family_size, 1))

    #: Expected exceedances required before a decision AT the bar is meaningful.
    #: One is merely enough for the percentile grid to contain the bar, which is
    #: expressibility rather than resolution; the first version asked for one and
    #: would have called a decision on a single lucky draw.
    MIN_EXCEEDANCES = 10

    def detectable_effect(self, horizon: int, stat: str = "mean") -> float:
        """The effect this run needed before the bar was reachable, per trade.

        Precisely: the critical value, which is the effect that clears the bar
        about HALF the time. Calling it "the smallest edge this run could have
        certified" was too generous by roughly a third — an effect certified
        reliably, at the usual 80%, has to be about 1.3 times this number,
        because the screens' own mean is noisy with much the same spread.

        THIS IS THE NUMBER THAT WAS MISSING, and leaving it out was the worst
        methodological error in the project. A bar was set at 99.7%, results
        were measured against it, and failing it was reported as a finding —
        without anyone first asking whether the data could clear that bar at all.

        It could not. Working from the observed spread of the control
        distribution, the declared bar demands roughly 1.9 points per 20-day
        trade, which annualises to something like 25-30% of pure selection
        alpha. Essentially nothing legitimate clears that. Against the effect
        actually measured, the design had about one chance in six of returning
        a pass. A test that says "no" five times out of six when the answer is
        yes has not found evidence of absence; it has failed to be an
        experiment.

        Reported next to every result from now on, so the reader can see what
        the run was capable of noticing before reading what it noticed.
        """
        spread = self.random_p95[horizon][stat] - self.random_p05[horizon][stat]
        if not np.isfinite(spread) or spread <= 0:
            return float("nan")
        sigma = spread / 3.29  # p95 - p05 spans 3.29 standard deviations.
        z = _z_for(self.corrected_bar)
        return float(z * sigma)

    @property
    def resolvable(self) -> bool:
        """Are there enough controls to decide AT the bar, not merely to print it?

        With 200 replicates the finest percentile step is 0.5, so a bar of 99.67
        cannot be told apart from 100. Ten expected exceedances puts the Monte
        Carlo standard error well inside the distance being judged. Saying the
        run cannot answer is better than printing a number that looks decisive
        and is an artefact of how many times the dice were rolled.
        """
        expected = self.replicates * (100.0 - self.corrected_bar) / 100.0
        return expected >= self.MIN_EXCEEDANCES


@dataclass(frozen=True)
class BacktestReport:
    start: date
    end: date
    fit_end: date | None
    cost_pct: float
    sessions: int
    universe_days: float
    arms: tuple[ArmStats, ...]
    arms_in_sample: tuple[ArmStats, ...] = ()
    arms_out_of_sample: tuple[ArmStats, ...] = ()
    trades: tuple[Trade, ...] = ()
    price_is_adjusted: bool = True
    null_test: NullTest | None = None

    @property
    def in_sample_note(self) -> str:
        if self.fit_end is None:
            return "NO HOLD-OUT. Every threshold was measured on this same period."
        return (
            f"Thresholds were calibrated on data up to {self.fit_end}. Quote only results after it."
        )


def precompute(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Per-bar indicator series, computed once per ticker for the whole history.

    Calling the screens once per ticker per simulated session would mean
    recomputing a 180-period average on a sliced frame roughly four hundred
    thousand times. These are the same numbers `sma` and `pct_gap` produce, laid
    out per bar, and `tests/test_backtest.py` asserts they agree with
    `screen_trend` on sampled dates so this cannot drift away from the screen it
    is standing in for.

    Nothing here peeks: every series is causal, computed from bars at or before
    each row.
    """
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"]
    out["open"] = df["open"]
    # High and low are only needed once exits are simulated: a stop is hit
    # intrabar, and a close-only series cannot see that.
    out["high"] = df["high"]
    out["low"] = df["low"]
    out["fast"] = sma(df["close"], cfg.sma_fast)
    out["slow"] = sma(df["close"], cfg.sma_slow)
    out["gap"] = (out["fast"] - out["slow"]) / out["slow"] * 100.0
    out["avg_volume"] = df["volume"].rolling(cfg.avg_volume_window, min_periods=1).mean()
    reading = rsi(df["close"], cfg.rsi_period)
    out["rsi"] = reading
    # Gate 1's raw material. Causal by explicit shift rather than by truncation,
    # because this caller wants an answer at every bar. See `nearest_levels`.
    levels = nearest_levels(df, cfg)
    out["reward_risk"] = levels["reward_risk"]
    # The prices themselves, not just the ratio: the stop goes AT the support
    # and the target AT the resistance, so both need to survive as levels.
    out["support"] = levels["support"]
    out["resistance"] = levels["resistance"]
    # The lowest RSI in the recent window, which is what the gate tests: was
    # this thing sold off lately, not is it sold off right now.
    out["rsi_low"] = reading.rolling(cfg.rsi_lookback, min_periods=1).min()
    return out


def rolling_beta(closes: pd.Series, benchmark: pd.Series, window: int) -> pd.Series:
    """Beta at every bar, using only that bar's trailing window.

    Vectorised for the same reason as `precompute`, and causal for a better one:
    a single beta computed from the whole history would be the exact selection
    lookahead this module exists to avoid.
    """
    paired = pd.concat([closes.rename("a"), benchmark.rename("b")], axis=1, join="inner")
    returns = paired.pct_change()
    covariance = returns["a"].rolling(window).cov(returns["b"])
    variance = returns["b"].rolling(window).var()
    beta = covariance / variance.replace(0.0, np.nan)
    return beta.reindex(closes.index)


@dataclass(frozen=True)
class Panel:
    """Every ticker's history reindexed onto one calendar, as plain arrays.

    A backtest that slices a DataFrame per ticker per session recomputes a
    180-period average roughly four hundred thousand times, which takes hours.
    Aligning once and working in numpy turns the entire universe-and-trend pass
    into a handful of 2-D boolean operations.

    It is also safer, not just faster. Every array here is causal by
    construction, so there is no date parameter anywhere for a future bar to
    leak through. Missing bars stay NaN and are never forward filled: an invented
    price is worse than an excluded trade.
    """

    dates: pd.DatetimeIndex
    tickers: tuple[str, ...]
    open: np.ndarray
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    fast: np.ndarray
    slow: np.ndarray
    gap: np.ndarray
    avg_volume: np.ndarray
    rsi: np.ndarray
    rsi_low: np.ndarray
    reward_risk: np.ndarray
    support: np.ndarray
    resistance: np.ndarray
    beta: np.ndarray


def build_panel(frames: dict[str, pd.DataFrame], benchmark: pd.DataFrame, cfg: Config) -> Panel:
    """Align every ticker onto the benchmark's trading calendar."""
    calendar = benchmark.index
    tickers = tuple(sorted(frames))
    fields = (
        "open",
        "close",
        "high",
        "low",
        "fast",
        "slow",
        "gap",
        "avg_volume",
        "rsi",
        "rsi_low",
        "reward_risk",
        "support",
        "resistance",
        "beta",
    )
    columns = {name: [] for name in fields}

    for ticker in tickers:
        df = frames[ticker]
        series = precompute(df, cfg).reindex(calendar)
        beta = rolling_beta(df["close"], benchmark["close"], cfg.beta_window).reindex(calendar)
        for name in fields[:-1]:
            columns[name].append(series[name].to_numpy(dtype=float))
        columns["beta"].append(beta.to_numpy(dtype=float))

    stacked = {name: np.column_stack(values) for name, values in columns.items()}
    return Panel(dates=calendar, tickers=tickers, **stacked)


def universe_mask(panel: Panel, cfg: Config) -> np.ndarray:
    """The course's page 142 scan filter at every bar, from that bar's own data."""
    with np.errstate(invalid="ignore"):
        return (
            (panel.close >= cfg.min_price)
            & (panel.avg_volume >= cfg.min_avg_volume)
            & (panel.beta >= cfg.min_beta)
        )


def trend_mask(
    panel: Panel, cfg: Config, universe: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """The trend screen, vectorised. Mirrors `screens/trend.py` condition for condition.

    `tests/test_backtest.py` asserts this agrees with `screen_trend` itself on
    sampled bars, so the fast path cannot quietly drift away from the screen it
    stands in for. Scored on the absolute ceiling; relative scoring needs each
    ticker's own gap history and belongs in a later pass.

    `universe` matters only under confirmation entry, and it matters a lot. The
    first version intersected the price, volume and beta filter AFTER computing
    the transition, so a ticker whose 252-day beta wobbled under the floor on
    the exact session it confirmed had its transition consumed outside the
    universe and never signalled again for that entire move. Since the candidate
    pool was screened at roughly the beta floor, names sitting near it are the
    rule rather than the exception, and confirmation entry is sparse enough that
    losing a handful of moves moves the answer. Intersect first, then diff.
    """
    with np.errstate(invalid="ignore"):
        passes = (
            (panel.fast > panel.slow)
            & (panel.close > panel.fast)
            & (panel.close > panel.slow)
            & ~((panel.gap > 0) & (panel.gap < cfg.min_sma_gap_pct))
        )
        strength = np.clip(panel.gap / cfg.sma_gap_strong_pct, 0.0, 1.0)
    live = passes & np.isfinite(panel.gap)
    if cfg.max_entry_rsi is not None:
        # Gate 3, as a sequence rather than a coincidence: did RSI dip to the
        # ceiling at any point in the recent window? Weakness lately, strength
        # today. A NaN reading is not a good deal, so it fails rather than passes.
        with np.errstate(invalid="ignore"):
            live = live & np.isfinite(panel.rsi_low) & (panel.rsi_low <= cfg.max_entry_rsi)
    if cfg.min_reward_risk is not None:
        # Gate 1: more room up than down. A bar with no known ceiling above or
        # no known floor below reads NaN, and NaN fails. "I cannot see the
        # downside" is not the same as "there is no downside", and a gate that
        # treats them alike buys exactly the tops it exists to avoid.
        with np.errstate(invalid="ignore"):
            live = (
                live & np.isfinite(panel.reward_risk) & (panel.reward_risk >= cfg.min_reward_risk)
            )
    if universe is not None:
        live = live & universe
    if cfg.trend_entry == "confirmation":
        # The course's rule: the FIRST candle holding above the line, not every
        # candle that happens to be above it. A transition from not-passing to
        # passing, so one signal per move instead of one per session.
        previous = np.vstack([np.zeros((1, live.shape[1]), dtype=bool), live[:-1]])
        live = live & ~previous
    return live, np.where(passes, strength, 0.0)


def breakout_mask(
    frames: dict[str, pd.DataFrame],
    panel: Panel,
    cfg: Config,
    universe: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """The breakout screen at every bar, in the same shape `trend_mask` returns.

    The screen is path-dependent, so there is no vectorised form of it and this
    is a per-ticker sweep rather than a handful of array operations. See
    `breakout_path` for why, and for the equivalence test that keeps it honest.

    EVALUATED ON EACH TICKER'S OWN BARS, then reindexed onto the panel calendar.
    Running it on the calendar-aligned arrays instead would insert NaN rows on
    every session a ticker did not trade, and a screen that counts bars —
    "broken within 5 sessions", "the baby bar after the ignition" — would count
    those holes. The live scanner sees the ticker's own history with no holes in
    it, so the backtest has to as well.
    """
    n_dates, n_tickers = panel.close.shape
    signals = np.zeros((n_dates, n_tickers), dtype=bool)
    strength = np.zeros((n_dates, n_tickers), dtype=float)

    for i, ticker in enumerate(panel.tickers):
        df = frames[ticker]
        passed, score = breakout_signals(df, cfg)
        # Only bars the panel calendar actually contains. A ticker trading on a
        # session the benchmark did not is dropped rather than shifted onto a
        # neighbouring date, which would move a signal to a day it was not known.
        rows = panel.dates.get_indexer(df.index)
        live = rows >= 0
        signals[rows[live], i] = passed[live]
        strength[rows[live], i] = np.nan_to_num(score[live])

    if universe is not None:
        signals = signals & universe
    return signals, strength


def forward_return(
    bars: pd.DataFrame, entry_pos: int, horizon: int, cost_pct: float
) -> float | None:
    """Percent return from the entry open to the close `horizon` sessions later.

    Entry is an OPEN and exit is a close, which is the pair you could actually
    trade: the signal is known after T's close, so the earliest fill is T+1's
    open. Costs are taken once, as a round trip, and stated in the report.

    Returns None when the position runs past the end of the data, so an
    unfinished trade is excluded rather than silently counted as flat.
    """
    exit_pos = entry_pos + horizon
    if exit_pos >= len(bars):
        return None
    entry = float(bars["open"].iloc[entry_pos])
    exit_price = float(bars["close"].iloc[exit_pos])
    if entry <= 0:
        return None
    return (exit_price / entry - 1.0) * 100.0 - cost_pct


def summarise(name: str, trades: list[Trade]) -> ArmStats:
    hit_rate: dict[int, float] = {}
    mean: dict[int, float] = {}
    median: dict[int, float] = {}
    worst: dict[int, float] = {}
    for horizon in HORIZONS:
        values = [t.returns[horizon] for t in trades if horizon in t.returns]
        if not values:
            hit_rate[horizon] = mean[horizon] = median[horizon] = worst[horizon] = float("nan")
            continue
        series = pd.Series(values)
        hit_rate[horizon] = float((series > 0).mean() * 100.0)
        mean[horizon] = float(series.mean())
        median[horizon] = float(series.median())
        worst[horizon] = float(series.min())
    return ArmStats(name, len(trades), hit_rate, mean, median, worst)


def forward_returns(panel: Panel, horizon: int, cost_pct: float) -> np.ndarray:
    """Return matrix for a signal at bar t: buy the t+1 open, sell the t+1+h close.

    Vectorised over the whole panel. Entry is an OPEN and exit is a CLOSE, which
    is the pair you could actually trade, because the signal is only known after
    t's close. NaN wherever the trade would run past the end of the data, so an
    unfinished position is excluded rather than counted as flat.
    """
    n = len(panel.dates)
    entry = np.full_like(panel.open, np.nan)
    exit_ = np.full_like(panel.close, np.nan)
    entry[: n - 1] = panel.open[1:]
    if n - 1 - horizon > 0:
        exit_[: n - 1 - horizon] = panel.close[1 + horizon :]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (exit_ / entry - 1.0) * 100.0 - cost_pct
        out[~np.isfinite(entry) | (entry <= 0)] = np.nan
    return out


def _shift_back(arr: np.ndarray, offset: int) -> np.ndarray:
    """`out[t] = arr[t + offset]`, NaN where that runs off the end."""
    out = np.full_like(arr, np.nan)
    if offset < len(arr):
        out[: len(arr) - offset] = arr[offset:]
    return out


def exit_returns(panel: Panel, horizon: int, cost_pct: float, cfg: Config) -> np.ndarray:
    """Returns under the rulebook's exits, rather than holding blind to the bell.

    Section 4 of the rulebook specifies two things this project spent fifteen
    tests ignoring: a HARD STOP at a previous support level, decided in advance
    "so you cannot talk yourself into holding and hoping", and a 5% TRAILING
    STOP that follows price up once the target is reached. Everything measured
    before this bought at the open and sold `horizon` sessions later come what
    may, which is why a single trade could lose 58% and why every mean was
    hostage to its own tail. Those numbers describe a strategy nobody would
    trade. This function describes the one in the book.

    Stop and target are both read from the SIGNAL bar and never updated from
    later bars, so the trade is fully specified at the moment it is taken. That
    is not only causal, it is the point: a stop chosen after you are in the
    position is the thing the rulebook is warning against.

    FOUR MODELLING DECISIONS, each taken the conservative way, because a fill
    assumption is where a backtest lies to you most comfortably.

    1.  Stop before target within a bar. When a bar's range covers both, daily
        data cannot say which came first. Assuming the stop means the losing
        interpretation always wins, so the result is a floor rather than a
        guess dressed as a measurement.
    2.  A gap through the stop fills at the OPEN, not the stop. If price opens
        below your stop you do not get your stop, you get the open. Filling at
        the stop price would invent liquidity that was never there and would
        quietly cap the left tail at exactly the number that makes the strategy
        look safe.
    3.  The trailing stop arms at the END of the bar that reaches the target and
        is only checked from the NEXT bar. Arming it intrabar would require
        knowing the path within the bar, which daily data does not contain.
    4.  The trail follows the highest HIGH seen since arming, which is the
        ratchet the rulebook describes, and it never moves down. That last
        clause was a lie in the first version: arming simply REPLACED the hard
        stop with `peak * 0.95`, so whenever the target sat less than ~5.26%
        above the stop, reaching it moved the exit level DOWN. Worked example
        from the review that caught it: entry 100, stop 98, target 102. Bar 2
        prints a high of 102, arming a trail at 96.9. A bar-3 low of 97 should
        have exited at the hard stop for -2%; instead the position survived and
        could exit at 96.9 for -3.1%. The exit level is now the HIGHER of the
        two, which is what a ratchet means and what the rulebook says.

    A position that survives all of that exits exactly where it used to: the
    close `horizon` sessions after entry. So with no stop and no target in
    range, this returns what `forward_returns` returns, and a test asserts it.
    """
    entry = _shift_back(panel.open, 1)
    stop = panel.support.copy()
    target = panel.resistance.copy()

    with np.errstate(invalid="ignore"):
        tradeable = np.isfinite(entry) & (entry > 0)
        # A stop at or above the entry is not a stop, it is an instant exit.
        stop = np.where(np.isfinite(stop) & (stop < entry), stop, np.nan)
        target = np.where(np.isfinite(target) & (target > entry), target, np.nan)
        if cfg.exit_requires_levels:
            # Both arms trade the same geometry or the comparison measures the
            # geometry. See `exit_requires_levels` in Config for the numbers
            # that made this necessary.
            tradeable &= np.isfinite(stop) & np.isfinite(target)

    exit_price = np.full_like(entry, np.nan)
    closed = np.zeros(entry.shape, dtype=bool)
    armed = np.zeros(entry.shape, dtype=bool)
    peak = np.full_like(entry, -np.inf)
    trail = 1.0 - cfg.trail_pct / 100.0

    for step in range(horizon + 1):
        offset = 1 + step
        bar_open = _shift_back(panel.open, offset)
        bar_high = _shift_back(panel.high, offset)
        bar_low = _shift_back(panel.low, offset)

        with np.errstate(invalid="ignore"):
            # fmax, not maximum: a NaN hard stop (possible when
            # `exit_requires_levels` is off) must not poison a live trail.
            level = np.where(armed, np.fmax(stop, peak * trail), stop)
            # Decision 1: the stop is tested before the target.
            hit = ~closed & tradeable & np.isfinite(level) & np.isfinite(bar_low)
            hit &= bar_low <= level
            # Decision 2: a gap through it fills at the open, not the level.
            fill = np.where(np.isfinite(bar_open) & (bar_open < level), bar_open, level)
            exit_price = np.where(hit, fill, exit_price)
            closed |= hit

            # Decision 3: arming happens after the stop test, and the trail is
            # not checked until the next iteration.
            reached = ~closed & tradeable & ~armed & np.isfinite(target)
            reached &= np.isfinite(bar_high) & (bar_high >= target)
            armed |= reached
            # Decision 4: ratchet upwards only, from the arming bar onwards.
            peak = np.where(armed & np.isfinite(bar_high), np.maximum(peak, bar_high), peak)

    # Anything still open exits where it always did.
    final_close = _shift_back(panel.close, 1 + horizon)
    exit_price = np.where(closed, exit_price, final_close)

    # Trades whose horizon runs past the end of the data are dropped WHOLE, as
    # a cohort, including the ones that closed early. That looks wasteful and is
    # deliberate: inside that cohort only the trades that exited early are
    # resolvable at all, and "exited early" is an outcome, never a quiet
    # drifter. Keeping them would condition the sample on the path taken. The
    # rule is date-based and outcome-blind, and applies to every arm.
    #
    # A NaN close in the MIDDLE of the history is a different thing entirely,
    # and the first version confused the two: one bad bar in 2021 would discard
    # a trade that had already stopped out seventeen sessions earlier, for no
    # reason at all.
    reached_the_end = np.zeros_like(entry, dtype=bool)
    if len(panel.dates) - 1 - horizon > 0:
        reached_the_end[: len(panel.dates) - 1 - horizon] = True

    with np.errstate(invalid="ignore", divide="ignore"):
        out = (exit_price / entry - 1.0) * 100.0 - cost_pct
        usable = tradeable & reached_the_end & (closed | np.isfinite(final_close))
        out[~usable] = np.nan
    return out


def horizon_returns(panel: Panel, horizon: int, cost_pct: float, cfg: Config) -> np.ndarray:
    """Dispatch to the configured exit rule. One seam, so no caller has to know."""
    if cfg.exit_rule == "stops":
        return exit_returns(panel, horizon, cost_pct, cfg)
    return forward_returns(panel, horizon, cost_pct)


def _record(
    arm: str,
    panel: Panel,
    picks: list[tuple[int, int, float]],
    returns_by_horizon: dict[int, np.ndarray],
) -> list[Trade]:
    trades: list[Trade] = []
    for t, i, score in picks:
        entry = panel.open[t + 1, i] if t + 1 < len(panel.dates) else np.nan
        if not np.isfinite(entry):
            continue
        got = {
            h: float(returns_by_horizon[h][t, i])
            for h in HORIZONS
            if np.isfinite(returns_by_horizon[h][t, i])
        }
        if not got:
            continue
        trades.append(
            Trade(
                arm=arm,
                ticker=panel.tickers[i],
                signal_date=panel.dates[t].date(),
                entry_date=panel.dates[t + 1].date(),
                entry_price=float(entry),
                score=float(score),
                returns=got,
            )
        )
    return trades


def _thin(picks: list[tuple[int, int, float]], min_gap: int) -> list[tuple[int, int, float]]:
    """Drop repeat signals on the same ticker inside `min_gap` sessions.

    The trend screen fires on a STATE, so a name in a long uptrend signals every
    single session. Recording all of them turns one move into thirty correlated
    observations wearing the costume of thirty independent ones, which inflates
    the apparent sample and makes any confidence interval fiction. Default gap is
    the longest horizon, so recorded trades never overlap on the same ticker.
    """
    if min_gap <= 0:
        return picks
    last: dict[int, int] = {}
    kept = []
    for t, i, score in sorted(picks):
        if i in last and t - last[i] < min_gap:
            continue
        last[i] = t
        kept.append((t, i, score))
    return kept


def _draw_control(
    universe: np.ndarray,
    counts: dict[int, int],
    rng: np.random.Generator,
    min_gap: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """One random control: the screens' per-date trade counts, different names.

    Matching the count per date is the whole point. See the module docstring for
    the worked example of what a flat draw does to the comparison.

    `min_gap` matches the OTHER constraint the screens are under. The screens
    are thinned so one ticker cannot appear twice inside `min_gap` sessions; an
    unconstrained control can, and its repeat trades overlap by up to 19 of 20
    sessions with returns correlating around 0.9. Correlated trades inside a
    replicate inflate that replicate's variance, so the null distribution comes
    out wider than the correct reference and the screens' percentile is dragged
    towards 50. Simulated in review at a realistic density: null spread 1.30x
    too wide, and a result genuinely at the 99.67th percentile reading as 98.2.
    That is the difference between a pass and a maybe, and it points the wrong
    way — it hides real effects rather than inventing them.
    """
    dates: list[int] = []
    picked: list[int] = []
    last_taken: dict[int, int] = {}
    for t in sorted(counts):
        wanted = counts[t]
        available = np.flatnonzero(universe[t])
        if min_gap > 0 and len(available):
            fresh = [i for i in available if t - last_taken.get(int(i), -min_gap) >= min_gap]
            # Only honour the constraint while it leaves enough names to fill
            # the date. Falling short would break the count matching, which is
            # the more important of the two properties.
            if len(fresh) >= wanted:
                available = np.asarray(fresh, dtype=int)
        if not len(available):
            continue
        if wanted >= len(available):
            drawn = available  # Taking the whole universe needs no dice.
        else:
            drawn = rng.choice(available, size=wanted, replace=False)
        dates.extend([t] * len(drawn))
        picked.extend(int(i) for i in drawn)
        if min_gap > 0:
            for i in drawn:
                last_taken[int(i)] = t
    return np.asarray(dates, dtype=int), np.asarray(picked, dtype=int)


def _tradeable(
    panel: Panel, dates: np.ndarray, picked: np.ndarray, returns: dict[int, np.ndarray]
) -> np.ndarray:
    """Which of these (date, ticker) pairs would really have become a position.

    The same test `_record` applies: there has to be a next open to buy at, and
    at least one horizon that finishes before the data does. Applied identically
    to every arm, so no arm is quietly filtered harder than another.
    """
    entry = np.full(len(dates), np.nan)
    has_next = dates + 1 < len(panel.dates)
    entry[has_next] = panel.open[dates[has_next] + 1, picked[has_next]]
    finished = np.zeros(len(dates), dtype=bool)
    for horizon in HORIZONS:
        finished |= np.isfinite(returns[horizon][dates, picked])
    with np.errstate(invalid="ignore"):
        return np.isfinite(entry) & (entry > 0) & finished


def _trimmed_mean(values: np.ndarray, trim_pct: float = TRIM_PCT) -> float:
    """Mean after removing the best `trim_pct` of trades.

    One-sided on purpose. Trimming both ends would be a robustness measure;
    trimming only the top answers the specific question asked here, which is
    whether an apparent edge is really a handful of outsized winners.
    """
    if not len(values):
        return float("nan")
    drop = int(np.ceil(len(values) * trim_pct / 100.0))
    if drop >= len(values):
        return float("nan")
    return float(np.sort(values)[: len(values) - drop].mean())


def _tail_lift(values: np.ndarray, trim_pct: float = TRIM_PCT) -> float:
    """How many percentage points of the mean the best `trim_pct` of trades add.

    Expressed as a DIFFERENCE, not a share, and the first version got this
    wrong in a way worth keeping on the record. It divided the top trades' sum
    by the total, which reads as "the best 5% supplied 60% of the return" and
    is fine until the total is near zero — at which point it printed "1597% of
    the total" and would have printed a sign flip just as confidently. A ratio
    whose denominator can pass through zero is not a statistic, it is a trap.

    Mean minus trimmed mean has no denominator, is in the same units as
    everything beside it, and answers the question directly: this is how much of
    the headline number disappears when the luckiest trades do.
    """
    if not len(values):
        return float("nan")
    trimmed = _trimmed_mean(values, trim_pct)
    if not np.isfinite(trimmed):
        return float("nan")
    return float(values.mean() - trimmed)


def _stats_by_horizon(
    dates: np.ndarray, picked: np.ndarray, returns: dict[int, np.ndarray]
) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for horizon in HORIZONS:
        values = returns[horizon][dates, picked] if len(dates) else np.empty(0)
        values = values[np.isfinite(values)]
        out[horizon] = {
            "mean": float(values.mean()) if len(values) else float("nan"),
            "median": float(np.median(values)) if len(values) else float("nan"),
            "trimmed": _trimmed_mean(values),
        }
    return out


def null_distribution(
    panel: Panel,
    universe: np.ndarray,
    counts: dict[int, int],
    returns: dict[int, np.ndarray],
    screen_dates: np.ndarray,
    screen_picks: np.ndarray,
    in_period: np.ndarray,
    period: str,
    replicates: int = REPLICATES,
    seed: int = 7,
    family_size: int = TESTS_RUN,
    tickers: tuple[str, ...] = (),
    exit_rule: str = "hold",
    min_gap: int = 0,
) -> NullTest:
    """Run the control many times and locate the screens inside the spread.

    A mean sitting above the control's median proves nothing on its own; a mean
    sitting above 97% of controls is a claim. Reporting the percentile rather
    than a single comparison is what stops a 31-trade sample from being read as
    a discovery, which is exactly the mistake this was written to prevent.

    `in_period` is a per-date boolean, so the same sweep serves the in-sample
    and out-of-sample halves without redrawing.
    """
    keep = _tradeable(panel, screen_dates, screen_picks, returns) & in_period[screen_dates]
    mine = _stats_by_horizon(screen_dates[keep], screen_picks[keep], returns)

    tail: dict[int, float] = {}
    for horizon in HORIZONS:
        values = returns[horizon][screen_dates[keep], screen_picks[keep]]
        tail[horizon] = _tail_lift(values[np.isfinite(values)])

    rng = np.random.default_rng(seed)
    samples: dict[int, dict[str, list[float]]] = {h: {stat: [] for stat in STATS} for h in HORIZONS}
    for _ in range(replicates):
        dates, picked = _draw_control(universe, counts, rng, min_gap=min_gap)
        if not len(dates):
            continue
        ok = _tradeable(panel, dates, picked, returns) & in_period[dates]
        drawn_stats = _stats_by_horizon(dates[ok], picked[ok], returns)
        for horizon in HORIZONS:
            for stat in STATS:
                samples[horizon][stat].append(drawn_stats[horizon][stat])

    median: dict[int, dict[str, float]] = {}
    p05: dict[int, dict[str, float]] = {}
    p95: dict[int, dict[str, float]] = {}
    beats: dict[int, dict[str, float]] = {}
    for horizon in HORIZONS:
        median[horizon], p05[horizon], p95[horizon], beats[horizon] = {}, {}, {}, {}
        for stat in STATS:
            drawn = np.asarray([v for v in samples[horizon][stat] if np.isfinite(v)])
            observed = mine[horizon][stat]
            if not len(drawn) or not np.isfinite(observed):
                for target in (median, p05, p95, beats):
                    target[horizon][stat] = float("nan")
                continue
            median[horizon][stat] = float(np.median(drawn))
            p05[horizon][stat] = float(np.percentile(drawn, 5))
            p95[horizon][stat] = float(np.percentile(drawn, 95))
            # The add-one permutation estimator, not the raw proportion. The
            # raw version prints 100%, which claims p = 0, and no finite number
            # of controls can support that: with 5000 draws the strongest
            # honest statement is 99.98%. Ties count against the screens.
            atleast = int((drawn >= observed).sum())
            beats[horizon][stat] = 100.0 * (1.0 - (1.0 + atleast) / (1.0 + len(drawn)))

    names = {tickers[i] for i in screen_picks[keep]} if len(tickers) else set()
    return NullTest(
        replicates=replicates,
        period=period,
        screen_trades=int(keep.sum()),
        distinct_tickers=len(names),
        family_size=family_size,
        exit_rule=exit_rule,
        screens=mine,
        random_median=median,
        random_p05=p05,
        random_p95=p95,
        beats_pct=beats,
        tail_lift=tail,
    )


def run(
    frames: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    cfg: Config,
    start: date,
    end: date,
    fit_end: date | None = None,
    cost_pct: float = DEFAULT_COST_PCT,
    min_gap_sessions: int | None = None,
    replicates: int = REPLICATES,
    family_size: int = TESTS_RUN,
    seed: int = 7,
    screen: str = "trend",
) -> BacktestReport:
    """Walk the window forward and measure what each arm would have earned.

    `frames` is every candidate ticker's full history. It is never sliced by date
    here, because it does not need to be: every array in the panel is causal, so
    a signal at bar t was computable from bars at or before t by construction.

    `min_gap_sessions` defaults by entry rule rather than to a constant. State
    entry fires every session the condition holds, so without thinning one
    three-month uptrend arrives as sixty correlated observations dressed as
    sixty independent ones. Confirmation entry is already one signal per move,
    so the same thinning would instead delete real re-entries: confirm, fail,
    pull back, confirm again ten sessions later is two trades a trader takes and
    the course describes, not one trade counted twice.
    """
    if screen not in ("trend", "breakout"):
        raise ValueError(f"unknown screen {screen!r}, expected 'trend' or 'breakout'")

    if min_gap_sessions is None:
        if screen == "breakout":
            # The breakout screen fires on a state, like trend entry does, and
            # for a bounded reason: `level_break_lookback` is 5, so one break can
            # keep qualifying for up to five consecutive sessions. Those are the
            # same move seen five times, and at a 20-session horizon they overlap
            # almost completely. Thinned at the longest horizon so recorded
            # trades on one ticker never overlap, and the control is thinned the
            # same way so the comparison stays like for like.
            min_gap_sessions = max(HORIZONS)
        else:
            min_gap_sessions = 0 if cfg.trend_entry == "confirmation" else max(HORIZONS)

    missing = [t for t, df in frames.items() if df["close"].isna().any()]
    if missing:
        # Wilder's RSI is a recursion, so one NaN close propagates forward for
        # ever. With the RSI gate on, that silently removes the ticker from the
        # screens arm while leaving it fully drawable by the control, which is
        # exactly the kind of asymmetric attrition that fakes a null result.
        log.warning(
            "%d ticker(s) have NaN closes and will go dead to the RSI gate: %s",
            len(missing),
            ", ".join(sorted(missing)[:8]),
        )

    panel = build_panel(frames, benchmark, cfg)
    # The control arms use the SAME exit rule as the screens. A stop is not an
    # advantage the screens get to keep to themselves; if stops improve random
    # picks just as much, the stops are what improved, not the screens.
    returns_by_horizon = {h: horizon_returns(panel, h, cost_pct, cfg) for h in HORIZONS}

    window = (panel.dates >= pd.Timestamp(start)) & (panel.dates <= pd.Timestamp(end))
    universe = universe_mask(panel, cfg) & window[:, None]

    if cfg.exit_rule == "stops" and cfg.exit_requires_levels:
        # A trade needs a stop below and a target above to be taken at all, so
        # bars that have neither are not part of the eligible universe FOR
        # EITHER ARM. Leaving that out broke the comparison in a way that took a
        # real run to notice: gate 1 cannot fire without both levels, so the
        # requirement never bound on the screens, while the control drew freely
        # from the whole universe and then had most of its picks thrown away
        # afterwards. The result was 66 screen trades against 6 controls, which
        # is not a control. Intersecting here keeps the per-date counts
        # matchable, which is the property the whole design rests on.
        # FINITENESS ONLY, tested at bar t. The first version also required the
        # levels to bracket `open[t + 1]`, which put TOMORROW'S OPEN inside a
        # mask indexed by today — a signal set the live scanner could never
        # reproduce, because at T's close that open does not exist yet. Worse
        # under confirmation entry: an overnight gap through the stop could
        # switch a name out of the universe for one bar and hand the same move a
        # second, fresher-looking transition.
        #
        # It is also unnecessary. `nearest_levels` returns the nearest level
        # strictly above and strictly below the CLOSE, so a finite pair already
        # brackets bar t. The two conditions differ only when the open gaps
        # through a level overnight, and `exit_returns` handles that case on its
        # own, symmetrically, for every arm.
        universe = universe & np.isfinite(panel.support) & np.isfinite(panel.resistance)

    if screen == "breakout":
        signals, strength = breakout_mask(frames, panel, cfg, universe=universe)
    else:
        signals, strength = trend_mask(panel, cfg, universe=universe)

    picks = [(int(t), int(i), float(strength[t, i])) for t, i in np.argwhere(signals)]
    picks = _thin(picks, min_gap_sessions)
    screen_trades = _record("screens", panel, picks, returns_by_horizon)

    # RANDOM arm: same dates, same universe, SAME NUMBER OF NAMES PER DATE, no
    # screen. Carries the identical survivorship bias and the identical date
    # weighting, so the gap between it and the screens is the screens.
    counts: dict[int, int] = {}
    for t, _, _ in picks:
        counts[t] = counts.get(t, 0) + 1
    rng = np.random.default_rng(seed)
    control_dates, control_picks = _draw_control(universe, counts, rng, min_gap=min_gap_sessions)
    random_trades = _record(
        "random from universe",
        panel,
        [(int(t), int(i), 0.0) for t, i in zip(control_dates, control_picks, strict=True)],
        returns_by_horizon,
    )

    # BENCHMARK arm: buy the tracker on every date the screens fired.
    bench_panel = build_panel({cfg.beta_benchmark: benchmark}, benchmark, cfg)
    bench_returns = {h: horizon_returns(bench_panel, h, cost_pct, cfg) for h in HORIZONS}
    bench_picks = [(t, 0, 0.0) for t in sorted({t for t, _, _ in picks})]
    bench_trades = _record(cfg.beta_benchmark, bench_panel, bench_picks, bench_returns)

    by_arm = [
        ("screens", screen_trades),
        ("random from universe", random_trades),
        (cfg.beta_benchmark, bench_trades),
    ]

    def slice_arms(keep) -> tuple[ArmStats, ...]:
        return tuple(summarise(name, [t for t in trades if keep(t)]) for name, trades in by_arm)

    # The percentile is computed on the period that gets quoted, which is the
    # hold-out when there is one. Running it in sample would be measuring how
    # well the thresholds fit the data they were read off.
    screen_dates = np.asarray([t for t, _, _ in picks], dtype=int)
    screen_picks = np.asarray([i for _, i, _ in picks], dtype=int)
    null_test = None
    if len(screen_dates) and replicates > 0:
        if fit_end is not None:
            in_period = np.asarray(panel.dates > pd.Timestamp(fit_end)) & window
            label = f"out of sample, after {fit_end}"
        else:
            in_period = window
            label = "whole period, no hold-out"
        null_test = null_distribution(
            panel,
            universe,
            counts,
            returns_by_horizon,
            screen_dates,
            screen_picks,
            in_period,
            label,
            replicates=replicates,
            seed=seed + 1,  # Not the seed the single illustrative arm used.
            family_size=family_size,
            tickers=panel.tickers,
            exit_rule=cfg.exit_rule,
            min_gap=min_gap_sessions,
        )

    return BacktestReport(
        start=start,
        end=end,
        fit_end=fit_end,
        cost_pct=cost_pct,
        sessions=int(window.sum()),
        universe_days=float(universe.sum(axis=1)[window].mean()) if window.any() else 0.0,
        arms=slice_arms(lambda t: True),
        arms_in_sample=(slice_arms(lambda t: t.signal_date <= fit_end) if fit_end else ()),
        arms_out_of_sample=(slice_arms(lambda t: t.signal_date > fit_end) if fit_end else ()),
        trades=tuple(screen_trades + random_trades + bench_trades),
        null_test=null_test,
    )


def _z_for(percentile: float) -> float:
    """Normal quantile, good enough for a power statement and dependency-free.

    Abramowitz and Stegun 26.2.23. This is reporting the order of magnitude of
    a detectable effect, not pricing an option.
    """
    p = min(max((100.0 - percentile) / 100.0, 1e-9), 0.5)
    t = float(np.sqrt(-2.0 * np.log(p)))
    return t - (2.515517 + 0.802853 * t + 0.010328 * t * t) / (
        1.0 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t
    )


def verdict(null: NullTest, horizon: int) -> str:
    """Plain English for a percentile, so nobody has to interpret it hopefully.

    Deliberately unkind, and it reads all three statistics rather than the
    flattering one. The order of the checks is the order in which a result
    fails: too few trades, then a mean carried by its tail, then the raw bar,
    then the bar corrected for how many variants were tried.
    """
    beats = null.beats_pct[horizon]
    mean_pct = beats.get("mean", float("nan"))
    if not np.isfinite(mean_pct):
        return "no trades to judge"

    n = null.screen_trades
    if n < 30:
        return f"beats {mean_pct:.0f}% of controls, but {n} trades decides nothing either way"

    # Failing a bar the data could never have cleared is not a negative result,
    # it is an absent one, and the two must not print the same way.
    floor = null.detectable_effect(horizon)
    observed = null.screens[horizon]["mean"] - null.random_median[horizon]["mean"]
    underpowered = np.isfinite(floor) and np.isfinite(observed) and 0.0 < observed < floor

    trimmed_pct = beats.get("trimmed", float("nan"))
    median_pct = beats.get("median", float("nan"))
    lift = null.tail_lift[horizon]
    if mean_pct >= 95.0 and np.isfinite(trimmed_pct) and trimmed_pct < 80.0:
        return (
            f"beats {mean_pct:.0f}% on the mean but only {trimmed_pct:.0f}% once its best "
            f"5% of trades are removed. The edge IS the tail, not the strategy"
        )
    if (
        null.exit_rule != "stops"
        and mean_pct >= 95.0
        and np.isfinite(median_pct)
        and median_pct < 50.0
    ):
        return (
            f"beats {mean_pct:.0f}% on the mean while its typical trade is WORSE than "
            f"random ({median_pct:.0f}th percentile). Its best 5% of trades supply "
            f"{lift:.2f} points of the mean"
        )
    if mean_pct >= null.corrected_bar and null.resolvable:
        return (
            f"beats {mean_pct:.0f}% of controls, clearing even the "
            f"{null.corrected_bar:.1f}% bar for {null.family_size} tests. Take this seriously"
        )
    if mean_pct >= null.corrected_bar and not null.resolvable:
        # Checked BEFORE the power branch. A result that clears the bar but
        # cannot be resolved at it is a resolution problem, not a power problem,
        # and the first version printed "short of the bar" about a number that
        # was not short of the bar.
        return (
            f"beats {mean_pct:.1f}% of controls, at or past the "
            f"{null.corrected_bar:.1f}% bar — but {null.replicates} controls cannot "
            "resolve a difference there. Rerun with more before believing it"
        )
    if mean_pct >= 95.0 and underpowered:
        return (
            f"beats {mean_pct:.0f}% of controls, short of the {null.corrected_bar:.1f}% "
            f"bar — but that bar demands {floor:.2f} points per trade and the effect is "
            f"{observed:+.2f}. The design cannot resolve this. Underpowered, not negative"
        )
    if mean_pct >= 95.0:
        if not null.resolvable:
            return (
                f"beats {mean_pct:.0f}% of controls, but {null.replicates} controls cannot "
                f"resolve the {null.corrected_bar:.1f}% bar {null.family_size} tests demand. "
                "Rerun with more"
            )
        return (
            f"beats {mean_pct:.0f}% of controls, short of the {null.corrected_bar:.1f}% "
            f"that {null.family_size} tests demand. Promising, not proven"
        )
    if mean_pct >= 80.0 and underpowered:
        return (
            f"beats {mean_pct:.0f}% of controls, short of the bar — but the bar needed "
            f"{floor:.2f} points and only {observed:+.2f} was on offer. UNDERPOWERED, "
            "not negative: this run could not have certified this effect either way"
        )
    if mean_pct >= 80.0:
        return f"beats {mean_pct:.0f}% of controls. Suggestive, short of the bar, do not trade it"
    if mean_pct <= 5.0:
        return f"beats only {mean_pct:.0f}% of controls. Actively worse than picking at random"
    return f"beats {mean_pct:.0f}% of controls, which is what a coin toss looks like"


LABELS = {
    "mean": "mean",
    "median": "median (typical trade)",
    "trimmed": "mean, best 5% removed",
}


def _null_lines(null: NullTest) -> list[str]:
    out = [
        f"=== IS IT LUCK? {null.replicates} random controls, {null.period} ===",
        "  Every control takes the same number of names on the same dates as the",
        "  screens did. The only difference is which names. So this asks the one",
        f"  question that matters: {null.screen_trades} screen trades across "
        f"{null.distinct_tickers} tickers, could they be chance?",
        f"  Bar is {null.corrected_bar:.1f}%, not 95%, because {null.family_size} variants "
        "have been tested against this data.",
        "",
    ]
    for horizon in HORIZONS:
        out.append(f"  -- {horizon}-session horizon")
        out.append(f"     {'':<24}{'screens':>9}{'controls':>10}{'beats':>8}")
        for stat in STATS:
            suspect = stat == "median" and null.exit_rule == "stops"
            out.append(
                f"     {LABELS[stat]:<24}{null.screens[horizon][stat]:>8.2f}%"
                f"{null.random_median[horizon][stat]:>9.2f}%"
                f"{null.beats_pct[horizon][stat]:>7.0f}%"
                + ("   <- ignore, see below" if suspect else "")
            )
        out.append(
            f"     best 5% of trades supply {null.tail_lift[horizon]:.2f} points of that mean"
        )
        floor = null.detectable_effect(horizon)
        observed = null.screens[horizon]["mean"] - null.random_median[horizon]["mean"]
        if np.isfinite(floor):
            out.append(
                f"     could only have certified an edge of {floor:.2f} points or more; "
                f"observed {observed:+.2f}"
            )
        out.append(f"     {verdict(null, horizon)}")
        out.append("")
    if null.exit_rule == "stops":
        out += [
            "  The median row is not evidence under stops. Stopped-out trades pile up",
            "  just below zero, so the median sits inside that lump and moves a long way",
            "  on a small change in how often an arm gets stopped. On a synthetic feed",
            "  with no signal at all it still beat 99-100% of controls. Read the mean.",
            "",
        ]
    return out


def render(report: BacktestReport) -> str:
    """The result, with every caveat printed rather than filed away."""
    lines = [
        f"Backtest {report.start} to {report.end}",
        f"  {report.sessions} sessions, {report.universe_days:.0f} tickers in the "
        "universe on an average day",
        f"  Costs: {report.cost_pct:.2f}% per round trip, already deducted from every return",
        f"  {report.in_sample_note}",
        "",
    ]

    def table(title: str, arms: tuple[ArmStats, ...], note: str = "") -> list[str]:
        out = [title]
        if note:
            out.append(f"  {note}")
        for horizon in HORIZONS:
            out.append(f"  -- {horizon}-session horizon")
            out.append(f"  {'arm':<24}{'trades':>8}{'hit':>8}{'mean':>9}{'median':>9}{'worst':>9}")
            for arm in arms:
                out.append(
                    f"  {arm.name:<24}{arm.trades:>8}{arm.hit_rate[horizon]:>7.1f}%"
                    f"{arm.mean[horizon]:>8.2f}%{arm.median[horizon]:>8.2f}%"
                    f"{arm.worst[horizon]:>8.1f}%"
                )
            out.append("")
        return out

    # The percentile goes FIRST. Put it under the tables and it reads as a
    # footnote to numbers already believed, which is the wrong way round: the
    # tables are the evidence, this is the finding.
    if report.null_test is not None:
        lines += _null_lines(report.null_test)

    if report.arms_out_of_sample:
        lines += table(
            f"=== OUT OF SAMPLE, after {report.fit_end}. THIS IS THE RESULT. ===",
            report.arms_out_of_sample,
            "No threshold in this project was calibrated on this period.",
        )
        lines += table(
            f"=== in sample, up to {report.fit_end}. Do not quote these. ===",
            report.arms_in_sample,
            "The gap thresholds were measured on this data, so it is fitted to itself.",
        )
    else:
        lines += table(
            "=== WHOLE PERIOD, no hold-out ===",
            report.arms,
            "Every threshold was measured on this same data. Treat as indicative only.",
        )

    if report.null_test is not None and report.null_test.family_size > 1:
        lines += [
            f"On the bar: Bonferroni assumes {report.null_test.family_size} INDEPENDENT tests",
            "and these are not independent. They share trades, dates, and three horizons of",
            "the same positions. The honest bar is somewhere between 95% and",
            f"{report.null_test.corrected_bar:.1f}%, nearer the top. It is left at the",
            "conservative end deliberately, because the alternative is choosing a",
            "correction after seeing the number, which is how people fool themselves.",
            "",
            "Scope: the control trades the same dates, so this measures which NAMES were",
            "picked, never when. A timing edge would score 50 here by construction.",
            "",
        ]

    lines += [
        "The single random row above is one draw, kept because it is legible. It is",
        "not the evidence; the percentile is. And SPY has no survivorship bias while",
        "this universe does, so beating SPY is partly just that gap.",
        "",
    ]
    if report.price_is_adjusted:
        lines.append(
            "Caveat: prices are split and dividend adjusted using corporate actions known"
            " today, so the price floor is applied to prices you could not have seen."
        )
    return "\n".join(lines)
