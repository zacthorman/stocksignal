"""Run a backtest against the frozen CSV cache instead of a live provider.

WHY THIS EXISTS AND WHY IT IS NOT A SHORTCUT. `cli.py backtest` fetches through
`get_source`, which needs Alpaca credentials and, more importantly, re-fetches:
`YFinanceSource` expires its cache after 12 hours, so two runs a day apart are
two different datasets. For a measurement that gets written into the README and
quoted later, that is the wrong property. This script reads `cache/*_1500d.csv`
and nothing else, so a run is reproducible from a snapshot on disk and a rerun
next month answers the same question rather than a similar one.

It is also the only way to run this in an environment with no API keys, which is
where the breakout measurement was built.

The snapshot's limits, stated here rather than discovered later: these files were
written by a live fetch, so they carry the same split and dividend back
adjustment `backtest.py` documents, the same survivorship gap, and whatever
universe `data/watchlist.txt` had when they were pulled. None of that is fixed by
reading them from disk. What is fixed is that the numbers do not move under you.

Usage:
    python scripts/measure_from_cache.py --screen breakout --replicates 6000
    python scripts/measure_from_cache.py --screen breakout --count-only
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.backtest import (  # noqa: E402
    TESTS_RUN,
    breakout_mask,
    build_panel,
    render,
    run,
    trend_mask,
    universe_mask,
)
from stocksignal.backtest import _thin as thin_picks  # noqa: E402
from stocksignal.config import Config  # noqa: E402

CACHE = ROOT / "cache"
SUFFIX = "_1500d.csv"


def load_frames(benchmark_ticker: str) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(CACHE.glob(f"*{SUFFIX}")):
        ticker = path.name[: -len(SUFFIX)].upper()
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index.name = None
        frames[ticker] = df
    benchmark = frames.pop(benchmark_ticker, None)
    if benchmark is None:
        raise SystemExit(f"no {benchmark_ticker}{SUFFIX} in {CACHE}, cannot compute beta")
    return frames, benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", default="breakout", choices=("trend", "breakout"))
    parser.add_argument("--from", dest="start", default="2021-06-01")
    parser.add_argument("--to", dest="finish", default="2026-08-10")
    parser.add_argument("--fit-end", default="2023-12-31")
    parser.add_argument("--cost", type=float, default=0.2)
    parser.add_argument("--replicates", type=int, default=6000)
    parser.add_argument("--tests-run", type=int, default=TESTS_RUN)
    parser.add_argument("--exits", default="hold", choices=("hold", "stops"))
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Report how many signals and how many distinct names, and stop "
        "before any return is computed. This is the pre-registration pass: "
        "sample size is needed to state the power of the test, and it says "
        "nothing whatever about the result.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    cfg = Config(exit_rule=args.exits)
    start = date.fromisoformat(args.start)
    finish = date.fromisoformat(args.finish)
    fit_end = date.fromisoformat(args.fit_end) if args.fit_end else None

    began = time.time()
    frames, benchmark = load_frames(cfg.beta_benchmark)
    usable = {t: df for t, df in frames.items() if len(df) > cfg.required_history}
    print(
        f"{len(usable)} of {len(frames)} tickers have enough history; "
        f"benchmark {cfg.beta_benchmark} {benchmark.index[0].date()} to "
        f"{benchmark.index[-1].date()}",
        flush=True,
    )

    if args.count_only:
        panel = build_panel(usable, benchmark, cfg)
        window = (panel.dates >= pd.Timestamp(start)) & (panel.dates <= pd.Timestamp(finish))
        universe = universe_mask(panel, cfg) & window[:, None]
        if args.screen == "breakout":
            signals, _ = breakout_mask(usable, panel, cfg, universe=universe)
        else:
            signals, _ = trend_mask(panel, cfg, universe=universe)
        raw = [(int(t), int(i), 0.0) for t, i in np.argwhere(signals)]
        kept = thin_picks(raw, 20)
        after = np.asarray([t for t, _, _ in kept], dtype=int)
        held_out = (
            panel.dates[after] > pd.Timestamp(fit_end) if fit_end else np.ones(len(after), bool)
        )
        print(f"sessions in window: {int(window.sum())}")
        print(f"mean universe size per session: {universe.sum(axis=1)[window].mean():.1f}")
        print(f"raw signals: {len(raw)}")
        print(f"after 20-session thinning: {len(kept)}")
        print(f"of those, out of sample (after {fit_end}): {int(held_out.sum())}")
        print(f"distinct tickers: {len({i for _, i, _ in kept})}")
        print(f"elapsed {time.time() - began:.1f}s")
        return

    report = run(
        usable,
        benchmark,
        cfg,
        start=start,
        end=finish,
        fit_end=fit_end,
        cost_pct=args.cost,
        replicates=args.replicates,
        family_size=args.tests_run,
        screen=args.screen,
    )
    text = render(report)
    print(text)
    print(f"\nelapsed {time.time() - began:.1f}s")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"written to {args.out}")


if __name__ == "__main__":
    main()
