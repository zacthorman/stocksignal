"""Tell the scan you have looked at a name and the answer is no.

    PYTHONPATH=src python scripts/dismiss.py TXG --reason "no setup, waiting for a pullback"
    PYTHONPATH=src python scripts/dismiss.py TXG SSRM CHYM --days 60
    PYTHONPATH=src python scripts/dismiss.py --list
    PYTHONPATH=src python scripts/dismiss.py TXG --undo

WHY THIS IS ALLOWED TO REORDER THE DIGEST WHEN NOTHING ELSE IS. The balance
layer refuses to filter, and so does every screen: the tool reports and Zac
decides. A dismissal is the other case. It is Zac's decision, recorded so the
tool stops asking the same question every morning, and the digest still prints
the name under its own heading with the reason and the days remaining.

WHY IT EXPIRES. A dismissal is a judgement about a chart, and charts change. A
screener that honoured a six-week-old "no" forever would let a stale decision
quietly shrink the universe, which is the same failure as the growth direction
call that never ages out. Thirty days by default, `--days` to override.

A REASON IS OPTIONAL AND WORTH WRITING ANYWAY. In six weeks the name comes back
and the only thing that will tell you whether the objection still stands is what
you wrote down at the time.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.memory import (  # noqa: E402
    DEFAULT_DISMISSAL_DAYS,
    load_dismissals,
)

DISMISSALS = ROOT / "data" / "dismissed.json"


def write(entries: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tickers", nargs="*", help="Names to dismiss")
    ap.add_argument("--reason", default="", help="Why. Optional, and worth writing")
    ap.add_argument("--days", type=int, default=DEFAULT_DISMISSAL_DAYS)
    ap.add_argument("--undo", action="store_true", help="Bring these names back now")
    ap.add_argument("--list", action="store_true", help="Show what is dismissed")
    ap.add_argument("--file", type=Path, default=DISMISSALS)
    args = ap.parse_args()

    raw = json.loads(args.file.read_text()) if args.file.exists() else {}
    today = date.today()

    if args.list or not args.tickers:
        current = load_dismissals(args.file)
        if not current:
            print("nothing dismissed")
            return 0
        live = {t: d for t, d in current.items() if d.active_on(today)}
        dead = {t: d for t, d in current.items() if not d.active_on(today)}
        print(f"{len(live)} active, {len(dead)} expired\n")
        for t, d in sorted(live.items()):
            print(f"  {t:6s} {d.describe(today)}")
        for t, d in sorted(dead.items()):
            print(f"  {t:6s} EXPIRED on {d.expires_on.isoformat()}, back in the digest")
        return 0

    for t in (x.upper() for x in args.tickers):
        if args.undo:
            if raw.pop(t, None) is None:
                print(f"  {t}: was not dismissed")
            else:
                print(f"  {t}: back in the digest from the next scan")
            continue
        raw[t] = {"on": today.isoformat(), "reason": args.reason, "days": args.days}
        why = f", {args.reason}" if args.reason else ""
        print(f"  {t}: dismissed for {args.days} days{why}")

    write(raw, args.file)
    print(f"\nwritten to {args.file}")
    print("Commit it, or the next scheduled scan will not know.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
