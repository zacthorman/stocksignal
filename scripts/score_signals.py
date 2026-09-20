"""Score the committed ledger against what the prices actually did.

Run weekly by `.github/workflows/score-signals.yml`, because that is where the
Alpaca credentials live and because horizons take time to elapse: a job that ran
daily would mostly rewrite the same file.

  python scripts/score_signals.py --source alpaca
  python scripts/score_signals.py --source alpaca --out outcomes

WHAT IT WRITES, AND WHY BOTH.

  outcomes/scores.jsonl   one row per signal, every finished horizon, with the
                          benchmark legs. Rewritten whole each run, so a
                          correction shows up as a diff in git rather than as a
                          second row nobody queries. Same rule as the ledger.
  outcomes/REPORT.md      the summary a human reads. Committed rather than
                          printed to a log, because a result that lives only in
                          a job's output is a result that does not exist. That
                          lesson cost this project thirteen days of signals.

THE REPORT PRINTS MEAN, MEDIAN AND TRIMMED MEAN TOGETHER, always, and says so
when they disagree. On 17 September a pre-registered test passed on a mean that
seven trades out of 138 had supplied 92% of. A report that led with the mean
would be able to tell that story again without anyone noticing.

NOTHING HERE DECIDES ANYTHING. There is no threshold, no verdict and no
promotion of a screen. The honesty gate in the README is a decision for Zac
against a tracker, and this file's job is to put the number in front of him,
not to grade it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")

from stocksignal.data import get_source  # noqa: E402
from stocksignal.outcomes import (  # noqa: E402
    DEFAULT_COST_PCT,
    HORIZONS,
    RULEBOOK,
    score_signal,
    summarise,
)
from stocksignal.signal_log import LEDGER_DIR, read_ledger  # noqa: E402

BENCHMARKS = {
    "SPY": "like for like: US large caps over the same sessions",
    # The project's original honesty gate is a FTSE all-world tracker, which is
    # not on a US equities feed. VT is the same idea on the same feed: Vanguard
    # Total World, US-listed. Named as a proxy rather than passed off as VWRP.
    "VT": "the tracker gate: buy the world instead, proxy for VWRP",
}

# 250 sessions of history covers the oldest ledger entry plus the SMA warm-up
# the rulebook exit needs before it. Widen it when the ledger outgrows a year.
HISTORY_DAYS = 400


def screens_of(row: dict) -> list[str]:
    """The ledger writes `screens` as a list; the recovered rows wrote a string."""
    raw = row.get("screens") or row.get("passed_screens") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [s.strip() for s in raw if s and s.strip()]


def all_histories(source, tickers: list[str], days: int) -> dict:
    """One batched request where the source offers it, a loop where it does not.

    Alpaca covers every symbol in one call, which is the whole reason the
    project moved to it. The synthetic and yfinance sources have `history` only,
    and are here so this script can be exercised without credentials.
    """
    if hasattr(source, "histories"):
        return source.histories(tickers, days=days)
    out = {}
    for ticker in tickers:
        try:
            out[ticker] = source.history(ticker, days=days)
        except Exception as exc:  # noqa: BLE001 - reported per name, never fatal
            print(f"  {ticker}: {exc}")
    return out


def load_signals(ledger_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(Path(ledger_dir).glob("*.jsonl")):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        rows.extend(read_ledger(path))
    return rows


def fmt(value: float | None, width: int = 7) -> str:
    return f"{value:+{width}.2f}%" if value is not None else " " * (width + 1)


def share(value: float | None) -> str:
    """Withheld rather than printed when the total is negative. See `Summary`."""
    return f"{value:.0f}%" if value is not None else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="alpaca")
    ap.add_argument("--ledger", type=Path, default=LEDGER_DIR)
    ap.add_argument("--out", type=Path, default=Path("outcomes"))
    ap.add_argument("--cost", type=float, default=DEFAULT_COST_PCT)
    args = ap.parse_args()

    signals = load_signals(args.ledger)
    if not signals:
        print("no ledger files, nothing to score")
        return
    tickers = sorted({r["ticker"].upper() for r in signals})
    print(
        f"{len(signals)} signals, {len(tickers)} names, "
        f"{min(r['as_of'] for r in signals)} to {max(r['as_of'] for r in signals)}"
    )

    source = get_source(provider=args.source)
    frames = all_histories(source, tickers + list(BENCHMARKS), HISTORY_DAYS)
    benchmarks = {name: frames[name] for name in BENCHMARKS if name in frames}
    missing_bench = [name for name in BENCHMARKS if name not in benchmarks]
    if missing_bench:
        # Reported, not fatal. A missing tracker costs a column; a missing
        # SPY costs the comparison, and the report says which happened.
        print(f"benchmark bars unavailable: {', '.join(missing_bench)}")

    # THE CHECK THIS SCRIPT SHOULD HAVE BEEN BORN WITH. The ledger records the
    # close the tool CLAIMED on the signal date. If the bar this script reads
    # for that same date disagrees, then every return below is measured from a
    # price the digest never printed, and the whole report is fiction. It costs
    # one comparison per signal and it is the only thing standing between a
    # misalignment and a confident conclusion.
    agree, disagree, unchecked = 0, [], 0
    scored, pending, unreadable = [], 0, []
    for row in signals:
        ticker = row["ticker"].upper()
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            unreadable.append(ticker)
            continue
        stamp = pd.Timestamp(row["as_of"])
        if stamp in frame.index and row.get("close"):
            claimed, seen = float(row["close"]), float(frame.loc[stamp, "close"])
            if seen > 0 and abs(seen - claimed) / claimed <= 0.005:
                agree += 1
            else:
                disagree.append((ticker, row["as_of"], claimed, seen))
        else:
            unchecked += 1

        out = score_signal(
            ticker,
            date.fromisoformat(row["as_of"]),
            frame,
            benchmarks,
            cost_pct=args.cost,
            logged_at=row.get("logged_at"),
        )
        if out is None:
            pending += 1
            continue
        scored.append((out, row))

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "scores.jsonl").open("w") as fh:
        for out, row in sorted(scored, key=lambda pair: (pair[0].as_of, pair[0].ticker)):
            fh.write(
                json.dumps(
                    {
                        "as_of": out.as_of.isoformat(),
                        "ticker": out.ticker,
                        "entry_date": out.entry_date.isoformat(),
                        "score": row.get("score"),
                        "screens": screens_of(row),
                        "held_sessions": out.held,
                        "fill": out.basis,
                        "returns": {str(k): round(v, 4) for k, v in out.returns.items()},
                        "benchmarks": {
                            name: {str(k): round(v, 4) for k, v in legs.items()}
                            for name, legs in out.benchmarks.items()
                        },
                    }
                )
                + "\n"
            )

    rows = [out for out, _ in scored]
    open_fills = sum(1 for r in rows if r.basis == "open")
    close_fills = len(rows) - open_fills
    names = tuple(benchmarks)
    lines = [
        f"# Signal outcomes, as of {date.today().isoformat()}",
        "",
        f"{len(signals)} signals in the ledger, {len(rows)} with at least one finished "
        f"horizon, {pending} with nothing finished yet.",
        "",
        "Every signal is scored as an equal-weight paper trade whether or not it was "
        "taken: the ledger records what the tool claimed, so this measures the tool. "
        f"Costs of {args.cost}% are deducted once from the trade and never from the "
        "benchmark.",
        "",
        "**Entry is the first price that existed after the digest did.** A signal "
        "published before the opening bell fills at the next open; one published after "
        "it fills at that session's close, which is the next price a reader could "
        f"actually have paid. Here that is {open_fills} trades filled at an open and "
        f"{close_fills} at a close. The split is computed per signal from the ledger's "
        "own clock, so it tracks whatever the scheduled scan actually does rather than "
        "what it is supposed to do.",
        "",
        "**Read the median and the trimmed mean before the mean.** A mean that needs its "
        "best trades is a mean you cannot trade, because you do not know in advance "
        "which ones they are.",
        "",
        "**No significance is claimed anywhere in this file.** Nothing here was "
        "pre-registered, no test was run, and the trades overlap heavily: dozens bought "
        "the same morning and held the same sessions are readings of one market move. "
        "Read it as a record of what happened, and look at the entry-day tables below "
        "before believing any average.",
        "",
        "**The last row is a proxy and not your exit rule.** Page 107 says validation, "
        "the first candle holding below the 9 SMA, is not a concrete exit point: it is "
        "where you re-weigh the factors and decide. Selling on it is what can be scored "
        "without a person in the loop, so that is what the row measures. The rulebook's "
        "real exit needs a hard stop at a previous support level and a 5% trailing stop "
        "armed only after the price target is hit, and neither is decided yet: the "
        "support definition is the project's open question, and the tool deliberately "
        "publishes no price targets.",
        "",
        "| horizon | trades | entry days | mean | median | trim best 5% | hit rate |"
        + "".join(f" {n} itself | excess vs {n} (mean / median) |" for n in names),
        "|---|---:|---:|---:|---:|---:|---:|" + "---:|---:|" * len(names),
    ]
    for horizon in (*HORIZONS, RULEBOOK):
        summary = summarise(rows, horizon, names)
        label = "sell on validation" if horizon == RULEBOOK else f"{horizon} sessions"
        if summary is None:
            # Not a zero. Nothing has been held that long yet, and the row says
            # so rather than reading as a flat result.
            lines.append(f"| {label} | not yet elapsed | | | | | |" + " |" * len(names))
            continue
        cells = "".join(
            f" {fmt(summary.benchmark_mean.get(n))} |"
            f" {fmt(summary.excess_mean.get(n))} / {fmt(summary.excess_median.get(n))} |"
            for n in names
        )
        days = len({s.entry_date for s in rows if horizon in s.returns})
        lines.append(
            f"| {label} | {summary.n} | {days} | {fmt(summary.mean)} | {fmt(summary.median)} | "
            f"{fmt(summary.trimmed)} | {summary.hit_rate:.0f}% |" + cells
        )

    headline = summarise(rows, 20, names)
    if headline is not None:
        finished = [s for s in rows if 20 in s.returns]
        days = sorted({s.entry_date for s in finished})
        lines += ["", "## The 20-session horizon, in words", ""]
        lines.append(
            f"These {headline.n} trades were entered on {len(days)} mornings, "
            f"{days[0].isoformat()} to {days[-1].isoformat()}, so this is one window of "
            "market rather than a track record. It will read differently every month "
            "until the ledger covers several."
        )
        spy = headline.excess_mean.get("SPY")
        spy_median = headline.excess_median.get("SPY")
        lines.append(
            "The average one "
            f"{'beat' if (spy or 0) > 0 else 'lost to'} SPY by "
            f"{abs(spy or 0):.2f} points; the median one "
            f"{'beat' if (spy_median or 0) > 0 else 'lost to'} it by "
            f"{abs(spy_median or 0):.2f}."
        )
        if headline.mean > 0 and not headline.survives_trimming:
            lines.append(
                "**The mean does not survive trimming.** Drop the best 5% of trades and "
                f"it is {headline.trimmed:+.2f}%, so the positive average is the right "
                "tail rather than the typical trade."
            )
        if headline.top_5pct_share is not None:
            lines.append(
                f"The best 5% of trades supply {headline.top_5pct_share:.0f}% of the total."
            )

    # WHAT n IS REALLY WORTH, AND IT IS NOT WHAT IT SAYS IN THE TABLE. Ninety
    # names bought on the same morning and held the same twenty sessions are
    # ninety readings of ONE market move, not ninety independent bets. The
    # count in the table is trades; the count that governs how much the average
    # can be trusted is entry days, and on a young ledger that is a handful.
    # Printing the clusters is the only honest way to show it.
    for horizon in (20, RULEBOOK):
        subset = [s for s in rows if horizon in s.returns]
        if not subset:
            continue
        label = "sell on validation" if horizon == RULEBOOK else f"{horizon} sessions"
        clusters: dict[date, list] = defaultdict(list)
        for row_ in subset:
            clusters[row_.entry_date].append(row_)
        lines += [
            "",
            f"## Every entry day at {label}",
            "",
            "One row here is one morning's worth of signals, which is one market "
            "move. Read the number of rows, not the number of trades, when judging "
            "how much any average above is worth.",
            "",
            "| entry day | trades | mean | median | SPY itself | excess vs SPY |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for day in sorted(clusters):
            summary = summarise(clusters[day], horizon, names)
            if summary is None:
                continue
            lines.append(
                f"| {day.isoformat()} | {summary.n} | {fmt(summary.mean)} | "
                f"{fmt(summary.median)} | {fmt(summary.benchmark_mean.get('SPY'))} | "
                f"{fmt(summary.excess_mean.get('SPY'))} |"
            )

    # The audit, printed whether it passes or fails. A check that only speaks up
    # when it is unhappy is a check nobody remembers exists.
    total_checked = agree + len(disagree)
    lines += [
        "",
        "## Data check: are these the prices the digest printed?",
        "",
    ]
    # A TOLERANCE, BECAUSE A VENDOR CORRECTS THE ODD BAR. The first run of this
    # check found one name in 1,048 off by 0.9%, which is a late correction to a
    # daily bar rather than a misalignment, and the report called every number
    # in it suspect. A check that cries wolf at one row in a thousand gets
    # ignored at ten in a hundred, which is when it matters. So: exceptions are
    # listed always, and the verdict flips only when they stop being exceptions.
    rate = len(disagree) / total_checked if total_checked else 1.0
    if total_checked == 0:
        lines.append(
            f"No signal's date appeared in its own bars, which is itself wrong. "
            f"{unchecked} unchecked."
        )
    elif rate <= 0.01:
        lines.append(
            f"**Yes.** {agree} of {total_checked} signals match the close the digest "
            f"recorded on the same date, within 0.5%. {unchecked} could not be checked "
            "because the signal date is not in the returned history."
        )
    else:
        lines.append(
            f"**No, and every number above is suspect.** {len(disagree)} of "
            f"{total_checked} signals ({rate * 100:.1f}%) disagree with the close the "
            "digest recorded on the same date, so the returns are measured from prices "
            "the tool never claimed."
        )
    if disagree:
        lines += [
            "",
            f"{len(disagree)} exception{'' if len(disagree) == 1 else 's'}, "
            "which at this rate means a corrected bar rather than a broken join:"
            if rate <= 0.01
            else "First ten:",
            "",
            "| ticker | date | digest said | bars say | gap |",
            "|---|---|---:|---:|---:|",
        ]
        lines += [
            f"| {t} | {d} | {c:,.2f} | {v:,.2f} | {(v - c) / c * 100:+.2f}% |"
            for t, d, c, v in disagree[:10]
        ]

    by_screen: dict[str, list] = defaultdict(list)
    for out, row in scored:
        for screen in screens_of(row):
            by_screen[screen].append(out)
    if by_screen:
        lines += [
            "",
            "## By screen, at 20 sessions",
            "",
            "Descriptive. A screen looking better here is not a reason to promote it: "
            "these are overlapping subsets of one small sample, and choosing among them "
            "after the fact is the search that the September pre-registration exists to "
            "prevent.",
            "",
            "| screen | n | mean | median | trim best 5% |"
            + "".join(f" excess vs {n} |" for n in names),
            "|---|---:|---:|---:|---:|" + "---:|" * len(names),
        ]
        for screen, subset in sorted(by_screen.items()):
            summary = summarise(subset, 20, names)
            if summary is None:
                continue
            cells = "".join(f" {fmt(summary.excess_mean.get(n))} |" for n in names)
            lines.append(
                f"| {screen} | {summary.n} | {fmt(summary.mean)} | {fmt(summary.median)} | "
                f"{fmt(summary.trimmed)} |" + cells
            )

    if unreadable:
        lines += [
            "",
            "## Names with no bars",
            "",
            f"{len(set(unreadable))}: {', '.join(sorted(set(unreadable)))}. "
            "Delisted, renamed, or absent from the feed.",
        ]

    lines += [
        "",
        "---",
        "",
        "Benchmarks: " + "; ".join(f"**{n}**, {BENCHMARKS[n]}" for n in names) + ".",
        "",
        "Nothing here is financial advice or a verdict on any screen. It is a record of "
        "what the tool claimed and what happened next.",
        "",
    ]
    (args.out / "REPORT.md").write_text("\n".join(lines))
    print("\n".join(lines[: 14 + len(HORIZONS)]))
    print(f"\nwritten {args.out / 'scores.jsonl'} and {args.out / 'REPORT.md'}")


if __name__ == "__main__":
    main()
