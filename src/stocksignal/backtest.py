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

from stocksignal.config import Config
from stocksignal.indicators import rsi, sma

log = logging.getLogger(__name__)

HORIZONS = (5, 10, 20)
DEFAULT_COST_PCT = 0.2  # Round trip, in percent. Stated in every report.
REPLICATES = 200  # Independent random controls behind the percentile.


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

    This is the only line in the report that answers "could this be luck?".
    Every control draws the same number of names on the same dates as the
    screens did, so the sole difference between a control and the screens is
    which names got picked. `beats_pct` is the share of controls the screens
    beat, which is a permutation test spelled out in plain words: 50 means the
    screens are a coin toss, 95 or better is the conventional bar for saying
    something is there, and anything between is a result you do not have yet.
    """

    replicates: int
    period: str
    screen_trades: int
    screens_mean: dict[int, float]
    random_median: dict[int, float]
    random_p05: dict[int, float]
    random_p95: dict[int, float]
    beats_pct: dict[int, float]


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
    out["fast"] = sma(df["close"], cfg.sma_fast)
    out["slow"] = sma(df["close"], cfg.sma_slow)
    out["gap"] = (out["fast"] - out["slow"]) / out["slow"] * 100.0
    out["avg_volume"] = df["volume"].rolling(cfg.avg_volume_window, min_periods=1).mean()
    reading = rsi(df["close"], cfg.rsi_period)
    out["rsi"] = reading
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
    fast: np.ndarray
    slow: np.ndarray
    gap: np.ndarray
    avg_volume: np.ndarray
    rsi: np.ndarray
    rsi_low: np.ndarray
    beta: np.ndarray


def build_panel(frames: dict[str, pd.DataFrame], benchmark: pd.DataFrame, cfg: Config) -> Panel:
    """Align every ticker onto the benchmark's trading calendar."""
    calendar = benchmark.index
    tickers = tuple(sorted(frames))
    fields = ("open", "close", "fast", "slow", "gap", "avg_volume", "rsi", "rsi_low", "beta")
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
    if universe is not None:
        live = live & universe
    if cfg.trend_entry == "confirmation":
        # The course's rule: the FIRST candle holding above the line, not every
        # candle that happens to be above it. A transition from not-passing to
        # passing, so one signal per move instead of one per session.
        previous = np.vstack([np.zeros((1, live.shape[1]), dtype=bool), live[:-1]])
        live = live & ~previous
    return live, np.where(passes, strength, 0.0)


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
) -> tuple[np.ndarray, np.ndarray]:
    """One random control: the screens' per-date trade counts, different names.

    Matching the count per date is the whole point. See the module docstring for
    the worked example of what a flat draw does to the comparison.
    """
    dates: list[int] = []
    picked: list[int] = []
    for t, wanted in counts.items():
        available = np.flatnonzero(universe[t])
        if not len(available):
            continue
        if wanted >= len(available):
            drawn = available  # Taking the whole universe needs no dice.
        else:
            drawn = rng.choice(available, size=wanted, replace=False)
        dates.extend([t] * len(drawn))
        picked.extend(int(i) for i in drawn)
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


