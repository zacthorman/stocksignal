"""Where price data comes from.

Two sources ship with the scaffold:

* `SyntheticSource` invents deterministic price histories from a seed. It needs
  no network and no API key, so the tests and your first run work instantly.
* `YFinanceSource` pulls real daily bars from Yahoo Finance.

Both satisfy the same `PriceSource` protocol, so the scanner never knows or
cares which one it is holding. This is the single most useful structural idea in
the whole repo: the thing that fetches data is swappable, so a rate limit, a
dead provider or a paid upgrade is a one-line change at the edge rather than a
rewrite through the middle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class DataError(RuntimeError):
    """Raised when a source cannot produce usable bars for a ticker."""


def validate_bars(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Fail loudly and early on malformed data.

    Half the pain in any data project is a bad frame travelling three modules
    before it explodes somewhere unrelated. Check it at the door instead.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"{ticker}: missing columns {missing}")
    if df.empty:
        raise DataError(f"{ticker}: no rows returned")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise DataError(f"{ticker}: index must be a DatetimeIndex, got {type(df.index).__name__}")
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    if df[list(REQUIRED_COLUMNS)].isna().all().any():
        raise DataError(f"{ticker}: a required column is entirely null")
    return df


@runtime_checkable
class PriceSource(Protocol):
    """Anything that can hand back daily bars for a ticker."""

    def history(self, ticker: str, days: int) -> pd.DataFrame:
        """Return a DatetimeIndex frame with open/high/low/close/volume columns."""
        ...

    def shares_float(self, ticker: str) -> float | None:
        """Free float in shares, or None when the source does not know."""
        ...


class SyntheticSource:
    """Deterministic fake market data. Same ticker in, same bars out, forever.

    Useful for three things: running the tool before you have any credentials,
    writing tests that cannot flake, and deliberately constructing a ticker that
    should pass or fail a screen so you can prove the screen works.
    """

    def __init__(self, seed: int = 7, start_price: float = 100.0, drift: float = 0.0004):
        self.seed = seed
        self.start_price = start_price
        self.drift = drift

    def _rng(self, ticker: str) -> np.random.Generator:
        # Fold the ticker into the seed so different tickers differ, but any
        # given ticker is reproducible across runs and machines.
        blended = (self.seed * 1_000_003 + sum(ord(c) * (i + 1) for i, c in enumerate(ticker))) % (
            2**32
        )
        return np.random.default_rng(blended)

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        rng = self._rng(ticker)
        # Business days ending today, so the "latest" bar is always the last row.
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
        shocks = rng.normal(loc=self.drift, scale=0.018, size=days)
        close = self.start_price * np.exp(np.cumsum(shocks))
        intraday = np.abs(rng.normal(0, 0.008, size=days))
        df = pd.DataFrame(
            {
                "open": close * (1 - intraday / 2),
                "high": close * (1 + intraday),
                "low": close * (1 - intraday),
                "close": close,
                "volume": rng.lognormal(mean=13.2, sigma=0.45, size=days).round(),
            },
            index=idx,
        )
        return validate_bars(df, ticker)

    def shares_float(self, ticker: str) -> float | None:
        rng = self._rng(ticker)
        return float(rng.integers(5_000_000, 900_000_000))


class YFinanceSource:
    """Real daily bars from Yahoo Finance, with an on-disk CSV cache.

    yfinance is an unofficial scraper. It is free and it is fine for daily bars,
    but it rate limits and it occasionally changes shape underneath you. That is
    exactly why it sits behind the protocol.
    """

    def __init__(self, cache_dir: Path | None = None, cache_hours: int = 12):
        self.cache_dir = Path(cache_dir) if cache_dir else Path("cache")
        self.cache_hours = cache_hours

    def _cache_path(self, ticker: str, days: int) -> Path:
        return self.cache_dir / f"{ticker.upper()}_{days}d.csv"

    def _cached(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        age_hours = (pd.Timestamp.now().timestamp() - path.stat().st_mtime) / 3600
        if age_hours > self.cache_hours:
            return None
        return pd.read_csv(path, index_col=0, parse_dates=True)

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        path = self._cache_path(ticker, days)
        cached = self._cached(path)
        if cached is not None:
            return validate_bars(cached, ticker)

        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise DataError(
                "yfinance is not installed. Run: uv pip install -e '.[live]' "
                "or scan with --offline."
            ) from exc

        # A calendar-day buffer, because `days` here means trading sessions.
        raw = yf.Ticker(ticker).history(period=f"{int(days * 1.6) + 10}d", auto_adjust=True)
        if raw.empty:
            raise DataError(f"{ticker}: yfinance returned no rows")
        raw = raw.rename(columns=str.lower)[list(REQUIRED_COLUMNS)].tail(days)
        raw.index = pd.to_datetime(raw.index).tz_localize(None)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        raw.to_csv(path)
        return validate_bars(raw, ticker)

    def shares_float(self, ticker: str) -> float | None:
        try:
            import yfinance as yf
        except ImportError:  # pragma: no cover - depends on the extra
            return None
        try:
            info = yf.Ticker(ticker).get_info()
        except Exception:
            # Deliberately broad: this is a best-effort enrichment, and a
            # provider hiccup here must never take down a whole scan.
            return None
        value = info.get("floatShares") or info.get("sharesOutstanding")
        return float(value) if value else None


def get_source(offline: bool = True, cache_dir: Path | None = None) -> PriceSource:
    """Pick a source. Offline is the default so the tool always works."""
    return SyntheticSource() if offline else YFinanceSource(cache_dir=cache_dir)
