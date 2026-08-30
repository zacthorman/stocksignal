"""Run the four balance sheet checks across the whole watchlist, then ask
whether the layer actually discriminates.

    .venv/bin/python scripts/balance_sweep.py --contact "Zac Thorman you@email.com"

    # Re-print the analysis from a finished sweep, no network at all.
    .venv/bin/python scripts/balance_sweep.py --summary-only

WHY THIS EXISTS, AND IT IS NOT TO PRODUCE A RANKING.

`balance.py` has only ever been run by hand, on one ticker at a time, on TEM and
SEZL. Two names is enough to show the module works and nowhere near enough to
show it is useful. The question this script exists to answer is the same one
Gate 1 failed: a filter that abstains nine times in ten is not filtering, and a
filter that flags four names in five is not filtering either. Before the layer
is wired into the daily scan it has to be shown to separate the board.

So the output that matters is not the list of verdicts. It is the distribution,
the coverage rate, and the per-check abstention rate. Those three decide whether
the wiring job is worth doing at all.

WHAT IT DELIBERATELY DOES NOT DO.

No score, no rank, no ordering by severity. `balance.py` refuses to sum flags
because one disqualifying flag should stop you regardless of the others, and a
sweep that quietly sorted the board by flag count would reintroduce exactly the
arithmetic the module was built to avoid. The records come back in watchlist
order and the analysis counts them, nothing more.

RAW FILINGS ARE NOT CACHED BY DEFAULT. A companyfacts payload runs to several
megabytes and 256 of them would put well over a gigabyte on disk for a reading
that is only redone when a company files. Pass --cache-facts if a rerun in the
next few days is likely and the disk can take it. The derived records are always
kept, and the sweep resumes from them, which is the cheap half of the same idea.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import balance_sheet as bs  # noqa: E402

from stocksignal.balance import to_dict  # noqa: E402
from stocksignal.sources.edgar import EdgarClient  # noqa: E402

DEFAULT_OUT = ROOT / "out" / "balance-sweep.json"
CHECK_NAMES = (
    "1 cash",
    "2 current and tangible",
    "3 debt",
    "4 receivables",
)
VERDICTS = ("SOLID", "WATCH", "CONCERN", "AVOID", "UNKNOWN")


def read_watchlist(path: Path) -> list[str]:
    """One ticker a line, `#` starts a comment, INLINE comments allowed.

    The inline half is the whole point and the first version of this function
    missed it. `build_watchlist.py` writes every row as `AEHR    # BETA 5.54
    $107.03  VOL 3,399,576`, so skipping only lines that START with `#` hands
    the entire line back as a ticker. Matches `cards.py` and `score_watchlist.py`,
    which have always had it right.
    """
    out = []
    for line in path.read_text().splitlines():
        symbol = line.split("#", 1)[0].strip().upper()
        if symbol:
            out.append(symbol)
    return out


def check_symbols(tickers: list[str]) -> None:
    """Refuse to run on something that is not a list of tickers.

    WHY THIS GUARD EXISTS. When the parser above was wrong, all 256 rows were
    looked up in the CIK map, missed, and filed as "no CIK: foreign issuer, ETF,
    or delisted". That message is a real cause of a real failure, so a parsing
    bug wearing it looked exactly like a watchlist full of foreign issuers. A
    plausible wrong answer is worse than a crash, so this crashes.
    """
    bad = [t for t in tickers if not (1 <= len(t) <= 6) or not t.isalpha()]
    if bad:
        raise SystemExit(
            f"{len(bad)} of {len(tickers)} parsed symbols are not tickers, "
            f"so the watchlist is not being read correctly. First few: {bad[:3]}"
        )


def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"as_of": date.today().isoformat(), "sheets": {}, "failures": {}}


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def sweep(args) -> dict:
    tickers = read_watchlist(Path(args.watchlist))
    check_symbols(tickers)
    if args.limit:
        tickers = tickers[: args.limit]

    payload = load(Path(args.out))
    sheets, failures = payload["sheets"], payload["failures"]
    if getattr(args, "retry_failures", False) and failures:
        # A failure is recorded so the sweep does not re-ask a question already
        # answered. When the READER changes, the recorded answer is stale.
        print(f"clearing {len(failures)} recorded failures and reading them again\n")
        failures.clear()

    client = EdgarClient(args.contact)
    ciks = bs.cached("_tickers", client.cik_map, True)
    ciks = {k.upper(): int(v) for k, v in ciks.items()}

    todo = [t for t in tickers if t not in sheets and t not in failures]
    print(f"{len(tickers)} on the watchlist, {len(todo)} still to read.\n")

    try:
        run(todo, ciks, client, sheets, failures, payload, args)
    finally:
        # A CRASH MUST NOT COST THE FETCHES. This is a `finally` and not an
        # `except` on purpose: a defect inside `balance.py` should still take
        # the run down loudly, because per-ticker exception handling is how this
        # project once hid a ZeroDivisionError that was discarding its own best
        # signals. What it should not also do is throw away 50 EDGAR reads on
        # the way out. Loud, and resumable.
        save(Path(args.out), payload)

    print(f"\nwritten to {args.out}")
    return payload


def run(todo, ciks, client, sheets, failures, payload, args) -> None:
    for i, ticker in enumerate(todo, start=1):
        cik = ciks.get(ticker)
        if cik is None:
            failures[ticker] = "no CIK: foreign issuer, ETF, or delisted"
            print(f"  {i:3d}/{len(todo)}  {ticker:6s} FAILED  {failures[ticker]}")
            continue
        try:
            facts = bs.cached(
                f"facts-{cik}", lambda c=cik: client.company_facts(c), args.cache_facts
            )
            sheet = bs.build(ticker, facts)
        except Exception as exc:  # noqa: BLE001 - every failure is named, never swallowed
            failures[ticker] = f"{type(exc).__name__}: {exc}"
            print(f"  {i:3d}/{len(todo)}  {ticker:6s} FAILED  {failures[ticker]}")
            continue

        record = to_dict(sheet)
        # `coverage` is not in to_dict and it is the number this whole exercise
        # turns on, so it is added here rather than inferred later.
        record["coverage"] = list(sheet.coverage)
        sheets[ticker] = record
        flags = len(record["flags"])
        print(
            f"  {i:3d}/{len(todo)}  {ticker:6s} {record['verdict']:8s} "
            f"{sum(record['coverage'])}/4 checks, {flags} flag{'' if flags == 1 else 's'}"
        )

        if i % 5 == 0:
            save(Path(args.out), payload)


def write_store(payload: dict, path: Path) -> None:
    """Trim the sweep down to what the daily scan needs, and commit that.

    WHY A SECOND, SMALLER FILE. `out/` is gitignored, and it should stay that
    way: the full sweep carries every ratio for 220 companies and is a working
    artefact. The scan runs in GitHub Actions from a clean checkout with no
    EDGAR access budget, so what it needs is a committed file holding the
    verdict, the coverage count, the flag names, and the date the reading was
    taken. Nothing else travels.

    The failures travel too, and that is the point of the `unreadable` half.
    Dropping them would leave ASML looking like a company with nothing to
    report rather than one this reader does not cover.
    """
    readings = {
        t: {
            "verdict": s["verdict"],
            "coverage": sum(s.get("coverage") or []),
            # The MESSAGES travel, not just the check names. The digest prints
            # one line and needs neither, but a card prints the argument, and
            # the argument is the figure that produced the flag. Without it the
            # card would show "CONCERN", which is a rating, and a rating is the
            # one thing this module refuses to produce.
            "flags": [
                {"severity": f["severity"], "check": f["check"], "message": f["message"]}
                for f in s["flags"]
            ],
            "notes": s.get("notes", []),
        }
        for t, s in payload["sheets"].items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": payload.get("as_of") or date.today().isoformat(),
                "readings": readings,
                "unreadable": payload["failures"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(
        f"store written to {path}: {len(readings)} readings, "
        f"{len(payload['failures'])} unreadable"
    )


def analyse(payload: dict) -> None:
    sheets, failures = payload["sheets"], payload["failures"]
    n = len(sheets)
    if not n:
        print("Nothing to analyse.")
        return

    rule = "=" * 70
    print(f"\n{rule}\nTHE DISTRIBUTION, on {n} names read and {len(failures)} failed\n{rule}")

    verdicts = Counter(s["verdict"] for s in sheets.values())
    for v in VERDICTS:
        c = verdicts.get(v, 0)
        bar = "#" * round(40 * c / n)
        print(f"  {v:8s} {c:4d}  {100 * c / n:5.1f}%  {bar}")

    actionable = sum(verdicts.get(v, 0) for v in ("CONCERN", "AVOID"))
    print(
        f"\n  Flagged hard (CONCERN or AVOID): {actionable} of {n}, "
        f"{100 * actionable / n:.1f}%"
        f"\n  Declined to answer (UNKNOWN):    {verdicts.get('UNKNOWN', 0)} of {n}, "
        f"{100 * verdicts.get('UNKNOWN', 0) / n:.1f}%"
    )

    print(f"\n{'-' * 70}\nCOVERAGE, which checks could be answered at all\n{'-' * 70}")
    per_check = [0, 0, 0, 0]
    depth = Counter()
    for s in sheets.values():
        cov = s.get("coverage") or [False] * 4
        depth[sum(cov)] += 1
        for i, ok in enumerate(cov):
            per_check[i] += 1 if ok else 0
    for i, name in enumerate(CHECK_NAMES):
        got = per_check[i]
        print(f"  check {name:24s} answered {got:4d}/{n}  {100 * got / n:5.1f}%")
    print()
    for k in range(4, -1, -1):
        c = depth.get(k, 0)
        if c:
            print(f"  {k} of 4 checks answered: {c:4d}  {100 * c / n:5.1f}%")

    print(f"\n{'-' * 70}\nFLAGS, how often each one fires\n{'-' * 70}")
    by_check = Counter()
    by_sev = Counter()
    for s in sheets.values():
        for f in s["flags"]:
            by_check[(f["severity"], f["check"])] += 1
            by_sev[f["severity"]] += 1
    for (sev, check), c in sorted(by_check.items(), key=lambda kv: -kv[1]):
        print(f"  [{sev:8s}] {check:26s} {c:4d}  {100 * c / n:5.1f}% of names")
    print("\n  by severity: " + ", ".join(f"{k} {v}" for k, v in by_sev.most_common()))

    crit = [t for t, s in sheets.items() if any(f["severity"] == "critical" for f in s["flags"])]
    if crit:
        print(f"\n  CRITICAL, {len(crit)}: " + ", ".join(sorted(crit)))

    print(f"\n{'-' * 70}\nTHE READ\n{'-' * 70}")
    # The bar is set here and not after seeing the answer, which is the whole
    # point of writing it into the script rather than into the conclusion.
    unknown_pct = 100 * verdicts.get("UNKNOWN", 0) / n
    flagged_pct = 100 * actionable / n
    if unknown_pct > 50:
        print("  ABSTAINS. More than half the board cannot be read, which is Gate 1 again.")
    elif flagged_pct > 60:
        print("  TOO LOOSE. It flags most of the board, so it separates nothing.")
    elif flagged_pct < 3:
        print("  TOO TIGHT. It almost never fires, so it will not change a decision.")
    else:
        print(f"  DISCRIMINATES. {flagged_pct:.0f}% flagged hard, {unknown_pct:.0f}% unreadable.")

    if failures:
        print(f"\n  FAILED TO READ, {len(failures)}:")
        for t, why in sorted(failures.items())[:20]:
            print(f"    {t}: {why}")
        if len(failures) > 20:
            print(f"    ... and {len(failures) - 20} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contact", help="Real name and email. The SEC asks for it.")
    ap.add_argument("--watchlist", default=str(ROOT / "data" / "watchlist.txt"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=0, help="First N names only, for a smoke test")
    ap.add_argument(
        "--retry-failures",
        action="store_true",
        help="Clear the recorded failures and read those names again",
    )
    ap.add_argument("--cache-facts", action="store_true", help="Keep the raw filings on disk")
    ap.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Also write the trimmed, committable file the daily scan reads",
    )
    ap.add_argument(
        "--summary-only", action="store_true", help="Analyse an existing sweep, no network"
    )
    args = ap.parse_args()

    if args.summary_only:
        payload = load(Path(args.out))
        if args.store:
            write_store(payload, args.store)
        analyse(payload)
        return 0
    if not args.contact:
        ap.error("--contact is required unless --summary-only")
    payload = sweep(args)
    if args.store:
        write_store(payload, args.store)
    analyse(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
