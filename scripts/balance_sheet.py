"""Read one or more balance sheets straight from EDGAR and run the four checks.

    .venv/bin/python scripts/balance_sheet.py TEM SEZL \
        --contact "Zac Thorman zdthorman@gmail.com"

WHY THIS EXISTS AS A SCRIPT. The balance sheet reading was first done by hand,
one company at a time, and a hand pull is not a result anybody can check. This
turns it into a command, so the numbers behind a verdict can be re-derived from
the filings rather than trusted because they appeared in a chat.

WHAT IT IS NOT. It does not score and it does not rank. `balance.py` returns a
list of flags with the numbers attached, and the verdict is a summary of the
worst flag rather than a rating. A single critical flag should stop you however
the rest of the sheet reads.

MISSING LINES STAY MISSING. Every field is optional and a line the company did
not report comes through as None, never as zero. The checks that depend on it
abstain and say so in the notes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.balance import BalanceSheet, to_dict  # noqa: E402
from stocksignal.sources.edgar import (  # noqa: E402
    ASSETS_CURRENT_TAGS,
    ASSETS_TAGS,
    CASH_TAGS,
    DEBT_CURRENT_TAGS,
    DEBT_TAGS,
    EQUITY_TAGS,
    GOODWILL_TAGS,
    INTANGIBLE_TAGS,
    INVENTORY_TAGS,
    LIABILITIES_CURRENT_TAGS,
    LIABILITIES_TAGS,
    PAYABLES_TAGS,
    RECEIVABLES_TAGS,
    REVENUE_TAGS,
    EdgarClient,
    EdgarError,
    annual_series,
)

CACHE = ROOT / "cache" / "edgar"

# Field name on BalanceSheet to the tags that fill it. Order matters inside a
# tag group: the first tag that returns anything wins, which is how a company
# that reports AccountsPayableCurrent and one that reports the combined
# accrued-liabilities line both come out with a payables figure.
LINES = {
    "assets": ASSETS_TAGS,
    "assets_current": ASSETS_CURRENT_TAGS,
    "liabilities": LIABILITIES_TAGS,
    "liabilities_current": LIABILITIES_CURRENT_TAGS,
    "equity": EQUITY_TAGS,
    "cash": CASH_TAGS,
    "inventory": INVENTORY_TAGS,
    "receivables": RECEIVABLES_TAGS,
    "payables": PAYABLES_TAGS,
    "goodwill": GOODWILL_TAGS,
    "intangibles": INTANGIBLE_TAGS,
    "debt_long": DEBT_TAGS,
    "debt_current": DEBT_CURRENT_TAGS,
    "revenue": REVENUE_TAGS,
}

# The three lines that also need last year, because the checks are year on year.
PRIOR = ("receivables", "payables", "revenue", "intangibles")


def cached(name: str, fetch, use_cache: bool):
    path = CACHE / f"{name}.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    payload = fetch()
    if use_cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return payload


def build(ticker: str, facts: dict) -> BalanceSheet:
    """Latest fiscal year plus the one before, from a companyfacts payload."""
    series = {field: annual_series(facts, tags) for field, tags in LINES.items()}

    # The reporting year is whichever year the company filed a total-assets
    # figure for. Anchoring on Assets rather than on the union of every line
    # stops a single stray tag from inventing a year with one number in it.
    years = sorted(series["assets"].values)
    if not years:
        # NAME THE CAUSE, DO NOT GUESS IT. "no Assets series, cannot read a
        # balance sheet" describes a company that files no balance sheet. On the
        # 220-name sweep it was returned for 35 names and every one of them was a
        # foreign private issuer: ASML, TSM, ARM, STM, CCJ, TECK and the rest.
        # They file full balance sheets, under IFRS, and `annual_series` reads
        # `facts["us-gaap"]` and nothing else, so the module never looked. The
        # message now reports which taxonomies the payload actually carries.
        taxonomies = sorted((facts.get("facts") or {}).keys())
        if "us-gaap" not in taxonomies:
            raise EdgarError(
                f"{ticker}: files no us-gaap facts, only {taxonomies or 'nothing'}. "
                f"This reader covers us-gaap only, so a 20-F filer reporting under "
                f"IFRS is not unreadable, it is unread."
            )
        raise EdgarError(
            f"{ticker}: files us-gaap facts but no Assets tag, cannot read a balance sheet"
        )
    latest = years[-1]
    prior = years[-2] if len(years) > 1 else None

    kwargs: dict[str, object] = {"ticker": ticker}
    for field, s in series.items():
        kwargs[field] = s.values.get(latest)
    for field in PRIOR:
        kwargs[f"prev_{field}"] = series[field].values.get(prior) if prior else None
    kwargs["fiscal_years"] = tuple(y for y in (prior, latest) if y is not None)
    return BalanceSheet(**kwargs)  # type: ignore[arg-type]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--contact", required=True, help="Real name and email. The SEC asks for it.")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--json", type=Path, default=None, help="Also write the full reading here")
    args = ap.parse_args()

    client = EdgarClient(args.contact)
    ciks = cached("_tickers", client.cik_map, not args.no_cache)
    ciks = {k.upper(): int(v) for k, v in ciks.items()}

    out, failures = {}, {}
    for ticker in (t.upper() for t in args.tickers):
        cik = ciks.get(ticker)
        if cik is None:
            failures[ticker] = "no CIK: foreign issuer, ETF, or delisted"
            continue
        try:
            facts = cached(f"facts-{cik}", lambda c=cik: client.company_facts(c), not args.no_cache)
            sheet = build(ticker, facts)
        except (EdgarError, KeyError, ValueError) as exc:
            failures[ticker] = f"{type(exc).__name__}: {exc}"
            continue
        out[ticker] = sheet
        report(sheet)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {"sheets": {t: to_dict(s) for t, s in out.items()}, "failures": failures}, indent=2
            )
        )
        print(f"\nwritten to {args.json}")

    # Failures are named, never swallowed. A silent partial result is the exact
    # failure mode this project has walked into more than once.
    if failures:
        print("\nFAILED")
        for ticker, why in failures.items():
            print(f"  {ticker}: {why}")
    return 0


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def num(v: float | None) -> str:
    if v is None:
        return "n/a"
    for unit, size in (("bn", 1e9), ("m", 1e6), ("k", 1e3)):
        if abs(v) >= size:
            return f"{v / size:,.1f}{unit}"
    return f"{v:,.0f}"


def report(b: BalanceSheet) -> None:
    years = "/".join(str(y) for y in b.fiscal_years) or "unknown"
    print(f"\n{'=' * 68}\n{b.ticker}  fiscal {years}\n{'=' * 68}")
    print(f"  VERDICT  {b.verdict}")
    ratio = "n/a" if b.current_ratio is None else f"{b.current_ratio:.2f}"
    cur = "n/a" if b.current_pct is None else f"{b.current_pct:.0f}%"
    soft = "n/a" if b.intangible_pct is None else f"{b.intangible_pct:.0f}%"
    print(f"\n  1 cash and liquidity   current ratio {ratio}, cash {num(b.cash)}")
    print(f"  2 current and tangible  current {cur} of assets, soft {soft}")
    print(f"  3 debt                  total {num(b.total_debt)}, net {num(b.net_debt)}")
    print(
        f"  4 receivables           receivables {pct(b.receivable_growth)}, "
        f"payables {pct(b.payable_growth)}, revenue {pct(b.revenue_growth)}"
    )
    print(f"\n  NAV {num(b.nav)}   NTAV {num(b.ntav)}")
    if b.flags:
        print("\n  FLAGS")
        for f in b.flags:
            print(f"    [{f.severity.upper():8}] {f.check}: {f.message}")
    else:
        print("\n  no flags")
    for note in b.notes:
        print(f"    note: {note}")


if __name__ == "__main__":
    raise SystemExit(main())
