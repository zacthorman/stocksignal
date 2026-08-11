"""The command line. Thin on purpose.

The CLI parses arguments, calls one function, and hands the result to a
renderer. If you ever find real logic creeping in here, that logic belongs in
`scanner.py` where it can be tested without spawning a process.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console

from stocksignal import __version__, signal_log
from stocksignal.backtest import TESTS_RUN
from stocksignal.backtest import render as render_backtest
from stocksignal.backtest import run as run_backtest
from stocksignal.config import DEFAULT_CONFIG, OUT_DIR, Config
from stocksignal.data import (
    PROVIDERS,
    DataError,
    get_source,
    shuffle_order,
    shuffle_returns,
)
from stocksignal.digest import render_markdown, render_terminal
from stocksignal.notify import deliver
from stocksignal.scanner import scan as run_scan

app = typer.Typer(add_completion=False, help="Mechanical stock and ETF screener.")
console = Console()
log = logging.getLogger(__name__)


def _load_watchlist(path: Path | None, cfg: Config) -> list[str]:
    """Read a watchlist file: one ticker a line, `#` starts a comment.

    The comment may be inline, not just at the start of a line, because
    `scripts/build_watchlist.py` writes the beta, price and volume that earned
    each symbol its place next to the symbol. Stripping only whole-line comments
    would turn `NVDA  # beta 2.4` into a ticker named "NVDA  # BETA 2.4" and the
    scan would report it as a data error rather than as a parsing mistake, which
    is the kind of bug you chase for an hour.
    """
    if path is None:
        return list(cfg.default_watchlist)
    out: list[str] = []
    for line in path.read_text().splitlines():
        symbol = line.split("#", 1)[0].strip().upper()
        if symbol:
            out.append(symbol)
    return out


@app.command()
def scan(
    watchlist: Path | None = typer.Option(
        None, "--watchlist", "-w", help="File with one ticker a line."
    ),
    tickers: str | None = typer.Option(None, "--tickers", "-t", help="Comma separated tickers."),
    offline: bool = typer.Option(True, "--offline/--live", help="Synthetic data, or real bars."),
    source_name: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="synthetic, yfinance or alpaca. Overrides --offline/--live.",
    ),
    save: bool = typer.Option(False, "--save", help="Write the digest to out/ as markdown."),
    log: bool = typer.Option(False, "--log", help="Append passing signals to signals.db."),
    telegram: bool = typer.Option(
        False,
        "--telegram",
        help="Send a phone-sized digest to Telegram. Needs TELEGRAM_BOT_TOKEN and "
        "TELEGRAM_CHAT_ID in the environment; skips quietly when they are absent.",
    ),
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

    if source_name is not None and source_name not in PROVIDERS:
        console.print(f"[red]Unknown source {source_name!r}. Choose one of: {', '.join(PROVIDERS)}")
        raise typer.Exit(code=1)

    resolved = source_name or ("synthetic" if offline else "yfinance")
    if resolved == "synthetic":
        # Note the backslash: rich reads square brackets as markup, so the
        # extras name has to be escaped or it vanishes from the output.
        console.print(
            "[dim]offline mode: synthetic data. Pass --live for real bars "
            r"(needs: uv pip install -e '.\[live]').[/dim]"
        )
    else:
        console.print(f"[dim]source: {resolved}[/dim]")

    try:
        source = get_source(provider=resolved)
    except DataError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
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

    if telegram:
        # Reported, never raised. The scan is the product; the message is a
        # convenience on top of it, and losing the convenience must not lose
        # the run or the exit code.
        outcome = deliver(report)
        colour = "green" if outcome.sent else "yellow"
        console.print(f"[{colour}]telegram[/{colour}] {outcome}")


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


@app.command()
def backtest(
    from_: str = typer.Option("2020-01-01", "--from", help="First simulated session."),
    to: str | None = typer.Option(None, "--to", help="Last simulated session, default today."),
    fit_end: str = typer.Option(
        "2023-12-31", "--fit-end", help="Last date any threshold was calibrated on."
    ),
    cost: float = typer.Option(0.2, "--cost", help="Round-trip cost in percent."),
    entry: str = typer.Option(
        "state",
        "--entry",
        help="state = fires every day the condition holds. confirmation = the "
        "course's rule, fires only on the day it first becomes true.",
    ),
    max_rsi: float | None = typer.Option(
        None, "--max-rsi", help="Gate 3: only enter at or below this RSI. Try 30, or 50."
    ),
    min_rr: float | None = typer.Option(
        None,
        "--min-rr",
        help="Gate 1: only enter when the distance to the next resistance divided "
        "by the distance to the next support clears this. 1.0 is the rulebook "
        "read literally; 2.0 is stricter than anything the course says.",
    ),
    exits: str = typer.Option(
        "hold",
        "--exits",
        help="hold = sell at the horizon regardless. stops = the rulebook's hard "
        "stop at previous support plus a 5% trailing stop after the target.",
    ),
    replicates: int = typer.Option(
        200,
        "--replicates",
        help="Random controls behind the percentile. 0 skips the test, which you "
        "should only do if you are not going to quote the result.",
    ),
    tests_run: int = typer.Option(
        TESTS_RUN,
        "--tests-run",
        help="How many variants have been tried against this data. Raises the bar, "
        "because one pass in twelve attempts is what chance produces.",
    ),
    shuffle_seed: int = typer.Option(
        1,
        "--shuffle-seed",
        help="Which shuffle to use. One permutation is one draw, so run several "
        "and read the spread rather than trusting a single reordering.",
    ),
    shuffle: bool = typer.Option(
        False,
        "--shuffle",
        help="Permute each ticker's daily returns before running. Destroys every "
        "time-series relationship while keeping volatility, price level and candle "
        "shape. Anything the screens still score here is mechanical.",
    ),
    source_name: str = typer.Option("alpaca", "--source", "-s"),
    pool: Path = typer.Option(Path("data/watchlist.txt"), "--pool", help="Candidate universe."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Walk a historical window forward and measure what the screens earned.

    `--pool` is the CANDIDATE list, not the traded list. The universe is rebuilt
    at every simulated session from bars dated on or before it, so price, volume
    and beta are all causal. What is not causal is which tickers are candidates
    at all: that file was screened on today's beta. The random arm is drawn from
    the same pool for exactly that reason, so it carries the identical bias and
    the screens-versus-random comparison survives it. The benchmark comparison
    does not, and the output says so.

    Read the IS IT LUCK block, not the means. Two arms differing by a point and a
    half tells you nothing on its own; the percentile tells you whether that
    difference is larger than the difference you get from picking names out of a
    hat, which is the only version of the question worth asking.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
    try:
        cfg = Config(
            trend_entry=entry,
            max_entry_rsi=max_rsi,
            min_reward_risk=min_rr,
            exit_rule=exits,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if source_name not in PROVIDERS:
        console.print(f"[red]Unknown source {source_name!r}.[/red]")
        raise typer.Exit(code=1)

    start = datetime.strptime(from_, "%Y-%m-%d").date()
    finish = datetime.strptime(to, "%Y-%m-%d").date() if to else date.today()
    split = datetime.strptime(fit_end, "%Y-%m-%d").date() if fit_end else None

    try:
        tickers = _load_watchlist(pool, cfg)
    except OSError as exc:
        # A missing pool file is a typo, not a crash. Printing a traceback for it
        # buries the one line that says which path was wrong.
        console.print(f"[red]Cannot read {pool}: {exc.strerror}.[/red]")
        console.print("[dim]Build one with: python scripts/build_watchlist.py[/dim]")
        raise typer.Exit(code=1) from exc
    if not tickers:
        console.print(f"[red]No candidates in {pool}.[/red]")
        raise typer.Exit(code=1)

    # Enough history to warm a 180-period average before the first simulated
    # session, plus the window itself, plus slack for holidays.
    sessions = int((finish - start).days * 252 / 365) + cfg.required_history + 40
    console.print(
        f"[dim]{len(tickers)} candidates, {sessions} sessions of history from {source_name}[/dim]"
    )

    source = get_source(provider=source_name)
    try:
        benchmark = source.history(cfg.beta_benchmark, days=sessions)
    except DataError as exc:
        console.print(f"[red]benchmark {cfg.beta_benchmark}: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    batch = getattr(source, "histories", None)
    if batch is not None:
        frames = batch(tickers, days=sessions)
    else:
        frames = {}
        for ticker in tickers:
            try:
                frames[ticker.upper()] = source.history(ticker, days=sessions)
            except DataError as exc:
                log.warning("skipping %s: %s", ticker, exc)

    usable = {t: df for t, df in frames.items() if len(df) > cfg.required_history}
    console.print(f"[dim]{len(usable)} of {len(tickers)} have enough history to simulate[/dim]\n")
    if not usable:
        console.print("[red]Nothing has enough history. Widen the window.[/red]")
        raise typer.Exit(code=1)

    if shuffle:
        console.print(
            f"[yellow]SHUFFLED (seed {shuffle_seed}): returns permuted in time. There is "
            "nothing here to predict, so a high percentile means the edge is mechanical."
            "\nThe price PATH changes, so the price floor bites differently and the "
            "universe will be smaller than the real one. Compare within this run, not "
            "against the real one.[/yellow]\n"
        )
        # ONE permutation, shared by every ticker and the benchmark. Per-ticker
        # permutations destroy every beta and empty the universe.
        order = shuffle_order(benchmark.index, seed=shuffle_seed)
        usable = {t: shuffle_returns(df, order) for t, df in usable.items()}
        benchmark = shuffle_returns(benchmark, order)

    report = run_backtest(
        usable,
        benchmark,
        cfg,
        start=start,
        end=finish,
        fit_end=split,
        cost_pct=cost,
        replicates=replicates,
        family_size=tests_run,
    )
    gate = f", RSI gate at {cfg.max_entry_rsi:g}" if cfg.max_entry_rsi else ", no RSI gate"
    room = (
        f", gate 1 at {cfg.min_reward_risk:g}:1 reward/risk"
        if cfg.min_reward_risk
        else ", no reward/risk gate"
    )
    console.print(f"[dim]entry rule: {cfg.trend_entry}{gate}{room}[/dim]")
    how = (
        f"stop at previous support, {cfg.trail_pct:g}% trail after target"
        if cfg.exit_rule == "stops"
        else "sell at the horizon regardless"
    )
    console.print(f"[dim]exit rule: {cfg.exit_rule}, {how}[/dim]\n")
    console.print(render_backtest(report))
    console.print(
        "\n[dim]Candidate pool came from a screen run today, so which tickers are "
        "eligible at all still carries selection bias. The random arm shares it; "
        f"{cfg.beta_benchmark} does not.[/dim]"
    )


if __name__ == "__main__":
    app()
