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

import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.data import DataError, get_source
from stocksignal.indicators import beta, sma

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", type=Path, default=Path("data/watchlist.txt"))
    parser.add_argument("--offline", action="store_true", help="Synthetic data, proves nothing")
    parser.add_argument("--benchmark", default=DEFAULT_CONFIG.beta_benchmark)
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

    for ticker in tickers:
        try:
            df = source.history(ticker, days=HISTORY_DAYS)
        except DataError as exc:
            print(f"  {ticker}: skipped, {exc}")
            continue

        gaps = qualifying_gaps(df, cfg)
        all_gaps.extend(float(g) for g in gaps)
        b = beta(df["close"], bench["close"], window=cfg.beta_window)
        share = len(gaps) / len(df) * 100 if len(df) else 0.0
        per_ticker[ticker] = (len(gaps), share, b)

    print("\n=== BETA against", args.benchmark, f"({cfg.beta_window}-session window) ===")
    print(f"  Filter is beta >= {cfg.min_beta}\n")
    clears = 0
    for ticker, (_, _, b) in sorted(
        per_ticker.items(), key=lambda kv: (kv[1][2] is None, -(kv[1][2] or 0))
    ):
        if b is None:
            print(f"  {ticker:<6} unknown")
            continue
        verdict = "PASS" if b >= cfg.min_beta else "fail"
        clears += b >= cfg.min_beta
        print(f"  {ticker:<6} {b:5.2f}  {verdict}")
    print(f"\n  {clears} of {len(per_ticker)} clear the beta floor.")

    print("\n=== SMA GAP on bars the trend screen would score ===")
    describe("all tickers pooled", all_gaps)

    print("\n  Per ticker, share of all bars that qualify at all:")
    for ticker, (n, share, _) in sorted(per_ticker.items(), key=lambda kv: -kv[1][1]):
        print(f"    {ticker:<6} {n:>5} bars  {share:5.1f}% of history")

    if all_gaps:
        pooled = pd.Series(all_gaps)
        floor = pooled.quantile(0.25)
        strong = pooled.quantile(0.90)
        print("\n=== SUGGESTION ===")
        print(f"  min_sma_gap_pct   = {floor:.1f}   (25th percentile)")
        print(f"  sma_gap_strong_pct = {strong:.1f}   (90th percentile)")
        print(
            "\n  Reasoning, so you can disagree with it: the floor is meant to cut chop,\n"
            "  so the bottom quarter of qualifying bars is a defensible place to draw it.\n"
            "  The ceiling is meant to be reachable but rare, so the 90th percentile means\n"
            "  roughly one qualifying bar in ten scores a full 1.0. Both are conventions.\n"
            "  What they are NOT is evidence that either level predicts a good trade."
        )
        print(f"\n  Currently in config: {cfg.min_sma_gap_pct} and {cfg.sma_gap_strong_pct}")
        print(f"  Median qualifying gap is {statistics.median(all_gaps):.2f}%.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
