"""One command that fills in everything the price bars cannot answer.

    .venv/bin/python scripts/fetch_all.py --contact "Zac Thorman zdthorman@gmail.com"

Hits two providers and writes one file, `data/fundamentals.json`:

    SEC EDGAR      revenue, share count, cash flow, balance sheet, net income,
                   plus recent 424B5 and S-3 filings (dilution), Form 4 counts
                   (insider activity) and 8-K dates (catalysts)
    yfinance       analyst upgrades and downgrades, which is the one thing in
                   the journal's twelve columns that no filing carries

WHY IT IS A SEPARATE COMMAND FROM THE DAILY SCAN. Statements move four times a
year and price bars move every day. Tying the two together would refetch 255
sets of accounts every weekday to learn nothing, and would put the daily digest
at the mercy of a second provider. The workflow runs this weekly on Sundays and
the scan carries on regardless of whether it succeeded.

CACHING IS ON BY DEFAULT and matters more than it looks. A full run is about
520 EDGAR requests paced under the rate limit, so it takes a few minutes; with
the cache a rerun after a crash costs nothing. Delete `cache/edgar/` to force a
refetch.

FAILURES ARE COLLECTED, NOT RAISED. One delisted ticker or one company that has
never filed an XBRL 10-K must not take down the other 254. Everything that
failed is named in the output file and printed at the end, because a silent
partial result is the failure mode this project keeps running into.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.sources.edgar import EdgarClient, EdgarError, extract  # noqa: E402

CACHE = ROOT / "cache" / "edgar"


def read_watchlist(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.append(line.upper())
    return out


def cached(name: str, fetch, use_cache: bool):
    """Disk cache keyed by name. Returns the payload, or raises what fetch raised."""
    path = CACHE / f"{name}.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            path.unlink()  # a truncated cache file is worse than none
    payload = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


def analyst_actions(symbol: str, months: int = 6) -> dict:
    """Recent analyst upgrades and downgrades. The journal's "Monkey Downgrade?".

    Isolated in its own function with a broad except because it is the least
    reliable thing here: the provider changes this table's shape between
    releases and drops it entirely for some small caps. A name with no analyst
    coverage is a real state and must read as unknown rather than as "no
    downgrade", which would be a free point.
    """
    try:
        import pandas as pd
        import yfinance as yf

        table = yf.Ticker(symbol).upgrades_downgrades
        if table is None or table.empty:
            return {"covered": False}
        cutoff = pd.Timestamp.now(tz=table.index.tz) - pd.DateOffset(months=months)
        recent = table[table.index >= cutoff]
        if recent.empty:
            return {"covered": True, "downgrades": 0, "upgrades": 0, "actions": 0}
        grades = recent["Action"].astype(str).str.lower()
        return {
            "covered": True,
            "downgrades": int((grades == "down").sum()),
            "upgrades": int((grades == "up").sum()),
            "actions": int(len(recent)),
            "latest": str(recent.index.max().date()),
        }
    except Exception as exc:  # noqa: BLE001
        return {"covered": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--contact",
        required=True,
        help="Name and email for the SEC User-Agent. They require a real one.",
    )
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-analysts", action="store_true",
                    help="Skip the yfinance leg and run on EDGAR alone.")
    ap.add_argument("--limit", type=int, default=0, help="First N tickers, for a smoke test.")
    args = ap.parse_args()

    tickers = read_watchlist(ROOT / "data" / "watchlist.txt")
    if args.limit:
        tickers = tickers[: args.limit]
    use_cache = not args.no_cache

    client = EdgarClient(contact=args.contact)
    print("fetching the ticker to CIK map", flush=True)
    cik_map = cached("_cik_map", client.cik_map, use_cache)
    cik_map = {k.upper(): int(v) for k, v in cik_map.items()}

    today = date.today()
    data: dict[str, dict] = {}
    no_cik: list[str] = []
    failed: list[str] = []

    for i, symbol in enumerate(tickers, 1):
        cik = cik_map.get(symbol)
        if cik is None:
            no_cik.append(symbol)
            print(f"  {i}/{len(tickers)} {symbol}: no CIK, foreign or delisted", flush=True)
            continue
        try:
            facts = cached(f"{symbol}_facts", lambda c=cik: client.company_facts(c), use_cache)
            subs = cached(f"{symbol}_subs", lambda c=cik: client.submissions(c), use_cache)
            record = extract(facts, subs, as_of=today)
            record["cik"] = cik
            if not args.no_analysts:
                record["analysts"] = analyst_actions(symbol)
            data[symbol] = record
            years = record["fiscal_years"]
            bits = []
            if record["dilution_risk"]:
                bits.append(f"{len(record['dilution_filings'])} offering filings")
            if record["catalyst_days_ago"] is not None:
                bits.append(f"8-K {record['catalyst_days_ago']}d ago")
            print(
                f"  {i}/{len(tickers)} {symbol}: {len(years)} years"
                + (", " + ", ".join(bits) if bits else ""),
                flush=True,
            )
        except (EdgarError, Exception) as exc:  # noqa: BLE001
            failed.append(f"{symbol} ({type(exc).__name__})")
            print(f"  {i}/{len(tickers)} {symbol}: FAILED, {exc}", flush=True)

    out = ROOT / "data" / "fundamentals.json"
    out.write_text(
        json.dumps(
            {
                "as_of": today.isoformat(),
                "source": "SEC EDGAR companyfacts and submissions"
                + ("" if args.no_analysts else ", plus yfinance for analyst actions"),
                "fetched": len(data),
                "no_cik": no_cik,
                "failed": failed,
                "data": data,
            },
            indent=1,
        )
    )
    print(f"\nwrote {out}")
    print(f"  {len(data)} fetched, {len(no_cik)} without a CIK, {len(failed)} failed")
    if no_cik:
        print("  no CIK: " + ", ".join(no_cik[:25]) + (" ..." if len(no_cik) > 25 else ""))
    if failed:
        print("  failed: " + ", ".join(failed[:25]) + (" ..." if len(failed) > 25 else ""))

    dilution = [t for t, r in data.items() if r.get("dilution_risk")]
    catalysts = [t for t, r in data.items() if r.get("catalyst_days_ago") is not None]
    print(f"\n  {len(dilution)} names filed an offering in the last 180 days")
    print(f"  {len(catalysts)} names filed an 8-K in the last 30 days")


if __name__ == "__main__":
    main()
