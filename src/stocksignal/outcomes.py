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

ENTRY IS THE FIRST PRICE THAT EXISTED AFTER THE SIGNAL WAS PUBLISHED, AND THAT
IS NOT ALWAYS THE NEXT OPEN. The design says a signal dated D is known after D's
close and fills at D+1's open, which matched `backtest.forward_return` and was
true while the scheduled scan ran before the bell. It stopped being true on
28 August 2026: every run since has stamped `logged_at` between 15:53 and 18:53
UTC, which is 11:53 to 14:53 in New York, hours after the open it was being
scored at. Scoring those signals at D+1's open buys a price that had already
gone by the time the digest existed.

So the fill follows the clock in the ledger. A signal logged before the opening
bell fills at D+1's OPEN; one logged after it fills at D+1's CLOSE, which is the
next price a person reading the message could actually have paid. The basis is
recorded per trade and counted in the report, because a mixed convention that
nobody can see is worse than either convention alone.

A row with no `logged_at` is one reconstructed from a digest, which the ledger
marks; those all predate the drift and are filled at the open.

FOUR HORIZONS, AND THEY ARE NOT INTERCHANGEABLE.

  5, 20, 60 sessions   buy the next open, sell the close that many sessions
                       later. 20 is the project's primary horizon and the
                       headline; 5 and 60 are context, not alternatives to
                       reach for when 20 disappoints.
  sell on validation   buy the next open, sell at the open after the first bar
                       that OPENS below the 9 SMA.

                       THIS IS NOT THE RULEBOOK'S EXIT, AND CALLING IT THAT WAS
                       AN ERROR THIS DOCSTRING EXISTS TO STOP REPEATING. Page
                       107 is explicit: validation is the first candle holding
                       below the 9 SMA and it is NOT a concrete exit point, it
                       is the moment you re-weigh the elevating factors against
                       the deprecating ones and decide. `exits.py` carries that
                       distinction in `ExitEvent.is_instruction` and warns that
                       collapsing validation into a sell is the easiest way to
                       get exits wrong. This column does exactly that, because
                       a mechanical rule is all that can be scored without a
                       person in the loop, and it is labelled as the proxy it is.

                       The rulebook's actual exit is a hard stop at a previous
                       support level plus a 5% trailing stop armed only AFTER
                       the price target is reached. Neither can be scored from
                       the ledger today: the stop basis is the open support
                       question (three touches is undefined 92% of the time,
                       and `position.py` records that a stop derived from the
                       level that earned the ratio stopped out 77% of trades),
                       and `opportunity.py` deliberately refuses to publish a
                       price target without a growth direction. Two decisions,
                       not two bugs.

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
from datetime import UTC, date, datetime

import pandas as pd

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


OPEN = "open"
CLOSE = "close"
BELL_UTC = 13 * 60 + 30
"""13:30 UTC is the New York open under EDT, 14:30 under EST.

The earlier of the two is used deliberately: through the winter months it
classifies the 13:30-14:30 hour as "after the bell" when the market had not
opened, which costs a slightly later fill and never an unbuyable one. Erring
the other way would hand the tool prices it could not have had."""


def published_at(logged_at: str | None) -> datetime | None:
    """The ledger's clock, in UTC. None when the row carries no stamp.

    The scan writes `datetime.now().isoformat()` on a GitHub runner, which is
    naive UTC. A tz-aware stamp is converted rather than trusted for its wall
    clock, because reading "16:00+05:00" as four in the afternoon UTC would
    call an after-bell run a before-bell one.
    """
    if not logged_at:
        return None
    try:
        stamp = datetime.fromisoformat(logged_at)
    except ValueError:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(UTC).replace(tzinfo=None)
    return stamp


def fill_basis(logged_at: str | None, entry_day: date) -> str:
    """OPEN if the signal was published before the bell on the entry day, else CLOSE.

    A stamp LATER than the entry day cannot be filled on it at all, at any
    price. That case is handled by `entry_position`, which moves the entry to a
    session the reader could have acted in; by the time this function sees such
    a row the day has already been corrected, so the late branch here is a
    backstop and returns the conservative answer.
    """
    stamp = published_at(logged_at)
    if stamp is None:
        return OPEN
    if stamp.date() < entry_day:
        return OPEN
    if stamp.date() > entry_day:
        return CLOSE
    return OPEN if stamp.hour * 60 + stamp.minute < BELL_UTC else CLOSE


