"""Let the course's own filters build the watchlist instead of picking names by hand.

The three filters are from page 142: price at least 15 dollars, average volume at
least 100k, beta at least 2 against the benchmark. Point this at the full list of
US listed symbols and whatever survives is, by definition, the universe the
strategy was written for.

Why this exists. The scaffold shipped a 19-ticker watchlist of index funds and
megacaps. Measured on 2026-08-10, four of those nineteen cleared beta 2, and one
of the four failed the price floor. The watchlist and the strategy disagreed
about what a tradeable stock is, and the strategy is the one with a rulebook
behind it.

    PYTHONPATH=src python scripts/build_watchlist.py --limit 500
    PYTHONPATH=src python scripts/build_watchlist.py --limit 500 --write

Without --write it prints what it would do and touches nothing.

ON RATE LIMITING, corrected 2026-08-10 after the first full-market run got
throttled roughly every six chunks.

The original version of this file claimed `yf.download` with a list of tickers is
"roughly one request per chunk". That is false. `yf.download` is a convenience
wrapper that fetches each ticker separately and concatenates the results, and
with `threads=True` it fires them concurrently. A chunk of 100 was therefore up
to 100 simultaneous requests, and the polite 1.5 second pause was between bursts
rather than between requests. It was a burst generator with a nap.

What it does now: serialises the fetch, pauses between chunks, and retries a
throttled chunk with exponential backoff instead of losing it. Successful chunks
are cached and empty ones are not, so a throttled run can simply be run again and
it resumes where it stopped.

None of that changes the real conclusion. yfinance costs one request per ticker
however you dress it up, so a whole-market screen is thousands of requests and
will be throttled. It is survivable for a job run monthly with a cache. It is the
wrong tool for a daily scan over hundreds of names, which wants a provider with
either true multi-symbol requests (Alpaca) or grouped daily bars, one call for
the whole market (Massive). See the PriceSource protocol in data.py: that swap is
a new class, not a rewrite.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.indicators import beta

# Nasdaq publishes these. Official, free, no key, no account, no scraping.
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

# Smaller chunks and a longer pause than the first version, which was throttled
# roughly every sixth chunk. Both are overridable from the command line, because
# the right values depend on how recently the provider has been annoyed with you.
CHUNK_SIZE = 40
CHUNK_PAUSE_SECONDS = 4.0
RETRY_ATTEMPTS = 4
PERIOD = "2y"  # Comfortably clears the 252-session beta window.
CACHE = Path("cache/universe")


def fetch_symbol_directory(exclude_etfs: bool) -> pd.DataFrame:
    """Every US listed symbol, with the junk stripped out.

    Warrants, units, preferred shares and rights all trade under symbols with a
    dot or a dollar sign in them. They are not what the rulebook means by a
    stock, and yfinance will not resolve most of them anyway.
    """
    frames = []
    for url, symbol_col in ((NASDAQ_LISTED, "Symbol"), (OTHER_LISTED, "ACT Symbol")):
        raw = pd.read_csv(url, sep="|")
        raw = raw[raw[symbol_col].notna()]
        # Both files end with a "File Creation Time" line that is not a symbol.
        raw = raw[~raw[symbol_col].str.contains("File Creation Time", na=False)]
        raw = raw.rename(columns={symbol_col: "symbol"})
        keep = ["symbol", "Security Name"]
        if "ETF" in raw.columns:
            keep.append("ETF")
        if "Test Issue" in raw.columns:
            keep.append("Test Issue")
        frames.append(raw[keep])

    df = pd.concat(frames, ignore_index=True)
    if "Test Issue" in df.columns:
        df = df[df["Test Issue"] != "Y"]
    if exclude_etfs and "ETF" in df.columns:
        df = df[df["ETF"] != "Y"]

    df = df[~df["symbol"].str.contains(r"[$.]", na=False, regex=True)]
    df = df.drop_duplicates(subset="symbol").sort_values("symbol")
    return df.reset_index(drop=True)


def download_chunk(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch one chunk. Returns only the symbols that came back with data.

    `threads=False` is deliberate and it is the whole fix. Threaded, yfinance
    fires every ticker in the chunk at once, which is what got this throttled.
    Serial is slower per chunk and finishes sooner overall, because it does not
    spend half the run backing off.
    """
    import yfinance as yf

    raw = yf.download(
        tickers=symbols,
        period=PERIOD,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        threads=False,
        progress=False,
    )

    return {s: f for s in symbols if (f := extract_frame(raw, s)) is not None}


