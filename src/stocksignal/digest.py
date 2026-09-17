"""Turning a ScanReport into something a human reads.

Two renderers, same report: a rich table for the terminal, and markdown for the
file you keep. Rendering lives here and nowhere else, so no screen is ever
tempted to print.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from stocksignal.balance_store import MISSING_STORE_NOTE, BalanceStore
from stocksignal.memory import ScanMemory
from stocksignal.scanner import ScanReport


def render_terminal(
    report: ScanReport,
    console: Console | None = None,
    balance: BalanceStore | None = None,
    memory: ScanMemory | None = None,
) -> None:
    console = console or Console()

    table = Table(title=f"Signals for {report.as_of.isoformat()}", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Ticker", style="bold")
    table.add_column("Close", justify="right")
    table.add_column("Score", justify="right")
    # THE BALANCE COLUMN NEVER FILTERS AND NEVER SORTS. It sits beside the score
    # rather than folded into it, because the two instruments are answering
    # different questions and the disagreement between them is the output. The
    # growth template looked at Tempus and saw revenue compounding at 83%; the
    # balance sheet looked at the same company and saw receivables compounding
    # at 101%. Neither number should be allowed to hide the other.
    table.add_column("Balance")
    # NEW is the only word in this table worth scanning for at 8am.
    table.add_column("Age")
    table.add_column("Why")

    if not report.signals:
        console.print(f"[yellow]No candidates passed on {report.as_of.isoformat()}.[/yellow]")
    else:
        for i, sig in enumerate(report.signals, start=1):
            why = list(sig.reasons)
            # One dim line rather than the failed screen's full argument. The
            # useful part is "this is a trend setup, not a breakout"; the
            # paragraph explaining why the breakout did not fire belongs in the
            # saved markdown, not in a table you scan in five seconds.
            if sig.not_firing:
                why.append(f"[dim](no {', '.join(sig.not_firing)} setup)[/dim]")
            verdict = balance.line(sig.ticker).split(",")[0] if balance else "no readings"
            age = "?"
            if memory:
                if memory.is_dismissed(sig.ticker):
                    age = "[dim]dismissed[/dim]"
                else:
                    r = memory.recurrence(sig.ticker)
                    age = "[bold]NEW[/bold]" if r and r.is_new else f"x{r.run_length}" if r else "?"
            table.add_row(
                str(i),
                sig.ticker,
                f"{sig.close:,.2f}",
                f"{sig.score:.2f}",
                verdict,
                age,
                "\n".join(why),
            )
        console.print(table)

    console.print(
        f"[dim]scanned {report.scanned} | passed {len(report.signals)} | "
        f"rejected {len(report.rejected)} | errors {len(report.errors)}[/dim]"
    )

    if report.rejected:
        console.print("\n[bold]Rejected[/bold]")
        for ticker, reason in report.rejected:
            console.print(f"  [red]x[/red] {ticker}: {reason}")

    if report.errors:
        console.print("\n[bold]Errors[/bold]")
        for ticker, reason in report.errors:
            console.print(f"  [red]![/red] {ticker}: {reason}")


def _candidate_block(
    lines: list[str],
    signals,
    balance: BalanceStore | None,
    memory: ScanMemory | None,
    start: int,
) -> int:
    for i, sig in enumerate(signals, start=start):
        lines.append(f"### {i}. {sig.ticker} at {sig.close:,.2f} (score {sig.score:.2f})")
        lines.append("")
        if memory:
            d = memory.dismissals.get(sig.ticker.upper())
            if d is not None and d.active_on(memory.as_of):
                lines.append(f"- _{d.describe(memory.as_of)}._")
            r = memory.recurrence(sig.ticker)
            if r is not None and not r.is_new:
                lines.append(f"- _{r.describe()}._")
        lines += [f"- {r}" for r in sig.reasons]
        if balance:
            lines.append(f"- **Balance sheet:** {balance.line(sig.ticker)}")
        if sig.not_firing:
            lines.append(f"- _Did not fire on: {', '.join(sig.not_firing)}._")
        lines.append("")
    return start + len(signals)


def render_markdown(
    report: ScanReport,
    balance: BalanceStore | None = None,
    memory: ScanMemory | None = None,
) -> str:
    lines = [
        f"# Signal digest, {report.as_of.isoformat()}",
        "",
        f"Scanned {report.scanned}. Passed {len(report.signals)}. "
        f"Rejected {len(report.rejected)}. Errors {len(report.errors)}.",
        "",
        # A MISSING STORE IS ANNOUNCED, NOT OMITTED. The whole argument for the
        # balance layer is that a price-to-sales reading cannot see cash, debt or
        # margins. A digest that quietly stopped carrying the second reading
        # would look identical to one where every company came back clean.
        balance.header(report.as_of) if balance else MISSING_STORE_NOTE,
        "",
    ]

    if report.signals:
        if memory is None:
            lines += ["## Candidates", ""]
            _candidate_block(lines, list(report.signals), balance, None, 1)
        else:
            # NEW FIRST, BECAUSE IT IS THE ONLY PART THAT IS NEWS. Eleven days
            # of the freeze had TXG, SSRM and CHYM on every single one, so a
            # digest that opens with the same three names every morning trains
            # you to stop reading it. The continuing names are still here in
            # full, they are just no longer the headline.
            new, continuing, dismissed = memory.split(list(report.signals))
            n = 1
            if new:
                lines += [f"## New today ({len(new)})", ""]
                n = _candidate_block(lines, new, balance, memory, n)
            else:
                lines += [
                    "## New today (0)",
                    "",
                    "Nothing passed today that was not already passing yesterday. "
                    "That is a real result and not an empty section: the screens "
                    "found no change worth your attention.",
                    "",
                ]
            if continuing:
                lines += [f"## Still passing ({len(continuing)})", ""]
                n = _candidate_block(lines, continuing, balance, memory, n)
            if dismissed:
                # MOVED, NOT REMOVED. A dismissal is Zac's judgement rather than
                # the tool's, which is why it is allowed to reorder the digest at
                # all, and it still has to be visible and it still has to expire.
                lines += [
                    f"## Dismissed ({len(dismissed)})",
                    "",
                    "You have already looked at these and said no. They stay here so "
                    "the decision is visible rather than silently shrinking the "
                    "universe, and each one returns when its dismissal expires.",
                    "",
                ]
                _candidate_block(lines, dismissed, balance, memory, n)
    else:
        lines += ["No candidates passed today.", ""]

    if report.rejected:
        lines += ["## Rejected", ""]
        lines += [f"- **{t}**: {why}" for t, why in report.rejected]
        lines.append("")

    if report.errors:
        lines += ["## Errors", ""]
        lines += [f"- **{t}**: {why}" for t, why in report.errors]
        lines.append("")

    lines += [
        "---",
        "",
        "Candidates only. Nothing here is a recommendation, and every entry and exit is a "
        "human decision.",
        "",
        "The balance reading never filters this list. A name flagged CONCERN or AVOID still "
        "appears, because the screens and the balance sheet answer different questions and "
        "the disagreement between them is the point.",
    ]
    return "\n".join(lines)
