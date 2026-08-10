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

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class DataError(RuntimeError):
    """Raised when a source cannot produce usable bars for a ticker."""


def last_business_day(day: pd.Timestamp) -> pd.Timestamp:
    """The given day, rolled back to Friday if it lands on a weekend.

    This exists because of a bug that only fires at weekends. `pd.bdate_range` given
    a Saturday or Sunday as `end` returns one row fewer than `periods` asked for, so
    a synthetic history built on a Sunday came out 119 rows long while the arrays
    beside it were 120, and pandas refused to build the frame. Midweek it was fine.

    Kept as its own function purely so it can be tested without pretending it is a
    different day, which is the only honest way to test date-dependent behaviour.
    """
    normalised = day.normalize()
    if normalised.weekday() >= 5:
        return normalised - pd.offsets.BDay(1)
    return normalised


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

    EVERY TICKER SHARES A MARKET FACTOR. This used to generate each ticker as an
    independent random walk, which is not a simplification of an equity market so
    much as a contradiction of one. Real stocks move together, and beta is the
    measurement of how much. Independent walks give every ticker a beta near
    zero, so once the beta gate went in, an offline scan rejected the entire
    universe and `make scan` printed nothing at all, forever.

    The tempting fix was to disable the beta gate for synthetic runs. That would
    have left the newest code in the project as the one path the offline smoke
    test never touched. Modelling the thing properly is barely more work:

        ticker return = beta x market return + idiosyncratic noise

    with each ticker's beta derived from its own name, so it stays reproducible
    while spreading across `BETA_RANGE`. An offline scan now gives a realistic
    mix of names that clear the beta floor and names that do not, which is what
    a smoke test is supposed to look like.

    The market factor is drawn from the seed alone rather than from any ticker,
    so it is the same series for every symbol in a run. That is what makes the
    correlation real rather than decorative.

    One caveat worth knowing. The market series is generated per call at the
    requested length, so asking for 100 days and 250 days produces different
    market paths. Within a single scan every ticker uses the same `days`, so
    they stay mutually consistent, which is all that matters here.

    THE DEFAULT SEED IS CHOSEN, NOT ARBITRARY. Because every ticker now rides one
    market factor, that factor's direction decides the whole run: on a seed whose
    market drifts down, no ticker is above its averages and the digest is empty
    again for a completely different reason. Seed 7 was one of those. 23 gives a
    market that rises overall, so a demo watchlist splits roughly evenly between
    signals and rejections, and the rejections come from both the beta gate and
    the trend screen. That is what makes `make scan` worth running.

    It is a presentation choice about fake data and nothing more. No real
    decision should ever rest on it, and any seed can be passed explicitly.
    """

    # Spread wide enough that some tickers clear a beta floor of 2 and some do
    # not, because a smoke test where everything passes tests nothing.
    BETA_RANGE = (0.4, 4.0)

    def __init__(
        self,
        seed: int = 23,
        start_price: float = 100.0,
        drift: float = 0.0004,
        benchmark: str = "SPY",
    ):
        self.seed = seed
        self.start_price = start_price
        self.drift = drift
        self.benchmark = benchmark.upper()

    def _rng(self, ticker: str) -> np.random.Generator:
        # Fold the ticker into the seed so different tickers differ, but any
        # given ticker is reproducible across runs and machines.
        blended = (self.seed * 1_000_003 + sum(ord(c) * (i + 1) for i, c in enumerate(ticker))) % (
            2**32
        )
        return np.random.default_rng(blended)

    def _market_returns(self, days: int) -> np.ndarray:
        """The one series every ticker is a leveraged, noisy version of."""
        rng = np.random.default_rng(self.seed % (2**32))
        return rng.normal(loc=self.drift, scale=0.011, size=days)

    def beta_for(self, ticker: str) -> float:
        """This ticker's beta, fixed by its name so it never moves between runs.

        The benchmark is the market by definition, so it gets exactly 1.0. An
        earlier version treated it like any other symbol and handed it 0.48,
        which quietly inflated every measured beta in the synthetic world by
        about a quarter: beta is measured *against* the benchmark, so if the
        benchmark is not the market, nothing else can be right either.

        A SHA-256 digest rather than a weighted character sum. The character
        sum was close enough to linear that similar strings landed on similar
        betas, so AAA through HHH all came out between 2.4 and 3.0 and an
        offline scan had no rejections to show. Python's own `hash` is not an
        option here: it is salted per process, so the same ticker would get a
        different beta on every run.
        """
        if ticker.upper() == self.benchmark:
            return 1.0
        low, high = self.BETA_RANGE
        digest = int.from_bytes(hashlib.sha256(ticker.upper().encode()).digest()[:4], "big")
        return low + (digest % 10_000) / 9_999 * (high - low)

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        rng = self._rng(ticker)
        # Business days ending on the most recent trading day, so the "latest" bar is
        # always the last row.
        idx = pd.bdate_range(end=last_business_day(pd.Timestamp.today()), periods=days)

        market = self._market_returns(days)
        beta = self.beta_for(ticker)
        # The benchmark is the market itself, with no story of its own. Giving it
        # idiosyncratic noise would put variance in the denominator of every beta
        # calculation and drag all of them below their true value.
        if ticker.upper() == self.benchmark:
            shocks = market
        else:
            # Noise scaled by beta, so a high-beta name is not merely a magnified
            # index. Real volatile stocks have more of their own story too, not
            # just more of the market's.
            idiosyncratic = rng.normal(loc=0.0, scale=0.008 * beta, size=days)
            shocks = beta * market + idiosyncratic

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


PROVIDERS = ("synthetic", "yfinance", "alpaca")


def get_source(
    offline: bool = True,
    cache_dir: Path | None = None,
    provider: str | None = None,
) -> PriceSource:
    """Pick a source. Offline is the default so the tool always works.

    `provider` names one explicitly and wins when given. `offline` is kept as
    the older two-way switch so existing callers and tests are unaffected:
    True means synthetic, False means yfinance.

    Alpaca is imported inside the branch rather than at module scope, because it
    needs `requests` from the `alpaca` extra and this module has to keep
    importing cleanly on a bare install. A missing extra should be an error when
    you ask for that provider, not when you import the package.
    """
    if provider is None:
        provider = "synthetic" if offline else "yfinance"

    if provider == "synthetic":
        return SyntheticSource()
    if provider == "yfinance":
        return YFinanceSource(cache_dir=cache_dir)
    if provider == "alpaca":
        from stocksignal.sources import AlpacaSource

        return AlpacaSource()

    raise DataError(f"unknown provider {provider!r}, expected one of {', '.join(PROVIDERS)}")