def download_with_retry(symbols: list[str], pause: float) -> dict[str, pd.DataFrame]:
    """Retry a throttled chunk with exponential backoff rather than losing it.

    A rate limit is a "come back later", not a fact about the symbols. Treating
    it as failure is how a run silently returns a smaller universe than the
    market actually has, which then looks like a finding rather than a fault.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            got = download_chunk(symbols)
            if got:
                return got
            reason = "empty response"
        except Exception as exc:  # noqa: BLE001 - provider errors are all the same here
            reason = f"{type(exc).__name__}: {exc}"

        if attempt == RETRY_ATTEMPTS:
            print(f"    gave up after {RETRY_ATTEMPTS} attempts ({reason})")
            return {}

        backoff = pause * (2**attempt)
        print(f"    attempt {attempt} failed ({reason}), waiting {backoff:.0f}s")
        time.sleep(backoff)
    return {}


def extract_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    """Pull one symbol's bars out of whatever shape yfinance handed back.

    This is the thing that broke on the first real run. A multi-symbol download
    returns MultiIndex columns of (ticker, field), so the ticker is the outer
    key. A single-symbol download returns plain columns, no ticker level at all.
    The first version keyed off `len(symbols)` to decide which it was, which is
    a guess about the response based on the request, and it was wrong for the
    one-symbol benchmark fetch: the benchmark came back empty and the whole run
    stopped with "SPY unavailable".

    Ask the frame what shape it is instead of predicting it.
    """
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return None
        frame = raw[symbol]
    else:
        frame = raw

    frame = frame.dropna(how="all")
    frame = frame.rename(columns=str.lower)
    if frame.empty or "close" not in frame.columns or "volume" not in frame.columns:
        return None
    return frame


def chunk_cache_path(chunk: list[str]) -> Path:
    """Name a cache file after what is in it, not after where it sat in a loop.

    The first version keyed on position and length, `chunk_0001_100.pkl`. That is
    only safe while the symbol list never changes. Change how symbols are
    selected and chunk 1 holds different tickers under the same filename, so the
    next run silently loads someone else's data and the whole screen is quietly
    wrong. Hashing the contents makes a different chunk a different file, and a
    changed PERIOD invalidates everything, which is what you want.
    """
    key = f"{PERIOD}:" + ",".join(sorted(chunk))
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE / f"chunk_{len(chunk):04d}_{digest}.pkl"


def load_universe(
    symbols: list[str],
    use_cache: bool,
    chunk_size: int = CHUNK_SIZE,
    pause: float = CHUNK_PAUSE_SECONDS,
) -> tuple[dict[str, pd.DataFrame], int]:
    """Download every symbol in chunks. Returns the frames and the failed-chunk count.

    Failures are counted and reported rather than swallowed, because a run that
    quietly loses ten chunks produces a universe that looks like an answer.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    chunks = [symbols[i : i + chunk_size] for i in range(0, len(symbols), chunk_size)]
    failed = 0

    for n, chunk in enumerate(chunks, start=1):
        path = chunk_cache_path(chunk)
        if use_cache and path.exists():
            frames.update(pd.read_pickle(path))
            print(f"  chunk {n}/{len(chunks)}: from cache")
            continue

        got = download_with_retry(chunk, pause)
        frames.update(got)
        # An empty result is a failed request, not a fact about the market, and
        # caching it would make the failure permanent until someone thought to
        # clear the cache by hand.
        if got:
            pd.to_pickle(got, path)
        else:
            failed += 1
        print(f"  chunk {n}/{len(chunks)}: {len(got)}/{len(chunk)} symbols returned")
        if n < len(chunks):
            time.sleep(pause)

    return frames, failed


def apply_filters(
    frames: dict[str, pd.DataFrame],
    benchmark: pd.Series,
    cfg: Config,
) -> tuple[list[dict], dict[str, int]]:
    """The three course filters, in the cheapest-first order.

    Price and volume are one lookup each. Beta needs a covariance over a year of
    returns, so it goes last and only runs on what already survived.
    """
    survivors: list[dict] = []
    cut = {"no data": 0, "price": 0, "volume": 0, "beta unknown": 0, "beta": 0}

    for symbol, df in frames.items():
        if df.empty or len(df) < cfg.beta_window:
            cut["no data"] += 1
            continue

        price = float(df["close"].iloc[-1])
        if price < cfg.min_price:
            cut["price"] += 1
            continue

        avg_volume = float(df["volume"].tail(cfg.avg_volume_window).mean())
        if avg_volume < cfg.min_avg_volume:
            cut["volume"] += 1
            continue

        b = beta(df["close"], benchmark, window=cfg.beta_window)
        if b is None:
            cut["beta unknown"] += 1
            continue
        if b < cfg.min_beta:
            cut["beta"] += 1
            continue

        survivors.append({"symbol": symbol, "price": price, "avg_volume": avg_volume, "beta": b})

    survivors.sort(key=lambda r: r["beta"], reverse=True)
    return survivors, cut