def entry_position(bars: pd.DataFrame, as_of: date, logged_at: str | None) -> int | None:
    """The first session the reader could have traded, which is not always D+1.

    Normally the bar after the signal date. But a run that lands a day or more
    late -- a delayed schedule, a rerun, a Friday signal scanned on Tuesday --
    publishes after D+1 has already closed, and filling it there would buy a
    session nobody could reach. Those enter on the first session at or after the
    day the digest actually existed.
    """
    pos = entry_index(bars, as_of)
    if pos is None:
        return None
    stamp = published_at(logged_at)
    if stamp is None:
        return pos
    while pos < len(bars) and bars.index[pos].date() < stamp.date():
        pos += 1
    return pos if pos < len(bars) else None


def span_return(
    bars: pd.DataFrame,
    entry_pos: int,
    exit_pos: int,
    entry_field: str,
    exit_field: str,
    cost_pct: float,
) -> float | None:
    """Percent from one named price to another. None if the exit is off the end.

    ONE FUNCTION FOR THE TRADE AND THE BENCHMARK, which is the point. They were
    separate, and the benchmark leg for the validation exit was priced to a
    CLOSE while the trade sold at an OPEN, so every such comparison ran half a
    session long. Sharing the code makes that class of mismatch unsayable.
    """
    if exit_pos >= len(bars) or entry_pos < 0 or exit_pos <= entry_pos:
        return None
    entry = float(bars[entry_field].iloc[entry_pos])
    exit_price = float(bars[exit_field].iloc[exit_pos])
    if not (math.isfinite(entry) and math.isfinite(exit_price)) or entry <= 0:
        return None
    return (exit_price / entry - 1.0) * 100.0 - cost_pct


def validation_exit(
    bars: pd.DataFrame,
    entry_pos: int,
    fast_window: int = 9,
    max_hold: int = MAX_HOLD,
) -> int | None:
    """Sessions held until the sell, for the validation proxy. None while still open.

    The rule scored here: hold until the first bar that OPENS below the fast
    SMA, sell at the next open. THIS IS NOT THE RULEBOOK'S EXIT. Page 107 calls
    validation a moment to re-weigh the elevating factors against the
    deprecating ones, explicitly not a concrete exit point, and `exits.py`
    carries that distinction. This is the mechanical proxy that can be scored
    without a person in the loop, and it is named for what it is.
    """
    fast = sma(bars["close"], fast_window)
    limit = min(entry_pos + max_hold, len(bars) - 2)
    for pos in range(entry_pos, limit + 1):
        open_ = float(bars[OPEN].iloc[pos])
        line = float(fast.iloc[pos])
        if math.isfinite(line) and math.isfinite(open_) and open_ < line:
            return pos + 1 - entry_pos
    if entry_pos + max_hold <= len(bars) - 2:
        return max_hold
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
    basis: str = "open"
    """Which price the entry was filled at. See `fill_basis`."""

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
    logged_at: str | None = None,
) -> Scored | None:
    """Score one signal. None when no horizon has finished yet.

    THE BENCHMARK IS HELD FOR THE SAME SESSIONS AND PRICED THE SAME WAY. Same
    entry basis, same exit field, same number of sessions; only the instrument
    differs. Costs are deducted from the trade and never from the benchmark,
    because the comparison is "my trade after costs against buying the index",
    and the index leg is one purchase made once.
    """
    entry_pos = entry_position(bars, as_of, logged_at)
    if entry_pos is None or entry_pos >= len(bars):
        return None
    entry_day = bars.index[entry_pos].date()
    basis = fill_basis(logged_at, entry_day)

    def legs(frame: pd.DataFrame, pos: int, cost: float) -> dict[str | int, float]:
        out: dict[str | int, float] = {}
        for horizon in HORIZONS:
            value = span_return(frame, pos, pos + horizon, basis, CLOSE, cost)
            if value is not None:
                out[horizon] = value
        return out

    returns = legs(bars, entry_pos, cost_pct)
    held = validation_exit(bars, entry_pos, fast_window)
    if held is not None:
        value = span_return(bars, entry_pos, entry_pos + held, basis, OPEN, cost_pct)
        if value is not None:
            returns[RULEBOOK] = value
        else:
            held = None

    marks: dict[str, dict[str | int, float]] = {}
    for name, frame in benchmarks.items():
        bench_entry = entry_position(frame, as_of, logged_at)
        if bench_entry is None:
            continue
        row = legs(frame, bench_entry, 0.0)
        if held is not None:
            value = span_return(frame, bench_entry, bench_entry + held, basis, OPEN, 0.0)
            if value is not None:
                row[RULEBOOK] = value
        marks[name] = row

    if not returns:
        return None
    return Scored(
        ticker=ticker,
        as_of=as_of,
        entry_date=entry_day,
        returns=returns,
        benchmarks=marks,
        held=held,
        basis=basis,
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
