"""Score the watchlist and write the dashboard's data file.

Reads the project's own bar cache rather than the network, so this runs
identically offline and in CI, which is the repo's standing rule. Writes a
single JSON blob carrying every factor's READING separately from its WEIGHT, so
the dashboard can re-weight in the browser without going back for more data.

Failures are collected and printed. The first version of this script had a bare
`except Exception: continue` around the per-ticker work and silently produced
zero rows, which is the exact silent-failure mode the vault complains about in
four separate places. It does not do that any more.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stocksignal.config import DEFAULT_CONFIG as CFG  # noqa: E402
from stocksignal.scanner import build_quote  # noqa: E402
from stocksignal.scorecard import FACTORS, score_ticker, to_dict  # noqa: E402
from stocksignal.screens.tradability import screen_tradability  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)


def load_enrichment() -> dict:
    """One record per ticker from `data/fundamentals.json`, or nothing.

    Absent is the normal state until `scripts/fetch_all.py` has been run, and
    the two factors that need it abstain rather than scoring zero, so this
    degrades to exactly the behaviour that existed before EDGAR was wired in.
    """
    path = ROOT / "data" / "fundamentals.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("data", {})


def load_cache(cache_dir: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(cache_dir.glob("*_1500d.csv")):
        ticker = path.name.split("_1500d")[0].upper()
        df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.DatetimeIndex(df.index)
        frames[ticker] = df
    return frames


def read_watchlist(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(line.upper())
    return out


def main(cache_dir: Path) -> None:
    frames = load_cache(cache_dir)
    print(f"{len(frames)} cached series", flush=True)

    benchmark = frames.get(CFG.beta_benchmark)
    if benchmark is None:
        raise SystemExit(f"no {CFG.beta_benchmark} in the cache: beta cannot be computed")
    bench_close = benchmark["close"]

    watchlist = set(read_watchlist(ROOT / "data" / "watchlist.txt"))
    # ETFs and the benchmark are in the cache for other purposes. Scoring an
    # index tracker against a rulebook written for single names is a category
    # error, so anything outside the watchlist is skipped rather than scored.
    universe = [t for t in sorted(frames) if t in watchlist]
    skipped = [t for t in sorted(frames) if t not in watchlist]

    enrichment = load_enrichment()
    print(
        f"{len(enrichment)} tickers with fetched filings"
        if enrichment
        else "no filings fetched: run scripts/fetch_all.py to answer the "
        "catalyst and analyst factors"
    )

    cards, rejected, errors, thin = [], [], [], []
    for t in universe:
        df = frames[t]
        if len(df) < CFG.min_history_days:
            thin.append({"ticker": t, "bars": len(df)})
            continue
        try:
            quote = build_quote(t, df, CFG, None, bench_close)
            gate = screen_tradability(df, quote, CFG)
            if not gate.passed:
                rejected.append({"ticker": t, "why": list(gate.reasons)})
                continue
            card = to_dict(score_ticker(df, quote, CFG, enrichment.get(t)))
            card["beta"] = None if quote.beta is None else round(quote.beta, 3)
            card["avg_volume"] = round(quote.avg_volume)
            card["gate_reasons"] = list(gate.reasons)
            tail = df["close"].iloc[-252:]
            card["spark"] = [round(float(v), 2) for v in tail.iloc[::4]]
            cards.append(card)
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": t, "error": f"{type(exc).__name__}: {exc}"})
            traceback.print_exc()

    cards.sort(key=lambda c: c["score"], reverse=True)
    as_of = max((c["as_of"] for c in cards), default="")
    payload = {
        "as_of": as_of,
        "generated": pd.Timestamp.now("UTC").isoformat(),
        "source": "project bar cache",
        "universe": len(universe),
        "scored": len(cards),
        "enriched": len(enrichment),
        "rejected": rejected,
        "thin": thin,
        "errors": errors,
        "skipped_not_in_watchlist": skipped,
        "factor_specs": [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                "source": f.source,
                "weight": round(f.weight, 4),
                "question": f.question,
            }
            for f in FACTORS
        ],
        "cards": cards,
    }
    path = OUT / "scores-latest.json"
    path.write_text(json.dumps(payload))
    print(
        f"\nwrote {path}\n"
        f"  as_of={as_of} scored={len(cards)} rejected={len(rejected)} "
        f"thin={len(thin)} errors={len(errors)}"
    )
    for c in cards[:20]:
        print(f"  {c['ticker']:6s} {c['score']:6.1f}  {c['band']:14s} coverage {c['coverage']:.0%}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache")
