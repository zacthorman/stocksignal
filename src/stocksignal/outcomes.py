"""What actually happened to every signal the tool ever published.

THE POINT OF THE WHOLE PROJECT, AND IT HAS NEVER RUN. `signal_log.py` says it
in its own first paragraph: anyone can print a list of tickers, and keeping an
honest timestamped record of what you claimed and scoring it later is the part
that turns a toy into evidence. The `outcomes` table has held zero rows since
the day it was created, first because the scheduled scan wrote its database to
a runner that was then destroyed, and after that was fixed on 31 August,
because nothing had been written to score it with. This is that.

WHAT A SIGNAL IS SCORED AS. A paper trade, equal weight, every name, whether or
not Zac took it. The ledger records what the TOOL claimed, so the measurement
has to be of the tool's calls. Reconstructing which ones he would have taken,
months later, from memory, would mark its own homework.

ENTRY IS THE NEXT OPEN, ALWAYS. The scan reads completed daily bars, so a
signal dated D is known after D's close and the earliest fill is D+1's open.
This matches `backtest.forward_return` exactly, and matching it is the point:
numbers from the live ledger and numbers from the backtest have to be readable
against each other or neither means anything.

FOUR HORIZONS, AND THEY ARE NOT INTERCHANGEABLE.

  5, 20, 60 sessions   buy the next open, sell the close that many sessions
                       later. 20 is the project's primary horizon and the
                       headline; 5 and 60 are context, not alternatives to
                       reach for when 20 disappoints.
  rulebook exit        buy the next open, sell at the open after the first bar
                       that OPENS below the 9 SMA (p111: a candle that dips
                       below but does not open below "was not a Validation").
                       The only horizon that corresponds to a rule Zac would
                       actually trade, and the one that made the difference
                       between a 96th percentile result and a worse-than-random
                       one in August.

UNFINISHED IS NOT FLAT. A horizon that has not elapsed yet returns None and is
recorded as pending. Counting an open position as a zero would drag every mean
toward nothing and would do it worst in exactly the periods with the most
recent signals.

THE BENCHMARK IS SUBTRACTED OVER THE SAME WINDOW, per trade, because a month
when everything went up is not a month when the screens worked. SPY is the
like-for-like comparator; the all-world tracker is the project's original
honesty gate and is reported separately.

MEAN, MEDIAN AND TRIMMED MEAN ARE ALL REPORTED, ALWAYS. The factor search on
17 September passed a pre-registered test on a mean that seven trades out of
138 had supplied 92% of. A summary here that printed the mean alone would be
capable of the same lie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from stocksignal.backtest import forward_return
from stocksignal.indicators import sma

HORIZONS = (5, 20, 60)
RULEBOOK = "exit"
"""Key for the rulebook exit in a scored row, alongside the integer horizons."""

MAX_HOLD = 252
DEFAULT_COST_PCT = 0.2


def entry_index(bars: pd.DataFrame, as_of: date) -> int | None:
    """Position of the first bar AFTER the signal date. None if there isn't one."""
    later = bars.index[bars.index > pd.Timestamp(as_of)]
    if later.empty:
        return None
    return int(bars.index.get_loc(later[0]))


def rulebook_exit_return(
    bars: pd.DataFrame,
    entry_pos: int,
    fast_window: int = 9,
    cost_pct: float = DEFAULT_COST_PCT,
    max_hold: int = MAX_HOLD,
) -> tuple[float, int] | None:
    """Hold until the first bar that OPENS below the fast SMA, then sell the next open.

    Returns (percent, sessions held), or None while the trade is still open at
    the end of the data. A position that reaches `max_hold` without ever opening
    below the SMA is closed there and reported as closed, because a cap that
    silently discards its longest holds would drop precisely the trades that
    trended.
    """
    fast = sma(bars["close"], fast_window)
    entry = float(bars["open"].iloc[entry_pos])
    if entry <= 0 or not math.isfinite(entry):
        return None
    limit = min(entry_pos + max_hold, len(bars) - 2)
    for pos in range(entry_pos, limit + 1):
        open_ = float(bars["open"].iloc[pos])
        line = float(fast.iloc[pos])
        if math.isfinite(line) and open_ < line:
            exit_price = float(bars["open"].iloc[pos + 1])
            return (exit_price / entry - 1.0) * 100.0 - cost_pct, pos + 1 - entry_pos
    if entry_pos + max_hold <= len(bars) - 2:
        exit_price = float(bars["open"].iloc[entry_pos + max_hold])
        return (exit_price / entry - 1.0) * 100.0 - cost_pct, max_hold
    return None