def render(survivors: list[dict], cfg: Config, scanned: int) -> str:
    lines = [
        "# Built by scripts/build_watchlist.py. Do not hand-edit, rerun it.",
        "#",
        "# Every symbol below cleared the course's page 142 scan filters:",
        f"#   price >= {cfg.min_price:g}, avg volume >= {cfg.min_avg_volume:,.0f}, "
        f"beta >= {cfg.min_beta:g} vs {cfg.beta_benchmark}",
        f"# {len(survivors)} survivors from {scanned} symbols screened.",
        "#",
        "# Beta decays as a stock's character changes, so this list goes stale.",
        "# Rebuild it monthly rather than trusting it forever.",
        "",
    ]
    for row in survivors:
        lines.append(
            f"{row['symbol']:<8}# beta {row['beta']:.2f}  "
            f"${row['price']:,.2f}  vol {row['avg_volume']:,.0f}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500, help="Symbols to screen, 0 for all")
    parser.add_argument("--out", type=Path, default=Path("data/watchlist.txt"))
    parser.add_argument("--write", action="store_true", help="Actually overwrite the watchlist")
    parser.add_argument("--include-etfs", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--chunk-size", type=int, default=CHUNK_SIZE, help="Symbols per request batch"
    )
    parser.add_argument(
        "--pause", type=float, default=CHUNK_PAUSE_SECONDS, help="Seconds between chunks"
    )
    args = parser.parse_args()

    cfg = DEFAULT_CONFIG

    print("Fetching the US symbol directory from Nasdaq...")
    directory = fetch_symbol_directory(exclude_etfs=not args.include_etfs)
    symbols = directory["symbol"].tolist()
    if args.limit and args.limit < len(symbols):
        # Evenly spaced through the alphabet rather than the first N. Taking the
        # head would have screened only A and B tickers, and "how much of the
        # market clears beta 2" is not a question you can answer from the front
        # of the alphabet. Deterministic, so reruns hit the same cache.
        step = len(symbols) / args.limit
        symbols = [symbols[int(i * step)] for i in range(args.limit)]
        print(f"  {len(directory):,} symbols listed, sampling {len(symbols):,} across the range\n")
    else:
        print(f"  {len(directory):,} symbols listed, screening all of them\n")

    print(
        f"Downloading {PERIOD} of daily bars, {args.chunk_size} per batch, "
        f"{args.pause:g}s between batches..."
    )
    frames, failed = load_universe(symbols, not args.no_cache, args.chunk_size, args.pause)
    print(f"  {len(frames):,} symbols returned usable data")
    if failed:
        print(
            f"  {failed} chunk(s) failed even after retries, so this run is missing data.\n"
            "  Everything that did succeed is cached. Rerun the same command later and\n"
            "  it will only refetch the chunks that failed."
        )
    print()

    print(f"Fetching the {cfg.beta_benchmark} benchmark...")
    bench_frames, _ = load_universe(
        [cfg.beta_benchmark], not args.no_cache, args.chunk_size, args.pause
    )
    if cfg.beta_benchmark not in bench_frames:
        print(
            f"\nBenchmark {cfg.beta_benchmark} came back empty, so beta cannot be computed\n"
            "and there is no point continuing. Usually the provider throttling you.\n"
            "Wait a few minutes and rerun: the 500 symbols above are cached, so the\n"
            "retry only costs the one request."
        )
        return 1
    benchmark = bench_frames[cfg.beta_benchmark]["close"]

    survivors, cut = apply_filters(frames, benchmark, cfg)

    print("=== WHAT THE FILTERS REMOVED ===")
    for reason, n in cut.items():
        print(f"  {reason:<14} {n:>6,}")
    print(f"  {'SURVIVED':<14} {len(survivors):>6,}\n")

    print("=== TOP 40 BY BETA ===")
    for row in survivors[:40]:
        print(
            f"  {row['symbol']:<8} beta {row['beta']:5.2f}  "
            f"${row['price']:>9,.2f}  vol {row['avg_volume']:>14,.0f}"
        )

    if not survivors:
        print("\nNothing survived. Widen --limit before concluding anything.")
        return 1

    content = render(survivors, cfg, len(frames))
    if args.write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content)
        print(f"\nWrote {len(survivors)} symbols to {args.out}")
    else:
        print(f"\nDry run. {len(survivors)} symbols would go to {args.out}. Add --write.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
