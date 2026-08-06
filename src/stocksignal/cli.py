"""The command line. Thin on purpose.

The CLI parses arguments, calls one function, and hands the result to a
renderer. If you ever find real logic creeping in here, that logic belongs in
`scanner.py` where it can be tested without spawning a process.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console

from stocksignal import __version__, signal_log
from stocksignal.config import DEFAULT_CONFIG, OUT_DIR, Config
from stocksignal.data import get_source
from stocksignal.digest import render_markdown, render_terminal
from stocksignal.scanner import scan as run_scan

app = typer.Typer(add_completion=False, help="Mechanical stock and ETF screener.")
console = Console()


def _load_watchlist(path: Path | None, cfg: Config) -> list[str]:
    if path is None:
        return list(cfg.default_watchlist)
    lines = path.read_text().splitlines()
    return [ln.strip().upper() for ln in lines if ln.strip() and not ln.startswith("#")]


@app.command()
def scan(
    watchlist: Path | None = typer.Option(
        None, "--watchlist", "-w", help="File with one ticker a line."
    ),
    tickers: str | None = typer.Option(None, "--tickers", "-t", help="Comma separated tickers."),
    offline: bool = typer.Option(True, "--offline/--live", help="Synthetic data, or real bars."),
    save: bool = typer.Option(False, "--save", help="Write the digest to out/ as markdown."),
    log: bool = typer.Option(False, "--log", help="Append passing signals to signals.db."),
    fast: int = typer.Option(DEFAULT_CONFIG.sma_fast, help="Fast SMA period."),
    slow: int = typer.Option(DEFAULT_CONFIG.sma_slow, help="Slow SMA period."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run every screen over a watchlist and print the digest."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = Config(sma_fast=fast, sma_slow=slow)
    symbols = (
        [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if tickers
        else _load_watchlist(watchlist, cfg)
    )
    if not symbols:
        console.print("[red]No tickers to scan.[/red]")
        raise typer.Exit(code=1)

    if offline:
        # Note the backslash: rich reads square brackets as markup, so the
        # extras name has to be escaped or it vanishes from the output.
        console.print(
            "[dim]offline mode: synthetic data. Pass --live for real bars "
            r"(needs: uv pip install -e '.\[live]').[/dim]"
        )

    source = get_source(offline=offline)
    report = run_scan(symbols, source, cfg)
    render_terminal(report, console)

    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"digest-{report.as_of.isoformat()}.md"
        out.write_text(render_markdown(report))
        console.print(f"[green]written[/green] {out}")

    if log:
        n = signal_log.log_signals(report.signals)
        console.print(f"[green]logged[/green] {n} signal(s) to signals.db")


@app.command()
def history(limit: int = typer.Option(20, "--limit", "-n")) -> None:
    """Show the most recent rows from the signal log."""
    rows = signal_log.recent(limit)
    if not rows:
        console.print("[yellow]Signal log is empty. Run a scan with --log first.[/yellow]")
        return
    for r in rows:
        console.print(
            f"[dim]{r['as_of']}[/dim] [bold]{r['ticker']}[/bold] "
            f"@ {r['close']:,.2f}  score {r['score']:.2f}  [dim]{r['screens']}[/dim]"
        )


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"stocksignal {__version__}")


if __name__ == "__main__":
    app()