def _mean_by_horizon(
    dates: np.ndarray, picked: np.ndarray, returns: dict[int, np.ndarray]
) -> dict[int, float]:
    out: dict[int, float] = {}
    for horizon in HORIZONS:
        values = returns[horizon][dates, picked] if len(dates) else np.empty(0)
        values = values[np.isfinite(values)]
        out[horizon] = float(values.mean()) if len(values) else float("nan")
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
    screens_mean = _mean_by_horizon(screen_dates[keep], screen_picks[keep], returns)

    rng = np.random.default_rng(seed)
    samples: dict[int, list[float]] = {h: [] for h in HORIZONS}
    for _ in range(replicates):
        dates, picked = _draw_control(universe, counts, rng)
        if not len(dates):
            continue
        ok = _tradeable(panel, dates, picked, returns) & in_period[dates]
        means = _mean_by_horizon(dates[ok], picked[ok], returns)
        for horizon in HORIZONS:
            samples[horizon].append(means[horizon])

    median: dict[int, float] = {}
    p05: dict[int, float] = {}
    p95: dict[int, float] = {}
    beats: dict[int, float] = {}
    for horizon in HORIZONS:
        drawn = np.asarray([v for v in samples[horizon] if np.isfinite(v)])
        mine = screens_mean[horizon]
        if not len(drawn) or not np.isfinite(mine):
            median[horizon] = p05[horizon] = p95[horizon] = beats[horizon] = float("nan")
            continue
        median[horizon] = float(np.median(drawn))
        p05[horizon] = float(np.percentile(drawn, 5))
        p95[horizon] = float(np.percentile(drawn, 95))
        beats[horizon] = float((drawn < mine).mean() * 100.0)

    return NullTest(
        replicates=replicates,
        period=period,
        screen_trades=int(keep.sum()),
        screens_mean=screens_mean,
        random_median=median,
        random_p05=p05,
        random_p95=p95,
        beats_pct=beats,
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
    seed: int = 7,
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
    if min_gap_sessions is None:
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
    returns_by_horizon = {h: forward_returns(panel, h, cost_pct) for h in HORIZONS}

    window = (panel.dates >= pd.Timestamp(start)) & (panel.dates <= pd.Timestamp(end))
    universe = universe_mask(panel, cfg) & window[:, None]
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
    control_dates, control_picks = _draw_control(universe, counts, rng)
    random_trades = _record(
        "random from universe",
        panel,
        [(int(t), int(i), 0.0) for t, i in zip(control_dates, control_picks, strict=True)],
        returns_by_horizon,
    )

    # BENCHMARK arm: buy the tracker on every date the screens fired.
    bench_panel = build_panel({cfg.beta_benchmark: benchmark}, benchmark, cfg)
    bench_returns = {h: forward_returns(bench_panel, h, cost_pct) for h in HORIZONS}
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


def verdict(beats_pct: float, trades: int) -> str:
    """Plain English for a percentile, so nobody has to interpret it hopefully.

    The bar is deliberately unkind. A screen you are going to risk money on
    should clear it comfortably, and one that lands in the middle is not a weak
    result to be nursed along, it is an absence of one.
    """
    if not np.isfinite(beats_pct):
        return "no trades to judge"
    if trades < 30:
        return f"beats {beats_pct:.0f}% of controls, but {trades} trades decides nothing either way"
    if beats_pct >= 95.0:
        return f"beats {beats_pct:.0f}% of controls. This one is worth taking seriously"
    if beats_pct >= 80.0:
        return f"beats {beats_pct:.0f}% of controls. Suggestive, short of the bar, do not trade it"
    if beats_pct <= 5.0:
        return f"beats only {beats_pct:.0f}% of controls. Actively worse than picking at random"
    return f"beats {beats_pct:.0f}% of controls, which is what a coin toss looks like"


def _null_lines(null: NullTest) -> list[str]:
    out = [
        f"=== IS IT LUCK? {null.replicates} random controls, {null.period} ===",
        "  Every control takes the same number of names on the same dates as the",
        "  screens did. The only difference is which names. So this asks the one",
        f"  question that matters: {null.screen_trades} screen trades, could they be chance?",
        "",
    ]
    for horizon in HORIZONS:
        out.append(f"  -- {horizon}-session horizon")
        out.append(f"     {'screens mean':<22}{null.screens_mean[horizon]:>8.2f}%")
        out.append(
            f"     {'random controls':<22}{null.random_median[horizon]:>8.2f}%"
            f"   (5th to 95th: {null.random_p05[horizon]:.2f}% "
            f"to {null.random_p95[horizon]:.2f}%)"
        )
        out.append(f"     {verdict(null.beats_pct[horizon], null.screen_trades)}")
        out.append("")
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
