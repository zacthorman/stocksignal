"""Add symbols to the frozen CSV cache. Run this yourself, it needs your keys.

WHY YOU HAVE TO RUN IT RATHER THAN ME. The cache is written by a live Alpaca
fetch. Your Alpaca credentials live in your shell environment on your Mac, and
neither of the machines Claude can reach has both the credentials and a network
connection at the same time. So the fetch is yours. Everything after it is not.

USAGE

    cd path/to/project-1-stocksignal
    source .venv/bin/activate
    python scripts/fetch_cache.py UVXY JNUG SPXL TQQQ

Symbols already present are skipped unless you pass --force. SPY is required by
every backtest in this project as the beta and comparison benchmark, and it is
already in the cache, so you do not need to re-pull it.

WHAT IT WRITES. `cache/{SYMBOL}_1500d.csv` with columns Date, open, high, low,
close, volume, indexed by date, exactly matching the files already there. 1500
sessions is about six years, which is what the existing snapshot covers. Nothing
else in the cache is touched.

A WARNING THAT MATTERS MORE FOR ETFS THAN FOR STOCKS. Leveraged and volatility
products decay. A 2x fund does not return 2x the index over any period longer
than a day, and a VIX futures product bleeds through contango whether or not it
is leveraged. Six years of daily bars on UVXY is a real price series and a
backtest on it is a real backtest, but the instrument itself is not a stock and
the rulebook was not written for one. Nothing in this script fixes that, and
nothing in the course addresses it either.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")

DAYS = 1500
CACHE = Path("cache")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="Tickers to fetch, e.g. UVXY JNUG")
    parser.add_argument("--force", action="store_true", help="Refetch symbols already cached")
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    if not (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY")):
        print(
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are not set in this shell.\n"
            "Export them and run again. They are the same two you just put into\n"
            "the repository's Actions secrets.",
            file=sys.stderr,
        )
        return 2

    from stocksignal.sources.alpaca import AlpacaSource

    CACHE.mkdir(exist_ok=True)
    source = AlpacaSource()
    failures = []

    for symbol in [s.strip().upper() for s in args.symbols]:
        path = CACHE / f"{symbol}_{args.days}d.csv"
        if path.exists() and not args.force:
            print(f"{symbol:>6}: already cached, skipping")
            continue
        try:
            df = source.history(symbol, days=args.days)
        except Exception as exc:  # noqa: BLE001 - report and continue, one bad symbol is not fatal
            print(f"{symbol:>6}: FAILED, {exc}")
            failures.append(symbol)
            continue
        if df is None or df.empty:
            print(f"{symbol:>6}: FAILED, no bars returned")
            failures.append(symbol)
            continue
        df = df[["open", "high", "low", "close", "volume"]]
        df.index.name = "Date"
        df.to_csv(path)
        print(f"{symbol:>6}: {len(df):>5} bars, {df.index[0].date()} to {df.index[-1].date()}")

    if failures:
        print(f"\nfailed: {', '.join(failures)}")
        print("A delisted or terminated symbol returns nothing. TVIX is one of those.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
