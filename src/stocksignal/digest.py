"""Turning a ScanReport into something a human reads.

Two renderers, same report: a rich table for the terminal, and markdown for the
file you keep. Rendering lives here and nowhere else, so no screen is ever
tempted to print.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from stocksignal.scanner import ScanReport


def render_terminal(report: ScanReport, console: Console | None = None) -> None:
    console = console or Console()

    table = Table(title=f"Signals for {report.as_of.isoformat()}", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Ticker", style="bold")
    table.add_column("Close", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Why")

    if not report.signals:
        console.print(f"[yellow]No candidates passed on {report.as_of.isoformat()}.[/yellow]")
    else:
        for i, sig in enumerate(report.signals, start=1):
            table.add_row(
                str(i),
                sig.ticker,
                f"{sig.close:,.2f}",
                f"{sig.score:.2f}",
                "\n".join(sig.reasons),
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


def render_markdown(report: ScanReport) -> str:
    lines = [
        f"# Signal digest, {report.as_of.isoformat()}",
        "",
        f"Scanned {report.scanned}. Passed {len(report.signals)}. "
        f"Rejected {len(report.rejected)}. Errors {len(report.errors)}.",
        "",
    ]

    if report.signals:
        lines += ["## Candidates", ""]
        for i, sig in enumerate(report.signals, start=1):
            lines.append(f"### {i}. {sig.ticker} at {sig.close:,.2f} (score {sig.score:.2f})")
            lines.append("")
            lines += [f"- {r}" for r in sig.reasons]
            lines.append("")
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
    ]
    return "\n".join(lines)
