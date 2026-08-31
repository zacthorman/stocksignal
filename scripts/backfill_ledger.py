"""Recover the signal ledger from the digests already committed.

    PYTHONPATH=src python scripts/backfill_ledger.py --dry-run
    PYTHONPATH=src python scripts/backfill_ledger.py

WHY THIS EXISTS. Between 11 and 28 August 2026 the scheduled scan wrote its
signals to `signals.db` on a GitHub runner, and `signals.db` is gitignored, so
every one of those days was written and deleted a minute later. What survived is
`digests/`, which the workflow does commit, and a digest carries the ticker, the
close, the score and the reasons for every candidate. That is enough to rebuild
the record.

WHAT IT CANNOT RECOVER, AND SAYS SO RATHER THAN GUESSING.

`logged_at` is a wall-clock time that no digest records, so reconstructed rows
carry an empty one rather than the time this script happened to run.

`screens` is only partly recoverable. A digest prints the reasons from the
screens that PASSED and a separate line naming the ones that did not fire, so a
candidate marked "Did not fire on: breakout" passed on trend. Where the digest
names no non-firing screen the passing set cannot be pinned down from the text,
and the field is left empty rather than filled with a plausible guess.

Every row it writes is marked `reconstructed from digest`, so nothing here can
ever be mistaken for a row the scanner logged at the time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.signal_log import RECONSTRUCTED  # noqa: E402

CANDIDATE = re.compile(r"^### \d+\. ([A-Z.]+) at ([\d,]+\.\d+) \(score ([\d.]+)\)$")
REASON = re.compile(r"^- (?!_)(.+)$")
NOT_FIRING = re.compile(r"^- _Did not fire on: (.+?)\._$")
ALL_SCREENS = ("trend", "breakout")


def parse_digest(path: Path) -> list[dict]:
    """One digest into ledger rows. Returns [] for a digest with no candidates."""
    day = path.stem.replace("digest-", "")
    rows: list[dict] = []
    current: dict | None = None

    for line in path.read_text().splitlines():
        m = CANDIDATE.match(line)
        if m:
            if current:
                rows.append(current)
            ticker, close, score = m.groups()
            current = {
                "as_of": day,
                "ticker": ticker,
                "close": float(close.replace(",", "")),
                "score": float(score),
                "screens": [],
                "reasons": [],
                "logged_at": "",
                "source": RECONSTRUCTED,
            }
            continue
        if current is None:
            continue
        nf = NOT_FIRING.match(line)
        if nf:
            missing = {s.strip() for s in nf.group(1).split(",")}
            current["screens"] = [s for s in ALL_SCREENS if s not in missing]
            continue
        r = REASON.match(line)
        if r:
            current["reasons"].append(r.group(1))

    if current:
        rows.append(current)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--digests", type=Path, default=ROOT / "digests")
    ap.add_argument("--ledger", type=Path, default=ROOT / "signals")
    ap.add_argument("--dry-run", action="store_true", help="Report and write nothing")
    args = ap.parse_args()

    digests = sorted(args.digests.glob("digest-*.md"))
    if not digests:
        print(f"no digests under {args.digests}", file=sys.stderr)
        return 1

    total = 0
    for d in digests:
        rows = parse_digest(d)
        day = d.stem.replace("digest-", "")
        out = args.ledger / f"{day}.jsonl"

        if out.exists():
            # NEVER OVERWRITE A REAL ROW WITH A RECONSTRUCTED ONE. A day the
            # scanner logged at the time is better evidence than a day rebuilt
            # from its own printed output, and this script must not be able to
            # downgrade one into the other.
            print(f"  {day}  SKIPPED, a ledger already exists for that day")
            continue
        if not rows:
            print(f"  {day}  no candidates in the digest, nothing to write")
            continue

        with_screens = sum(1 for r in rows if r["screens"])
        print(
            f"  {day}  {len(rows):3d} rows, {with_screens} with a recoverable screen set"
        )
        total += len(rows)
        if not args.dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
            )

    verb = "would write" if args.dry_run else "wrote"
    print(f"\n{verb} {total} reconstructed rows across {len(digests)} digests")
    if args.dry_run:
        print("dry run, nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
