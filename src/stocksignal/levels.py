"""Support and resistance: turning swing points into levels the rulebook recognises.

From the rulebook:
  * Mark support and resistance, long term and short term.
  * Three confirmations of a level makes it the level.
  * A break above resistance makes it new support, and a break below support makes it
    new resistance.

Two ideas do the work here.

The first is that a level is a zone, not a line. Price does not turn at 100.00 three
times to four decimal places; it turns at 99.6, then 100.5, then 100.0, and a human
looking at the chart calls that one level. So swing points get clustered, and the width
of the cluster is a percentage of price rather than a fixed amount of money.

The second is that swing highs and swing lows go into the same pool. Nothing here is
born a support or a resistance. A level is just a price the market has respected, and
whether it is a floor or a ceiling depends entirely on which side price is sitting on
today. That has to work this way, because the flip rule is otherwise impossible to
express: the same price cannot be permanently a ceiling and also become a floor.

Ageing was a deliberate decision rather than an accident. Three touches spread over two
years and three touches inside a fortnight both count, but only inside a lookback
window, and each level carries a recency score so the screens downstream can prefer the
fresh one. Dropping the old level entirely would throw away real information; treating
the two as identical would let a level nobody has tested since 2024 clutter the digest.

Pure functions only. Nothing in here fetches, prints or stores anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import swing_points

SUPPORT = "support"
RESISTANCE = "resistance"
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Level:
    """One price zone the market has respected, and the evidence for it.

    `kind` is deliberately empty until `classify_levels` runs, because it is not a
    property of the level at all. It is a property of the level's relationship to
    today's price, and today's price is not this function's business.
    """

    price: float
    touches: int
    first_touch: date
    last_touch: date
    kind: str = UNCLASSIFIED
    flipped: bool = False
    recency: float = 0.0

    def describe(self) -> str:
        """The reasoning, in the form it will appear in the digest."""
        freshness = f"recency {self.recency:.2f}"
        flip = ", recently broken and flipped" if self.flipped else ""
        return (
            f"{self.kind} at {self.price:.2f} from {self.touches} touches "
            f"between {self.first_touch} and {self.last_touch} ({freshness}){flip}"
        )


def find_levels(df: pd.DataFrame, cfg: Config) -> tuple[Level, ...]:
    """Cluster recent swing points into levels that clear the three-touch rule.

    Returns levels sorted by price, ascending, each still unclassified.
    """
    touches = _recent_touches(df, cfg)
    if len(touches) < cfg.level_min_touches:
        return ()

    levels = [
        _build_level(cluster, df, cfg)
        for cluster in _cluster_by_price(touches, cfg.level_tolerance_pct)
        if len(cluster) >= cfg.level_min_touches
    ]
    return tuple(sorted(levels, key=lambda lv: lv.price))


def classify_levels(levels: tuple[Level, ...], df: pd.DataFrame, cfg: Config) -> tuple[Level, ...]:
    """Mark each level as support or resistance, and flag the ones just broken.

    Returns new `Level` objects. The ones passed in are frozen and stay untouched, so a
    caller can hold on to the unclassified set and re-classify against a different bar
    later, which the backtest will need.
    """
    if not levels or df.empty:
        return ()

    close = float(df["close"].iloc[-1])
    # The close from `level_break_lookback` sessions ago. If a level sits between that
    # price and today's, price has crossed it inside the window.
    back = min(cfg.level_break_lookback, len(df) - 1)
    earlier = float(df["close"].iloc[-1 - back])

    out = []
    for level in levels:
        kind = SUPPORT if level.price <= close else RESISTANCE
        crossed = (earlier < level.price <= close) or (earlier > level.price >= close)
        out.append(replace(level, kind=kind, flipped=crossed))
    return tuple(out)


# Everything below is internal. Split out because each piece is one idea, and a
# function that clusters is far easier to reason about than a loop buried inside a
# function that also filters, dates and scores.


def _recent_touches(df: pd.DataFrame, cfg: Config) -> list[tuple[pd.Timestamp, float]]:
    """Every swing high and swing low inside the lookback window, as (date, price).

    Highs and lows are pooled on purpose. See the module docstring.
    """
    if df.empty or len(df) < 2 * cfg.level_swing_lookback + 1:
        return []

    highs, lows = swing_points(df["high"], df["low"], cfg.level_swing_lookback)
    cutoff = df.index[-min(cfg.level_lookback_days, len(df))]

    pooled: list[tuple[pd.Timestamp, float]] = []
    for series, take_highest in ((highs, True), (lows, False)):
        collapsed = _collapse_runs(series, df.index, take_highest)
        pooled.extend((stamp, price) for stamp, price in collapsed if stamp >= cutoff)
    # Sorting by price is what makes the single pass in `_cluster_by_price` correct.
    pooled.sort(key=lambda pair: pair[1])
    return pooled


def _collapse_runs(
    series: pd.Series, index: pd.DatetimeIndex, take_highest: bool
) -> list[tuple[pd.Timestamp, float]]:
    """Reduce a run of adjacent swing bars to the single bar that defines it.

    `swing_points` compares with `==`, so a stretch of equal or near equal bars marks
    every one of them as a pivot. On a chart that goes sideways for a month that is
    thirty "touches" of the same price on consecutive days, which would clear the
    three-touch rule on its own and turn any flat patch into a level.

    The rulebook means three separate occasions, not three days in a row. So a run of
    consecutive bars collapses to one touch: the highest bar of the run for swing
    highs, the lowest for swing lows.
    """
    if series.empty:
        return []

    positions = index.get_indexer(series.index)
    out: list[tuple[pd.Timestamp, float]] = []
    run: list[tuple[pd.Timestamp, float]] = []
    previous = None

    for position, (stamp, price) in zip(positions, series.items(), strict=True):
        if previous is not None and position != previous + 1:
            out.append(_pick(run, take_highest))
            run = []
        run.append((stamp, float(price)))
        previous = position
    out.append(_pick(run, take_highest))
    return out


def _pick(run: list[tuple[pd.Timestamp, float]], take_highest: bool) -> tuple[pd.Timestamp, float]:
    chooser = max if take_highest else min
    return chooser(run, key=lambda pair: pair[1])


def _cluster_by_price(
    touches: list[tuple[pd.Timestamp, float]], tolerance_pct: float
) -> list[list[tuple[pd.Timestamp, float]]]:
    """Walk price-sorted touches, extending a cluster while each one is close enough.

    The comparison is against the cluster's running mean rather than its first member.
    That is what stops a long chain of prices each 0.9 percent above the last from
    quietly walking a "one percent" level ten percent up the chart: the mean moves with
    the cluster, so a drifting sequence breaks itself into separate levels.
    """
    if not touches:
        return []

    clusters: list[list[tuple[pd.Timestamp, float]]] = [[touches[0]]]
    running_total = touches[0][1]

    for stamp, price in touches[1:]:
        current = clusters[-1]
        mean = running_total / len(current)
        within = mean > 0 and abs(price - mean) / mean * 100.0 <= tolerance_pct
        if within:
            current.append((stamp, price))
            running_total += price
        else:
            clusters.append([(stamp, price)])
            running_total = price
    return clusters


def _build_level(
    cluster: list[tuple[pd.Timestamp, float]],
    df: pd.DataFrame,
    cfg: Config,
) -> Level:
    stamps = sorted(stamp for stamp, _ in cluster)
    prices = [price for _, price in cluster]
    return Level(
        price=sum(prices) / len(prices),
        touches=len(cluster),
        first_touch=stamps[0].date(),
        last_touch=stamps[-1].date(),
        recency=_recency(stamps[-1], df, cfg),
    )


def _recency(last_touch: pd.Timestamp, df: pd.DataFrame, cfg: Config) -> float:
    """1.0 for a level touched recently, decaying in a straight line to 0.0 at the window edge.

    Age is counted in sessions rather than calendar days, because a market that was shut
    for a fortnight has not made a level any staler.
    """
    age = len(df) - 1 - df.index.get_loc(last_touch)
    if age <= cfg.level_fresh_days:
        return 1.0
    if age >= cfg.level_lookback_days:
        return 0.0
    span = cfg.level_lookback_days - cfg.level_fresh_days
    return round(1.0 - (age - cfg.level_fresh_days) / span, 4)
