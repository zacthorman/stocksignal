"""The breakout screen at every bar, causally, without slicing the frame 400,000 times.

WHY THIS MODULE EXISTS AT ALL, when `backtest.py` already has a fast path.

The trend screen is a coincidence: at bar t it asks whether four numbers computed
from bar t stand in the right order. Four causal series and three comparisons
answer it for the entire universe at once, which is what `trend_mask` does.

The breakout screen is not a coincidence, it is a story with an order of events.
A level has to exist, then break, then be pulled back to, then be closed above,
and the bar that broke it has to be identifiable afterwards so its volume and its
three-bar setup can be read. None of that survives being flattened into a
comparison between columns, because every step is defined relative to the
position of the step before it. The screen is path-dependent, so the backtest
needs a path.

The obvious implementation is to call `screen_breakout(df.iloc[: t + 1], ...)` at
every bar of every ticker. That is 272 tickers times 1,500 bars, and each call
recomputes swing points and a 180-period average over the whole slice. It is
correct and it is unusable: measured at 41 seconds for a single ticker, which is
about five hours for the universe, per run.

So this module does what `precompute` and `nearest_levels` already do elsewhere in
this project: it keeps the screen's logic and replaces its arithmetic with an
incremental version that carries state forward instead of rebuilding it. The
saving is entirely in the level set, which is the only expensive part.

WHAT MAKES THAT SAFE, and it is not confidence. `tests/test_breakout_path.py`
asserts that `breakout_signals` returns exactly what calling `screen_breakout` on
truncated frames returns, bar for bar, on real cached data across several
tickers and several hundred bars, scores included. If this file ever drifts away
from the screen it stands in for, that test fails. It is the same guarantee
`test_backtest.py` gives for `trend_mask`, and it exists for the same reason: a
fast path nobody checks is a second, secret strategy.

HOW THE LEVEL SET IS CARRIED FORWARD.

`find_levels` on a frame truncated at t does four things: find swing points,
collapse runs of adjacent swing bars to one touch each, drop touches older than
the lookback window, then cluster what is left by price and keep clusters with
three or more touches. Three of those four are cheap. The expensive one is that
it redoes all of it from scratch at every bar.

Two facts make the incremental version exact rather than approximate.

1.  TRUNCATION IS A PREFIX FILTER ON SWINGS. `swing_points` uses a centred
    window, so a swing at bar i needs bars i - lookback to i + lookback and is
    unknowable until bar i + lookback prints. On a frame truncated at t the last
    `lookback` bars therefore return nothing, and every earlier bar returns
    exactly what it returns on the full history. So the set of swings visible at
    t is precisely those with origin <= t - lookback, and it only ever grows.

2.  A COLLAPSED RUN IS A PREFIX EXTREMUM. `_collapse_runs` reduces a run of
    adjacent swing bars to the highest of them (for highs) or the lowest (for
    lows). Truncation takes a prefix of each run, because run members are in
    position order, so the touch a run contributes at time t is the running
    maximum, or minimum, over the members confirmed so far.

    This is the one place where the obvious shortcut is wrong, and `nearest_levels`
    takes it: that function collapses runs over the FULL series once, so a run
    whose later bars are higher contributes its final representative from the
    moment its first bar confirms. On a plateau that resolves upward, the two
    disagree for a few bars. It does not matter there, because the difference is
    a fraction of a percent on a level that is about to be reclustered anyway,
    but it would matter here: this module has to match the screen exactly for
    the equivalence test to mean anything, so the representative moves as the run
    fills in, exactly as truncation makes it move.

WHAT IS DELIBERATELY NOT OPTIMISED. The per-bar breakout logic below — finding
the breaking bar, walking the retest window, reading the three-bar setup — is a
direct transcription of `screens/breakout.py`, loop for loop, in numpy rather
than pandas. It is bounded by `level_break_lookback` and `breakout_retest_window`
and costs nothing, so there was no reason to be clever with it, and every reason
not to be: transcription can be checked by eye against the original, and the
equivalence test checks the rest.

A NOTE ON WHAT THE GATES ACTUALLY ALLOW, because it surprised me and it belongs
next to the code rather than in a commit message. `level_break_lookback` is 5 and
`breakout_retest_window` is 15, so the retest window looks like the loose
constraint and is not. The break has to be within 5 sessions of today AND the
pullback and the close back above it have to have happened since the break, so
the retest has at most 5 bars to complete, never 15. The 15 is dead. That makes
this a much rarer signal than reading either number alone suggests, and a rare
signal is a small sample, which is the thing that decides what the measurement
can and cannot say.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import rsi, sma, swing_points
from stocksignal.levels import swing_runs

__all__ = ["breakout_signals", "breakout_scores"]


def breakout_signals(df: pd.DataFrame, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """Whether the breakout screen passes at every bar, and what it scored.

    Returns two arrays the length of `df`: a boolean `passed` and a float
    `score`. Score is NaN where the screen did not pass, because a score on a
    setup that failed a gate is not a number anyone should be able to read by
    accident.

    Causal by construction. Every value at index t is computable from bars 0..t,
    and there is no date parameter anywhere for a future bar to leak through.
    """
    n = len(df)
    passed = np.zeros(n, dtype=bool)
    score = np.full(n, np.nan)
    if n == 0:
        return passed, score

    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    slow = sma(df["close"], cfg.sma_slow).to_numpy(dtype=float)
    reading = rsi(df["close"], cfg.rsi_period).to_numpy(dtype=float)

    # `(df["close"] < level.price).any()` on the truncated frame, carried
    # forward. NaN closes compare False in pandas and are skipped by fmin, so the
    # two agree on a frame with holes in it.
    lowest_close = np.fmin.accumulate(close)

    # Mean volume over the 20 bars BEFORE the breaking bar. `average_volume`
    # shortens its own window when there is not enough history, so the divisor
    # here is a count, not a constant.
    window = cfg.avg_volume_window
    vol_sum = np.concatenate([[0.0], np.nancumsum(volume)])
    body = np.abs(close - open_)

    tracker = _LevelTracker(df, cfg)

    for t in range(n):
        levels = tracker.at(t)
        if not levels:
            continue

        # `_find_breakout`: the highest level price has ever been below, which is
        # the resistance from the most recent run-up rather than an old ceiling.
        best_price = np.nan
        best_recency = 0.0
        for price, last_pos in levels:
            if lowest_close[t] < price and not (price <= best_price):
                best_price = price
                best_recency = _recency(t - last_pos, cfg)
        if not np.isfinite(best_price):
            continue

        # It has to be support now, meaning price is above it. A level still
        # above the close is a ceiling that has not been broken.
        if best_price > close[t]:
            continue

        breaking = _breaking_bar(close, best_price, t, cfg.level_break_lookback)
        if breaking is None:
            continue

        if cfg.breakout_require_retest and not _retest_held(
            close, low, best_price, breaking, t, cfg
        ):
            continue

        # The uptrend gate, page 75's opening requirement.
        if not np.isfinite(slow[t]) or close[t] <= slow[t]:
            continue

        passed[t] = True

        # Everything below is elevating or deprecating. None of it gates.
        taken = min(window, breaking)
        avg_vol_before = (vol_sum[breaking] - vol_sum[breaking - taken]) / taken if taken else 0.0
        ratio = volume[breaking] / avg_vol_before if avg_vol_before > 0 else 0.0
        volume_strength = _normalise(
            ratio, cfg.breakout_volume_spike_min, cfg.breakout_volume_spike_strong
        )
        three_bar = _three_bar_setup(body, close, low, breaking, t, cfg)

        value = (
            cfg.w_breakout_volume * volume_strength
            + cfg.w_breakout_three_bar * three_bar
            + cfg.w_breakout_recency * best_recency
        )
        if np.isfinite(reading[t]) and reading[t] >= cfg.rsi_overbought:
            value -= cfg.breakout_overbought_penalty
        score[t] = round(max(value, 0.0), 4)

    return passed, score


def breakout_scores(df: pd.DataFrame, cfg: Config) -> np.ndarray:
    """Just the scores, for callers that do not need the mask."""
    return breakout_signals(df, cfg)[1]


# -- the per-bar transcription of screens/breakout.py -------------------------


def _breaking_bar(close: np.ndarray, level: float, t: int, lookback: int) -> int | None:
    """`_find_breaking_bar`: first close in the window that crosses above `level`."""
    back = min(lookback, t)
    for pos in range(t - back + 1, t + 1):
        if close[pos - 1] <= level < close[pos]:
            return pos
    return None


def _retest_held(
    close: np.ndarray, low: np.ndarray, level: float, breaking: int, t: int, cfg: Config
) -> bool:
    """`_retest_held`: a pullback to the level, then a close back above it.

    The `elif` is load-bearing and is copied deliberately: the bar that touches
    the level cannot also be the bar that confirms. The reassurance the course
    asks for is a later bar closing above, not the same bar's own close.
    """
    ceiling = level * (1 + cfg.breakout_dip_tolerance_pct / 100.0)
    last = min(breaking + cfg.breakout_retest_window, t)
    touched = False
    for pos in range(breaking + 1, last + 1):
        if not touched and low[pos] <= ceiling:
            touched = True
        elif touched and close[pos] > level:
            return True
    return False


def _three_bar_setup(
    body: np.ndarray, close: np.ndarray, low: np.ndarray, breaking: int, t: int, cfg: Config
) -> float:
    """`_three_bar_setup`: ignite, one or two babies, then a confirmation bar.

    The early `return 0.0` on a fat baby is copied rather than tidied into a
    `continue`. It means a fat baby found while testing the 3-bar shape stops the
    4-bar shape from being tested at all, which is a real asymmetry in the
    original and not obviously intended — but this file's job is to match the
    screen, not to improve it. Fixing it here and not there would put a silent
    difference between the digest and the backtest, which is the exact failure
    this module is built to avoid. It is on the record in the session log.
    """
    ignite_body = body[breaking]
    if ignite_body <= 0:
        return 0.0

    for babies in (1, 2):
        confirm = breaking + babies + 1
        if confirm > t:
            continue
        bodies = body[breaking + 1 : breaking + 1 + babies]
        if np.any(bodies >= ignite_body):
            continue
        if np.any(low[breaking + 1 : breaking + 1 + babies] < low[breaking]):
            return 0.0
        if close[confirm] <= np.max(close[breaking + 1 : breaking + 1 + babies]):
            continue
        # See the screen: a zero-body baby is the strongest possible test, and
        # `_normalise` clamps the infinity to 1.0.
        biggest_baby = float(np.max(bodies))
        ratio = ignite_body / biggest_baby if biggest_baby > 0 else float("inf")
        strength = _normalise(ratio, 1.0, cfg.breakout_ignition_strong_ratio)
        if babies == 2:
            strength = min(strength * 1.1, 1.0)
        return float(strength)
    return 0.0


def _normalise(value: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 0.0
    return max(0.0, min((value - floor) / (ceiling - floor), 1.0))


def _recency(age: int, cfg: Config) -> float:
    """`levels._recency`, in sessions, without the index lookup."""
    if age <= cfg.level_fresh_days:
        return 1.0
    span = cfg.level_lookback_days - cfg.level_fresh_days
    return round(max(0.0, 1.0 - (age - cfg.level_fresh_days) / span), 4)


# -- the incremental level set ------------------------------------------------


class _LevelTracker:
    """`classify_levels(find_levels(df[: t + 1]))`, carried forward instead of rebuilt.

    Yields, at each bar, the three-touch levels as (price, last_touch_position)
    pairs. Classification into support and resistance is left to the caller
    because it is one comparison against that bar's close, and `flipped` is not
    read by the breakout screen at all.
    """

    def __init__(self, df: pd.DataFrame, cfg: Config) -> None:
        self.cfg = cfg
        self.n = len(df)
        self.swing = cfg.level_swing_lookback
        # `find_levels` returns nothing at all until the frame is long enough for
        # a centred window, and `_recent_touches` checks that before anything
        # else. Same guard, same place in the order.
        self.min_bars = 2 * self.swing + 1

        highs, lows = swing_points(df["high"], df["low"], self.swing)
        index = df.index
        # Highs first, then lows, matching `_recent_touches`. The order survives
        # the stable sort by price below, so ties between a high and a low at the
        # same price cluster in the same order they do in the screen.
        self._runs: list[_Run] = []
        for series, take_highest in ((highs, True), (lows, False)):
            for positions, prices in swing_runs(series, index):
                self._runs.append(_Run(positions, prices, take_highest))
        # Confirmation order, so the sweep below can stop early.
        self._runs.sort(key=lambda run: run.positions[0])

        self._next_run = 0
        self._live: list[_Run] = []
        self._dirty = True
        self._cached: tuple[tuple[float, int], ...] = ()

    def at(self, t: int) -> tuple[tuple[float, int], ...]:
        if t + 1 < self.min_bars:
            return ()

        confirmed_to = t - self.swing
        while self._next_run < len(self._runs) and self._runs[self._next_run].positions[0] <= (
            confirmed_to
        ):
            self._live.append(self._runs[self._next_run])
            self._next_run += 1
            self._dirty = True

        # A run whose representative moves is a changed touch, so the cluster set
        # has to be rebuilt even though nothing entered or left.
        for run in self._live:
            if run.advance(confirmed_to):
                self._dirty = True

        # `_recent_touches` keeps touches dated on or after the cutoff, and the
        # cutoff is a bar position on the truncated frame, so it moves every bar.
        cutoff = max(0, t + 1 - self.cfg.level_lookback_days)
        kept = [run for run in self._live if run.rep_position >= cutoff]
        if len(kept) != len(self._live):
            self._live = kept
            self._dirty = True

        if self._dirty:
            self._cached = self._cluster(t)
            self._dirty = False
        return self._cached

    def _cluster(self, t: int) -> tuple[tuple[float, int], ...]:
        touches = [(run.rep_position, run.rep_price) for run in self._live]
        if len(touches) < self.cfg.level_min_touches:
            return ()
        # Stable sort by price alone, exactly as `_recent_touches` does, so a tie
        # keeps the highs-before-lows order established above.
        touches.sort(key=lambda pair: pair[1])

        out: list[tuple[float, int]] = []
        cluster: list[tuple[int, float]] = [touches[0]]
        total = touches[0][1]
        tolerance = self.cfg.level_tolerance_pct

        def flush(group: list[tuple[int, float]]) -> None:
            if len(group) >= self.cfg.level_min_touches:
                out.append(
                    (
                        sum(price for _, price in group) / len(group),
                        max(position for position, _ in group),
                    )
                )

        for position, price in touches[1:]:
            mean = total / len(cluster)
            if mean > 0 and abs(price - mean) / mean * 100.0 <= tolerance:
                cluster.append((position, price))
                total += price
            else:
                flush(cluster)
                cluster = [(position, price)]
                total = price
        flush(cluster)
        return tuple(out)


class _Run:
    """One run of adjacent swing bars, and the touch it contributes over time.

    The representative is the running extremum over the members confirmed so
    far, which is what truncating the frame does to `_collapse_runs`.
    """

    __slots__ = ("positions", "prices", "take_highest", "_seen", "rep_position", "rep_price")

    def __init__(self, positions: list[int], prices: list[float], take_highest: bool) -> None:
        self.positions = positions
        self.prices = prices
        self.take_highest = take_highest
        self._seen = 0
        self.rep_position = positions[0]
        self.rep_price = prices[0]

    def advance(self, confirmed_to: int) -> bool:
        """Take in any members that have now printed. True if the touch moved."""
        moved = False
        while self._seen + 1 < len(self.positions) and self.positions[self._seen + 1] <= (
            confirmed_to
        ):
            self._seen += 1
            price = self.prices[self._seen]
            better = price > self.rep_price if self.take_highest else price < self.rep_price
            if better:
                self.rep_position = self.positions[self._seen]
                self.rep_price = price
                moved = True
        return moved
