"""Glue: fetch bars, build a quote, run the screens, sort what survived.

The scanner deliberately knows almost nothing. It does not know how to fetch,
how to score, or how to print. It knows the order of operations. When a module
knows only the order of operations, adding a screen is one line and changing a
data provider is zero lines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.data import DataError, PriceSource
from stocksignal.indicators import average_volume, beta
from stocksignal.models import Quote, Signal
from stocksignal.screens import screen_breakout, screen_tradability, screen_trend

log = logging.getLogger(__name__)

# HARD_GATE must pass before anything else runs, because there is no point
# scoring a setup on something you cannot trade.
#
# SCORING_SCREENS are alternative setups, not conditions the same trade must
# satisfy at once: a ticker needs to clear the hard gate and clear at least
# one of them. A trend read and a breakout are two different reasons to take
# a trade, so a ticker in a clean uptrend with no breakout today, or one
# breaking out before its trend has confirmed, both still qualify. Requiring
# all of them would mean a signal only ever fires on the rare ticker doing
# everything at once.
HARD_GATE = screen_tradability
SCORING_SCREENS = (screen_trend, screen_breakout)


@dataclass(frozen=True)
class ScanReport:
    """Everything one scan produced, including what it rejected and why."""

    as_of: date
    signals: tuple[Signal, ...]
    rejected: tuple[tuple[str, str], ...]  # (ticker, first failure reason)
    errors: tuple[tuple[str, str], ...]  # (ticker, error message)

    @property
    def scanned(self) -> int:
        return len(self.signals) + len(self.rejected) + len(self.errors)


def load_benchmark(source: PriceSource, cfg: Config) -> pd.Series | None:
    """Closing prices for the beta benchmark, fetched once for a whole scan.

    Returns None rather than raising. A provider hiccup on the benchmark should
    cost you the beta reading and nothing else, because the alternative is that
    one failed request takes down a scan of four hundred tickers. Beta then
    reads as unknown, which the tradability gate already treats as a warning
    rather than a rejection.
    """
    try:
        return source.history(cfg.beta_benchmark, days=cfg.required_history)["close"]
    except Exception as exc:  # noqa: BLE001 - benchmark is enrichment, never fatal
        log.warning("benchmark %s unavailable, beta will read unknown: %s", cfg.beta_benchmark, exc)
        return None


def prefetch(
    tickers: list[str], source: PriceSource, cfg: Config
) -> dict[str, pd.DataFrame] | None:
    """Pull every ticker in one go, if the source knows how. None if it does not.

    `PriceSource` only promises `history`, one ticker at a time. Some providers
    can do far better: Alpaca's bars endpoint takes a list of symbols and
    paginates, so 256 tickers cost a handful of requests instead of 256. Sources
    advertise that by having a `histories` method, and the ones that cannot are
    unaffected.

    A failed batch returns None rather than raising, so the scan drops back to
    fetching one at a time. Slower is a much better outcome than a whole
    watchlist lost to one bad response.
    """
    batch = getattr(source, "histories", None)
    if batch is None:
        return None
    try:
        frames = batch(tickers, days=cfg.required_history)
    except Exception as exc:  # noqa: BLE001 - fall back rather than fail the run
        log.warning("batch fetch failed, falling back to one at a time: %s", exc)
        return None
    log.info("batch fetched %d of %d tickers", len(frames), len(tickers))
    return frames


def take_frame(
    ticker: str,
    frames: dict[str, pd.DataFrame] | None,
    source: PriceSource,
    cfg: Config,
) -> pd.DataFrame:
    """One ticker's bars, from the batch if there was one.

    A symbol missing from a successful batch is a symbol the provider had no
    data for, so it raises rather than quietly refetching. Retrying it one at a
    time would spend a request to be told the same thing.
    """
    if frames is None:
        return source.history(ticker, days=cfg.required_history)
    df = frames.get(ticker.upper())
    if df is None:
        raise DataError(f"{ticker}: no rows in the batch response")
    return df


def build_quote(
    ticker: str,
    df: pd.DataFrame,
    cfg: Config,
    shares_float: float | None,
    benchmark: pd.Series | None = None,
) -> Quote:
    last = df.iloc[-1]
    return Quote(
        ticker=ticker.upper(),
        as_of=df.index[-1].date(),
        close=float(last["close"]),
        avg_volume=average_volume(df["volume"], cfg.avg_volume_window),
        latest_volume=float(last["volume"]),
        shares_float=shares_float,
        beta=None if benchmark is None else beta(df["close"], benchmark, cfg.beta_window),
    )


def scan_ticker(
    ticker: str,
    source: PriceSource,
    cfg: Config = DEFAULT_CONFIG,
    benchmark: pd.Series | None = None,
) -> Signal | None:
    """Run every screen against one ticker.

    Returns None if it fails the hard gate, or if it clears none of the
    scoring screens at all.

    `benchmark` is optional so a caller checking a single ticker does not pay
    for a second fetch it may not need. Omit it and beta reads as unknown.
    """
    df = source.history(ticker, days=cfg.required_history)
    quote = build_quote(ticker, df, cfg, source.shares_float(ticker), benchmark)

    gate = HARD_GATE(df, quote, cfg)
    if not gate.passed:
        return None

    scoring_results = [screen(df, quote, cfg) for screen in SCORING_SCREENS]
    if not any(r.passed for r in scoring_results):
        return None

    # Total score sums whichever setups actually fired; a failed scoring
    # screen contributes 0 by convention, so this needs no filtering. The gate
    # contributes a small liquidity tiebreak so that two equally strong setups
    # rank by tradability.
    setup_score = sum(r.score for r in scoring_results)
    total = round(setup_score + gate.score * 0.1, 4)

    return Signal(
        ticker=quote.ticker,
        as_of=quote.as_of,
        close=quote.close,
        score=total,
        results=tuple([gate, *scoring_results]),
    )


def scan(tickers: list[str], source: PriceSource, cfg: Config = DEFAULT_CONFIG) -> ScanReport:
    """Scan a watchlist. One bad ticker never takes down the run."""
    signals: list[Signal] = []
    rejected: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    as_of = date.today()

    # Fetched once, before the loop. Beta needs a benchmark series per ticker,
    # and pulling SPY four hundred times to answer the same question four
    # hundred times is how you get rate limited by a free provider.
    benchmark = load_benchmark(source, cfg)
    frames = prefetch(tickers, source, cfg)

    for ticker in tickers:
        try:
            df = take_frame(ticker, frames, source, cfg)
            quote = build_quote(ticker, df, cfg, source.shares_float(ticker), benchmark)
            as_of = quote.as_of

            gate = HARD_GATE(df, quote, cfg)
            if not gate.passed:
                rejected.append((quote.ticker, gate.reasons[0] if gate.reasons else "failed gate"))
                continue

            scoring_results = [s(df, quote, cfg) for s in SCORING_SCREENS]
            if not any(r.passed for r in scoring_results):
                reason = "; ".join(
                    f"{r.name}: {r.reasons[0]}" for r in scoring_results if r.reasons
                )
                rejected.append((quote.ticker, reason or "no scoring screen passed"))
                continue

            setup_score = sum(r.score for r in scoring_results)
            signals.append(
                Signal(
                    ticker=quote.ticker,
                    as_of=quote.as_of,
                    close=quote.close,
                    score=round(setup_score + gate.score * 0.1, 4),
                    results=tuple([gate, *scoring_results]),
                )
            )
        except DataError as exc:
            log.warning("data problem on %s: %s", ticker, exc)
            errors.append((ticker.upper(), str(exc)))
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the scan
            log.exception("unexpected failure on %s", ticker)
            errors.append((ticker.upper(), f"{type(exc).__name__}: {exc}"))

    signals.sort(key=lambda s: s.score, reverse=True)
    return ScanReport(
        as_of=as_of,
        signals=tuple(signals),
        rejected=tuple(rejected),
        errors=tuple(errors),
    )
