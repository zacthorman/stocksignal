"""The control arm: passed names against the ones the screens turned down.

  python scripts/screen_control.py --source alpaca

Writes `outcomes/CONTROL.md`, committed beside the outcomes report, because a
control that lives in a job log is a control nobody reads.

WHY THIS EXISTS. `score_signals.py` measures the signals against SPY, and
SPY is the wrong yardstick for a universe filtered on beta >= 2: when the market
falls a point these names fall two or three, so most of the gap is the filter
rather than the screens. The comparison that isolates the screens is the rest of
the same watchlist on the same morning, which the digests have been committing
all along in their rejected sections.

The cohorts, the unit of observation, and the statistic are all defined in
`stocksignal.control`, which was written before this was first run. Read that
module's docstring before reading any number below it.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")

from stocksignal.control import (  # noqa: E402
    GATED_OUT,
    SCREENED_OUT,
    ControlResult,
    compare_day,
    read_digest_cohorts,
)
from stocksignal.data import get_source  # noqa: E402
from stocksignal.outcomes import (  # noqa: E402
    CLOSE,
    entry_position,  # noqa: E402
    fill_basis,
    span_return,
)
from stocksignal.signal_log import LEDGER_DIR, read_ledger  # noqa: E402

HORIZONS = (5, 20)
HISTORY_DAYS = 400


def all_histories(source, tickers: list[str], days: int) -> dict:
    if hasattr(source, "histories"):
        return source.histories(tickers, days=days)
    out = {}
    for ticker in tickers:
        try:
            out[ticker] = source.history(ticker, days=days)
        except Exception as exc:  # noqa: BLE001 - reported per name, never fatal
            print(f"  {ticker}: {exc}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="alpaca")
    ap.add_argument("--ledger", type=Path, default=LEDGER_DIR)
    ap.add_argument("--digests", type=Path, default=Path("digests"))
    ap.add_argument("--out", type=Path, default=Path("outcomes/CONTROL.md"))
    args = ap.parse_args()

    passed_by_day: dict[date, set[str]] = defaultdict(set)
    # THE WHOLE DAY SHARES ONE CLOCK. Both cohorts come from the same scan, so
    # whatever price the reader could have paid for a published name is the
    # price they could have paid for a rejected one. The day's fill basis comes
    # from the ledger's own `logged_at`, which is what `score_signals.py` uses.
    logged_by_day: dict[date, str | None] = {}
    for path in sorted(Path(args.ledger).glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        for row in read_ledger(path):
            passed_by_day[day].add(row["ticker"].upper())
            logged_by_day.setdefault(day, row.get("logged_at"))

    cohorts = read_digest_cohorts(args.digests)
    days = sorted(set(passed_by_day) & set(cohorts))
    if not days:
        print("no day has both a ledger file and a digest, nothing to compare")
        return

    tickers = sorted(
        {t for day in days for t in passed_by_day[day]}
        | {t for day in days for t, c in cohorts[day].items() if c == SCREENED_OUT}
    )
    print(f"{len(days)} days, {len(tickers)} names")

    frames = all_histories(get_source(provider=args.source), tickers, HISTORY_DAYS)

    results: dict[int, ControlResult] = {}
    for horizon in HORIZONS:
        comparisons = []
        for day in days:
            control_names = {t for t, c in cohorts[day].items() if c == SCREENED_OUT}
            legs: dict[str, dict[str, float]] = {"passed": {}, "control": {}}
            for name, bucket in [(t, "passed") for t in passed_by_day[day]] + [
                (t, "control") for t in control_names
            ]:
                frame = frames.get(name)
                if frame is None or frame.empty:
                    continue
                pos = entry_position(frame, day, logged_by_day.get(day))
                if pos is None:
                    continue
                basis = fill_basis(logged_by_day.get(day), frame.index[pos].date())
                # COSTS ARE ZERO ON BOTH LEGS, deliberately: the same round trip
                # applies to either cohort, so it cancels in the difference.
                value = span_return(frame, pos, pos + horizon, basis, CLOSE, 0.0)
                if value is not None:
                    legs[bucket][name] = value
            comparison = compare_day(day, horizon, legs["passed"], legs["control"])
            if comparison is not None:
                comparisons.append(comparison)
        results[horizon] = ControlResult(horizon, comparisons)

    lines = [
        f"# Did passing the screens beat not passing them? As of {date.today().isoformat()}",
        "",
        "Each morning's published signals against the names the same scan rejected **on a "
        "screen rather than a gate**: same watchlist, same day, same holding period, so "
        "the beta and the market cancel and what is left is the screens' opinion.",
        "",
        "**One day is one observation, and neighbouring days are not separate ones.** "
        "Dozens of names bought the same morning share a single market move, so each day "
        "contributes one number: the difference between the two cohorts' median returns. "
        "Two windows starting a day apart then share all but one session, so the sign "
        "test runs only over days spaced a full holding period apart. Both the rule and "
        "the statistic were fixed before the first run.",
        "",
        "**This first run is exploratory whatever it says.** The window already existed "
        "when the statistic was picked. It becomes a real test as new days arrive.",
        "",
    ]
    for horizon in HORIZONS:
        result = results[horizon]
        if not result.days:
            lines += [f"## {horizon} sessions", "", "No day had both cohorts finished.", ""]
            continue
        lines += [
            f"## {horizon} sessions",
            "",
            f"**{result.days_favouring} of {len(result.days)} days favour the screens**, "
            f"median daily difference **{result.median_difference:+.2f} points**. Those "
            "days overlap heavily, so that count is description rather than evidence.",
            "",
            (
                f"Of the {len(result.usable)} non-overlapping days, {result.wins} favour "
                f"the screens: sign test p = {result.p_value:.3f}."
            )
            if result.p_value == result.p_value
            else (
                f"**No test yet.** Only {len(result.usable)} non-overlapping "
                f"{'day exists' if len(result.usable) == 1 else 'days exist'} at this "
                f"horizon, "
                f"and even if every one agreed the p could not fall below "
                f"{result.floor_p:.3f}. A number here would read as a measurement when "
                "it would only be arithmetic on one observation, so there isn't one."
            ),
            "",
            "| day | passed | median | control | median | difference |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for d in result.days:
            lines.append(
                f"| {d.day.isoformat()} | {d.n_passed} | {d.passed_median:+.2f}% | "
                f"{d.n_control} | {d.control_median:+.2f}% | {d.difference:+.2f} |"
            )
        lines.append("")

    gated = sum(1 for day in days for c in cohorts[day].values() if c == GATED_OUT)
    screened = sum(1 for day in days for c in cohorts[day].values() if c == SCREENED_OUT)
    lines += [
        "---",
        "",
        f"Cohorts came from {len(days)} digests: {screened} rejections on a screen, "
        f"{gated} on a hard gate. Gated names are excluded from the control on purpose: "
        "a name turned down for an 11 million float says nothing about the trend screen.",
        "",
        "Costs are not deducted on either leg, because both cohorts pay the same round "
        "trip and it cancels in the difference.",
        "",
        "Nothing here is financial advice, and nothing here is a verdict on the tool.",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    for horizon in HORIZONS:
        r = results[horizon]
        if r.days:
            print(
                f"{horizon}: {r.wins}/{len(r.usable)} days, median "
                f"{r.median_difference:+.2f}, p={r.p_value:.3f}"
            )
    print(f"written {args.out}")


if __name__ == "__main__":
    main()
