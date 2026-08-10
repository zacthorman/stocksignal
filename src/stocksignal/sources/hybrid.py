"""Bars from one provider, fundamentals from another.

The rulebook says do not trade low-float stocks and always check the float.
Alpaca is a broker, not a fundamentals vendor, so moving to it for bars silently
switched that rule off: every signal in the first live Alpaca scan read "float
unknown, check it by hand", which is honest but means the gate stopped gating.

Neither provider does both jobs well. Alpaca has fast batched bars and no
fundamentals; yfinance has fundamentals and gets throttled if you ask it for
bars three hundred times a morning. So use each for what it is good at.

The float cache is the thing that makes this cheap. Free float changes a few
times a year, on a share issue or a lockup expiry, so a value fetched last week
is still true. Caching for `cache_days` turns "one yfinance call per ticker per
scan", which is exactly the pattern that got throttled, into one call per ticker
per month.

    source = HybridSource(bars=AlpacaSource(), fundamentals=YFinanceSource())

Anything other than `shares_float` is delegated straight through to the bars
source, including `histories`, so the scanner's batch path still works and a
wrapped source that cannot batch still reports that it cannot.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from stocksignal.data import PriceSource

log = logging.getLogger(__name__)

DEFAULT_CACHE = Path("cache/floats.json")
DEFAULT_CACHE_DAYS = 30


class HybridSource:
    """A PriceSource that takes bars from one provider and float from another."""

    def __init__(
        self,
        bars: PriceSource,
        fundamentals: PriceSource | None = None,
        cache_path: Path | None = None,
        cache_days: int = DEFAULT_CACHE_DAYS,
        clock: callable = time.time,
    ):
        self._bars = bars
        self._fundamentals = fundamentals
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE
        self.cache_days = cache_days
        self._clock = clock
        self._cache: dict[str, dict] | None = None

    def __getattr__(self, name: str):
        """Delegate everything unclaimed to the bars source.

        Deliberately `__getattr__` rather than a set of forwarding methods, so
        that `hasattr(source, "histories")` is true exactly when the wrapped
        source can batch. The scanner uses that check to decide whether to
        prefetch, and a hand-written `histories` here would lie about a
        provider that cannot do it.
        """
        return getattr(self._bars, name)

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        return self._bars.history(ticker, days=days)

    # -- float, with a long cache -------------------------------------------

    def _load_cache(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        try:
            self._cache = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            self._cache = {}
        return self._cache

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache or {}, indent=1, sort_keys=True))
        except OSError as exc:  # pragma: no cover - disk problems are not fatal here
            log.warning("could not write the float cache: %s", exc)

    def shares_float(self, ticker: str) -> float | None:
        """Free float, from the fundamentals provider, cached for `cache_days`.

        A cached `None` counts as an answer and is honoured for the full window.
        Providers do not have a float for every symbol, and retrying a known
        miss on every scan is how you spend a rate limit learning nothing.
        """
        if self._fundamentals is None:
            return None

        key = ticker.upper()
        cache = self._load_cache()
        entry = cache.get(key)
        if entry is not None:
            age_days = (self._clock() - entry.get("at", 0)) / 86_400
            if age_days < self.cache_days:
                return entry.get("value")

        try:
            value = self._fundamentals.shares_float(ticker)
        except Exception as exc:  # noqa: BLE001 - enrichment must never fail a scan
            log.warning("float lookup failed for %s: %s", ticker, exc)
            return entry.get("value") if entry else None

        cache[key] = {"value": value, "at": self._clock()}
        self._save_cache()
        return value