@dataclass(frozen=True)
class Scored:
    """One signal, scored at every horizon that has finished."""

    ticker: str
    as_of: date
    entry_date: date
    returns: dict[str | int, float]
    benchmarks: dict[str, dict[str | int, float]]
    held: int | None = None

    def excess(self, horizon: str | int, benchmark: str) -> float | None:
        mine = self.returns.get(horizon)
        theirs = self.benchmarks.get(benchmark, {}).get(horizon)
        if mine is None or theirs is None:
            return None
        return mine - theirs


def score_signal(
    ticker: str,
    as_of: date,
    bars: pd.DataFrame,
    benchmarks: dict[str, pd.DataFrame],
    cost_pct: float = DEFAULT_COST_PCT,
    fast_window: int = 9,
) -> Scored | None:
    """Score one signal. None when the entry bar does not exist yet.

    THE BENCHMARK IS HELD FOR THE SAME NUMBER OF SESSIONS, not the same dates.
    Sessions are what the horizons are denominated in, and a tracker's calendar
    can differ from a single name's by a halted day. Costs are NOT deducted from
    the benchmark: the comparison is "my trade after costs against buying the
    index", and the index leg is one purchase you would have made anyway.
    """
    entry_pos = entry_index(bars, as_of)
    if entry_pos is None or entry_pos >= len(bars):
        return None

    returns: dict[str | int, float] = {}
    for horizon in HORIZONS:
        value = forward_return(bars, entry_pos, horizon, cost_pct)
        if value is not None:
            returns[horizon] = value

    held: int | None = None
    exit_ = rulebook_exit_return(bars, entry_pos, fast_window, cost_pct)
    if exit_ is not None:
        returns[RULEBOOK], held = exit_

    marks: dict[str, dict[str | int, float]] = {}
    for name, frame in benchmarks.items():
        bench_entry = entry_index(frame, as_of)
        if bench_entry is None:
            continue
        row: dict[str | int, float] = {}
        for horizon in HORIZONS:
            value = forward_return(frame, bench_entry, horizon, 0.0)
            if value is not None:
                row[horizon] = value
        if held is not None:
            value = forward_return(frame, bench_entry, held, 0.0)
            if value is not None:
                row[RULEBOOK] = value
        marks[name] = row

    if not returns:
        return None
    return Scored(
        ticker=ticker,
        as_of=as_of,
        entry_date=bars.index[entry_pos].date(),
        returns=returns,
        benchmarks=marks,
        held=held,
    )


@dataclass(frozen=True)
class Summary:
    """One horizon's worth of scored trades, described four ways.

    `trimmed` drops the best 5% and is the number to read when it disagrees with
    `mean`, because a mean that needs its best trades is a mean you cannot
    trade: you do not know in advance which ones they are.

    `top_5pct_share` is None when the trades lose money in total, because a
    percentage of a negative total says nothing about concentration.
    """

    horizon: str | int
    n: int
    mean: float
    median: float
    trimmed: float
    hit_rate: float
    benchmark_mean: dict[str, float]
    excess_mean: dict[str, float]
    excess_median: dict[str, float]
    top_5pct_share: float | None

    @property
    def survives_trimming(self) -> bool:
        return self.trimmed > 0


def summarise(
    scored: list[Scored], horizon: str | int, benchmarks: tuple[str, ...]
) -> Summary | None:
    values = [s.returns[horizon] for s in scored if horizon in s.returns]
    if not values:
        return None
    series = pd.Series(values, dtype=float)
    drop = math.ceil(0.05 * len(series))
    kept = series.sort_values().iloc[: len(series) - drop] if drop < len(series) else series
    top = series.sort_values().iloc[len(series) - drop :] if drop < len(series) else series
    total = series.sum()

    bench_mean: dict[str, float] = {}
    excess_mean: dict[str, float] = {}
    excess_median: dict[str, float] = {}
    for name in benchmarks:
        theirs = [
            s.benchmarks[name][horizon]
            for s in scored
            if horizon in s.returns and horizon in s.benchmarks.get(name, {})
        ]
        gaps = [s.excess(horizon, name) for s in scored if s.excess(horizon, name) is not None]
        if theirs:
            bench_mean[name] = float(pd.Series(theirs).mean())
        if gaps:
            excess_mean[name] = float(pd.Series(gaps).mean())
            excess_median[name] = float(pd.Series(gaps).median())

    return Summary(
        horizon=horizon,
        n=len(series),
        mean=float(series.mean()),
        median=float(series.median()),
        trimmed=float(kept.mean()),
        hit_rate=float((series > 0).mean() * 100.0),
        benchmark_mean=bench_mean,
        excess_mean=excess_mean,
        excess_median=excess_median,
        # A SHARE OF A NEGATIVE OR NEAR-ZERO TOTAL IS NOT A SHARE. When the
        # trades lose money overall, "the best 5% supplied 230%" is arithmetic
        # noise rather than a concentration reading, so it is withheld.
        top_5pct_share=(float(top.sum() / total * 100.0) if total > 0 else None),
    )
