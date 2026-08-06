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
from stocksignal.indicators import average_volume
from stocksignal.models import Quote, ScreenResult, Signal
from stocksignal.screens import screen_tradability, screen_trend

log = logging.getLogger(__name__)

# Screens are listed here in the order they run. The first entry is the hard
# gate: if it fails, the rest are skipped, because there is no point scoring the
# trend on something you cannot trade.
HARD_GATE = screen_tradability
SCORING_SCREENS = (screen_trend,)


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


def build_quote(ticker: str, df: pd.DataFrame, cfg: Config, shares_float: float | None) -> Quote:
    last = df.iloc[-1]
    return Quote(
        ticker=ticker.upper(),
        as_of=df.index[-1].date(),
        close=float(last["close"]),
        avg_volume=average_volume(df["volume"], cfg.avg_volume_window),
        latest_volume=float(last["volume"]),
        shares_float=shares_float,
    )


def scan_ticker(ticker: str, source: PriceSource, cfg: Config = DEFAULT_CONFIG) -> Signal | None:
    """Run every screen against one ticker. Returns None if it fails a hard gate."""
    df = source.history(ticker, days=max(250, cfg.min_history_days))
    quote = build_quote(ticker, df, cfg, source.shares_float(ticker))

    gate = HARD_GATE(df, quote, cfg)
    if not gate.passed:
        return None

    results: list[ScreenResult] = [gate]
    for screen in SCORING_SCREENS:
        results.append(screen(df, quote, cfg))

    if not all(r.passed for r in results):
        return None

    # Total score weights the scoring screens; the gate contributes a small
    # liquidity tiebreak so that two equally strong trends rank by tradability.
    trend_score = sum(r.score for r in results if r.name != gate.name)
    total = round(trend_score + gate.score * 0.1, 4)

    return Signal(
        ticker=quote.ticker,
        as_of=quote.as_of,
        close=quote.close,
        score=total,
        results=tuple(results),
    )


def scan(
    tickers: list[str], source: PriceSource, cfg: Config = DEFAULT_CONFIG
) -> ScanReport:
    """Scan a watchlist. One bad ticker never takes down the run."""
    signals: list[Signal] = []
    rejected: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    as_of = date.today()

    for ticker in tickers:
        try:
            df = source.history(ticker, days=max(250, cfg.min_history_days))
            quote = build_quote(ticker, df, cfg, source.shares_float(ticker))
            as_of = quote.as_of

            gate = HARD_GATE(df, quote, cfg)
            if not gate.passed:
                rejected.append((quote.ticker, gate.reasons[0] if gate.reasons else "failed gate"))
                continue

            results = [gate] + [s(df, quote, cfg) for s in SCORING_SCREENS]
            failed = [r for r in results if not r.passed]
            if failed:
                first = failed[0]
                rejected.append((quote.ticker, first.reasons[0] if first.reasons else first.name))
                continue

            trend_score = sum(r.score for r in results if r.name != gate.name)
            signals.append(
                Signal(
                    ticker=quote.ticker,
                    as_of=quote.as_of,
                    close=quote.close,
                    score=round(trend_score + gate.score * 0.1, 4),
                    results=tuple(results),
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
