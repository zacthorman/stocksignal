"""Measure the numbers that are currently guesses.

Two of the thresholds in `Config` were set by eye rather than by measurement:
`min_sma_gap_pct` and `sma_gap_strong_pct`. They were originally tuned against a
10/20 SMA pair, and the real setup is 9 and 180, which separates far wider. This
script looks at what the gap actually does on real price history so those two
numbers can be set from evidence.

It also prints each ticker's beta, because the course's scan filter wants beta of
at least 2 and nothing in the project computes it at scan time yet. Seeing the
real numbers is the fastest way to find out whether that filter leaves you with a
watchlist at all.

What this does NOT do: tell you which gap predicts a profitable trade. That is a
question about forward returns and it belongs to the backtest. All this measures
is the distribution, which is enough to stop the screen either passing everything
or passing nothing.

Run it:

    PYTHONPATH=src python scripts/calibrate.py --watchlist data/watchlist.txt

Add --offline to run against synthetic data, which proves the script works
without touching the network but tells you nothing about the market.
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.data import DataError, get_source
from stocksignal.indicators import beta, sma
from stocksignal.levels import find_levels

# Enough bars for a 180 SMA to be defined with years of readings after it.
HISTORY_DAYS = 1500

# Percentiles reported for the gap. The floor and the ceiling are picked from
# these, but which percentile to pick is a judgement call, not a fact, so all of
# them get printed rather than just the two the script would choose.
PERCENTILES = (5, 10, 25, 50, 75, 90, 95, 99)


def read_watchlist(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return [s.strip().upper() for line in lines if (s := line.split("#")[0].strip())]


def qualifying_gaps(df: pd.DataFrame, cfg: Config) -> pd.Series:
    """Gap readings on the bars the trend screen would actually be scoring.

    The threshold only ever gets applied to bars that already cleared the
    screen's other conditions, so measuring the gap across every bar in history
    would describe a population the number is never used on. Downtrends would
    drag the distribution negative and make any percentile taken from it
    meaningless.
    """
    fast = sma(df["close"], cfg.sma_fast)
    slow = sma(df["close"], cfg.sma_slow)
    close = df["close"]

    qualifies = (fast > slow) & (close > fast) & (close > slow)
    gap = (fast - slow) / slow * 100.0
    return gap[qualifies].dropna()


def describe(name: str, values: list[float]) -> None:
    if not values:
        print(f"  {name}: no readings")
        return
    series = pd.Series(values)
    print(f"  {name}: n={len(values):,}")
    cuts = " ".join(f"p{p}={series.quantile(p / 100):.2f}%" for p in PERCENTILES)
    print(f"    {cuts}")
    print(f"    mean={series.mean():.2f}%  max={series.max():.2f}%")


# Candidate windows for `level_break_lookback`, in sessions.
BREAK_WINDOWS = (3, 5, 10, 15, 20, 30, 60)


def break_positions(df: pd.DataFrame, cfg: Config) -> list[int]:
    """Bar positions where price closed above a three-touch resistance it was under.

    Uses the same crossing test as `breakout.py`: the previous close at or below
    the level, this close above it. Levels come from `find_levels`, so this is
    measuring the same object the screen measures.
    """
    levels = find_levels(df, cfg)
    if not levels:
        return []

    closes = df["close"].to_numpy()
    previous, current = closes[:-1], closes[1:]
    hits: set[int] = set()
    for level in levels:
        crossed = (previous <= level.price) & (level.price < current)
        hits.update((np.flatnonzero(crossed) + 1).tolist())
    return sorted(hits)


def report_break_recency(frames: dict[str, pd.DataFrame], cfg: Config) -> None:
    """How much breakout supply each candidate `level_break_lookback` would give.

    THE QUESTION THIS ANSWERS, and the one it does not. A percentile of
    "sessions since the last break" would be the wrong measurement: that
    distribution is dominated by ancient breaks, and an ancient break is not a
    trade. The decision-relevant number is supply. On what share of days does a
    ticker have a break inside the last W sessions, and therefore how many live
    candidates would a scan over this universe surface at each W?

    HONESTY WARNING, because this is a rough sizing rather than a backtest.
    Levels are computed once from the whole history, then breaks of those levels
    are located across that same history. A level confirmed by touches in 2026
    was not known in 2023, so this is mild lookahead. It is fine for choosing an
    order of magnitude for a window and worthless as evidence that any window
    makes money. Session 4 answers the second question; this only answers the
    first.
    """
    print("\n=== BREAKOUT SUPPLY by level_break_lookback ===")
    print(
        "  Rough sizing only: levels are found using the full history, so this\n"
        "  overstates what was knowable at the time. Use it to pick an order of\n"
        "  magnitude, not to justify a number.\n"
    )

    per_window: dict[int, float] = dict.fromkeys(BREAK_WINDOWS, 0.0)
    gaps_between: list[int] = []
    total_breaks = 0
    counted = 0

    for df in frames.values():
        positions = break_positions(df, cfg)
        if len(df) < 2:
            continue
        counted += 1
        total_breaks += len(positions)
        gaps_between.extend(positions[i] - positions[i - 1] for i in range(1, len(positions)))
        # Mark the bars each break keeps "live", rather than asking every bar
        # about every break. The naive version is bars x breaks x windows, which
        # is about a billion operations over 256 tickers and six years.
        for window in BREAK_WINDOWS:
            live = np.zeros(len(df), dtype=bool)
            for pos in positions:
                live[pos : min(pos + window, len(df))] = True
            per_window[window] += float(live.sum()) / len(df)

    if not counted:
        print("  no usable frames")
        return

    years = HISTORY_DAYS / 252
    print(f"  {total_breaks:,} breaks across {counted} tickers")
    print(f"  {total_breaks / counted / years:.1f} breaks per ticker per year\n")
    print(f"  {'window':>8}{'% of days live':>17}{'expected candidates':>22}")
    for window in BREAK_WINDOWS:
        share = per_window[window] / counted
        marker = "  <- current" if window == cfg.level_break_lookback else ""
        print(f"  {window:>6}d{share * 100:>16.1f}%{share * counted:>21.1f}{marker}")

    print(
        "\n  'Expected candidates' is how many of these tickers would have a live\n"
        "  break on an average day, BEFORE the volume, ignition, wick and\n"
        "  follow-through gates thin it further. The real scan on 2026-08-10\n"
        "  produced 3 breakout signals, so read these as a ceiling."
    )
    if gaps_between:
        median_gap = int(pd.Series(gaps_between).median())
        print(f"\n  Median sessions between consecutive breaks on a ticker: {median_gap}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", type=Path, default=Path("data/watchlist.txt"))
    parser.add_argument("--offline", action="store_true", help="Synthetic data, proves nothing")
    parser.add_argument("--benchmark", default=DEFAULT_CONFIG.beta_benchmark)
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print every ticker rather than a summary. 256 tickers is 512 lines.",
    )
    args = parser.parse_args()

    cfg = DEFAULT_CONFIG
    tickers = read_watchlist(args.watchlist)
    source = get_source(offline=args.offline)

    print(f"SMA pair: {cfg.sma_fast} against {cfg.sma_slow}")
    print(f"Tickers: {len(tickers)}  History: {HISTORY_DAYS} sessions  Offline: {args.offline}\n")

    try:
        bench = source.history(args.benchmark, days=HISTORY_DAYS)
    except DataError as exc:
        print(f"Benchmark {args.benchmark} failed: {exc}")
        return 1

    all_gaps: list[float] = []
    per_ticker: dict[str, tuple[int, float, float | None]] = {}
    frames: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        try:
            df = source.history(ticker, days=HISTORY_DAYS)
        except DataError as exc:
            print(f"  {ticker}: skipped, {exc}")
            continue

        frames[ticker] = df
        gaps = qualifying_gaps(df, cfg)
        all_gaps.extend(float(g) for g in gaps)
        b = beta(df["close"], bench["close"], window=cfg.beta_window)
        share = len(gaps) / len(df) * 100 if len(df) else 0.0
        per_ticker[ticker] = (len(gaps), share, b)

    ranked = sorted(per_ticker.items(), key=lambda kv: (kv[1][2] is None, -(kv[1][2] or 0)))
    print("\n=== BETA against", args.benchmark, f"({cfg.beta_window}-session window) ===")
    print(f"  Filter is beta >= {cfg.min_beta}")
    known = [b for _, (_, _, b) in ranked if b is not None]
    clears = sum(1 for b in known if b >= cfg.min_beta)
    if args.verbose:
        print()
        for ticker, (_, _, b) in ranked:
            if b is None:
                print(f"  {ticker:<6} unknown")
            else:
                print(f"  {ticker:<6} {b:5.2f}  {'PASS' if b >= cfg.min_beta else 'fail'}")
    elif known:
        show = 5
        print("\n  highest: " + ", ".join(f"{t} {b:.2f}" for t, (_, _, b) in ranked[:show]))
        passing = [kv for kv in ranked if kv[1][2] is not None and kv[1][2] >= cfg.min_beta]
        print("  lowest passing: " + ", ".join(f"{t} {b:.2f}" for t, (_, _, b) in passing[-show:]))
        print(f"  median {pd.Series(known).median():.2f}, run with -v for all of them")
    print(f"\n  {clears} of {len(per_ticker)} clear the beta floor.")
    if clears == len(per_ticker) and len(per_ticker) > 20:
        print(
            "  Note: all of them pass because build_watchlist.py selected them with\n"
            "  this same filter. That is a consistency check, not a finding."
        )

    print("\n=== SMA GAP on bars the trend screen would score ===")
    describe("all tickers pooled", all_gaps)

    shares = sorted(per_ticker.items(), key=lambda kv: -kv[1][1])
    print("\n  Share of history each ticker spends in a qualifying uptrend:")
    if args.verbose:
        for ticker, (n, share, _) in shares:
            print(f"    {ticker:<6} {n:>5} bars  {share:5.1f}% of history")
    else:
        pcts = [share for _, (_, share, _) in shares]
        median = pd.Series(pcts).median()
        print(f"    median {median:.1f}%, range {min(pcts):.1f}% to {max(pcts):.1f}%")
        print("    most:  " + ", ".join(f"{t} {s:.0f}%" for t, (_, s, _) in shares[:5]))
        never = [t for t, (n, _, _) in shares if n == 0]
        if never:
            print(
                f"    never qualified in the whole window: {', '.join(never)}\n"
                "    (these can never fire the trend screen, they just occupy a slot)"
            )

    if all_gaps:
        pooled = pd.Series(all_gaps)
        p10 = pooled.quantile(0.10)
        p25 = pooled.quantile(0.25)
        strong = pooled.quantile(0.90)
        print("\n=== SUGGESTION ===")
        print(f"  min_sma_gap_pct    = {p10:.1f}   (10th percentile)  <- what config uses")
        print(f"                       {p25:.1f}   (25th percentile)  <- the stricter option")
        print(f"  sma_gap_strong_pct = {strong:.1f}   (90th percentile)")
        print(
            "\n  Which floor, and why config takes the 10th rather than the 25th.\n"
            "  The floor exists to reject a fast average sitting a HAIR above a slow one,\n"
            "  which is chop wearing a trend's clothing. The 10th percentile is a hair.\n"
            "  The 25th is a real if unremarkable trend, so drawing the line there throws\n"
            "  away setups the screen was built to find. Take the 25th only if you have\n"
            "  decided you want a stricter screen, and record that you decided it: moving\n"
            "  a threshold because the last run produced too many rows is how a screen\n"
            "  gets fitted to a mood.\n\n"
            "  The ceiling is meant to be reachable but rare, so the 90th percentile means\n"
            "  roughly one qualifying bar in ten scores a full 1.0.\n\n"
            "  All three are conventions. None is evidence that a level predicts a good\n"
            "  trade, which is a question about forward returns and belongs to the backtest."
        )
        print(f"\n  Currently in config: {cfg.min_sma_gap_pct} and {cfg.sma_gap_strong_pct}")
        print(f"  Median qualifying gap is {statistics.median(all_gaps):.2f}%.")

    report_break_recency(frames, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
