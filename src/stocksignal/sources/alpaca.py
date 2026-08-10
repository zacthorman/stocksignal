"""Daily bars from Alpaca's market data API.

Why this exists. yfinance costs one HTTP request per ticker, so a scan over a
256-name watchlist is 256 requests every morning and a universe rebuild is
several thousand. That gets throttled, which is not a bug in yfinance so much as
using a convenience wrapper for a job it was never shaped for.

Alpaca's bars endpoint takes a genuine list of symbols in one request and
paginates the response, so the same 256 tickers cost a handful of calls rather
than 256. The free tier allows 200 requests a minute, which is more headroom
than this project can use.

THE ONE THING THAT WILL SILENTLY RUIN YOUR DATA. The `feed` parameter defaults to
"best available for your subscription", and on a free account that means IEX:
a single exchange carrying roughly 2% of US volume. Bars still arrive, prices
still look plausible, and volume comes back around fiftyfold too low. The
tradability gate's 100k volume floor would then reject almost the entire market
and nothing would error. `feed="sip"` is passed explicitly on every request for
that reason. Free accounts may query SIP for anything older than 15 minutes,
which covers every use this project has.

Credentials come from the environment, never the repo:

    export ALPACA_API_KEY_ID=...
    export ALPACA_API_SECRET_KEY=...

What this source does NOT provide is `shares_float`. Alpaca is a broker, not a
fundamentals vendor, and there is no float in the bars API. It returns None,
which the tradability gate already treats as "unknown, check by hand" rather
than as a rejection. If you want the float check back, keep a YFinanceSource
alongside purely for that call: float changes a few times a year, so it caches
almost indefinitely.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from stocksignal.data import DataError, validate_bars

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"

MARKET_TZ = ZoneInfo("America/New_York")

# US equities close at 16:00 ET. The extra quarter hour is settling time: the
# daily bar keeps moving for a few minutes after the bell as late prints land.
SESSION_FINAL_AFTER = time(16, 15)

# Alpaca caps a single response and hands back a token for the rest. 10000 is
# the documented ceiling; asking for more is not an error, it is just ignored.
PAGE_LIMIT = 10_000

# Calendar days fetched per trading session asked for. Weekends and holidays
# mean roughly 252 sessions a year against 365 days, so 1.5 plus a fortnight of
# slack is comfortable without pulling years of surplus.
CALENDAR_PADDING = 1.5
CALENDAR_SLACK_DAYS = 14


def _default_fetch(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict:
    import requests

    response = requests.get(url, params=params, headers=headers, timeout=30)
    if response.status_code == 401:
        raise DataError("Alpaca rejected the credentials (401). Check the key and secret.")
    if response.status_code == 429:
        raise DataError("Alpaca rate limit hit (429). Back off and retry.")
    if response.status_code >= 400:
        raise DataError(f"Alpaca returned {response.status_code}: {response.text[:200]}")
    return response.json()


class AlpacaSource:
    """A PriceSource backed by Alpaca. Satisfies the same protocol as the others.

    `fetch` is injectable so the tests can exercise pagination, the SIP feed
    parameter and the error paths without a network or an account.
    """

    def __init__(
        self,
        key_id: str | None = None,
        secret_key: str | None = None,
        feed: str = "sip",
        fetch: Callable[[str, dict, dict], dict] = _default_fetch,
        drop_partial_bars: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(MARKET_TZ),
    ):
        # `None` means "not supplied, read the environment". An empty string
        # means "explicitly no credentials" and is honoured as such.
        #
        # This was `key_id or os.environ.get(...)`, which collapses those two
        # cases: passing "" fell through to the environment, so a source built
        # deliberately without credentials silently picked up whatever was
        # exported in the shell. It made the no-credentials test pass on a
        # machine with no key set and fail on one with a key set, which is the
        # worst way round, since the machine that fails is the developer's and
        # the machine that passes is CI.
        self.key_id = key_id if key_id is not None else os.environ.get("ALPACA_API_KEY_ID", "")
        self.secret_key = (
            secret_key if secret_key is not None else os.environ.get("ALPACA_API_SECRET_KEY", "")
        )
        self.feed = feed
        self._fetch = fetch
        self.drop_partial_bars = drop_partial_bars
        self._clock = clock

    def last_final_session(self) -> pd.Timestamp:
        """The most recent date whose daily bar can be trusted not to change again.

        Ask for daily bars mid-session and the provider hands back today's bar
        so far: a close that is really just the last print, and a volume that is
        a fraction of what the day will finish on. Nothing errors. SPY came back
        at 11.7m against a normal 40m to 70m on the run that prompted this.

        That breaks the project in three places at once. Volume filters judge a
        partial figure. Moving averages, the gap, and the breakout tests all read
        a close that is still moving. And a scan at 15:00 disagrees with a scan
        at 21:00 on the same day, so signals stop being reproducible, which is
        the property the whole backtest depends on.

        Conservative by design: before the bell has settled, today does not count.
        On an early-close holiday this waits longer than it strictly must, which
        costs a few hours and never costs correctness.
        """
        now = self._clock()
        today = pd.Timestamp(now.date())
        return today if now.time() >= SESSION_FINAL_AFTER else today - pd.Timedelta(days=1)

    @property
    def _headers(self) -> dict[str, str]:
        if not self.key_id or not self.secret_key:
            raise DataError(
                "Alpaca credentials missing. Set ALPACA_API_KEY_ID and "
                "ALPACA_API_SECRET_KEY in the environment."
            )
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def _start_date(self, days: int) -> str:
        back = int(days * CALENDAR_PADDING) + CALENDAR_SLACK_DAYS
        return (datetime.now(UTC) - timedelta(days=back)).strftime("%Y-%m-%d")

    def histories(self, tickers: list[str], days: int = 250) -> dict[str, pd.DataFrame]:
        """Bars for many symbols. This is the method that makes Alpaca worth using.

        One request covers every symbol in `tickers`, and pagination is followed
        until Alpaca stops handing back a token. Ordering of the returned dict
        is not guaranteed to match the input, and symbols with no data are
        simply absent rather than present and empty.
        """
        if not tickers:
            return {}

        params: dict[str, Any] = {
            "symbols": ",".join(t.upper() for t in tickers),
            "timeframe": "1Day",
            "start": self._start_date(days),
            "adjustment": "all",
            "limit": PAGE_LIMIT,
            "feed": self.feed,
        }

        collected: dict[str, list[dict]] = {}
        while True:
            payload = self._fetch(BARS_URL, params, self._headers)
            for symbol, bars in (payload.get("bars") or {}).items():
                collected.setdefault(symbol, []).extend(bars)
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token

        cutoff = self.last_final_session() if self.drop_partial_bars else None
        return {
            symbol: self._to_frame(symbol, bars, days, cutoff)
            for symbol, bars in collected.items()
            if bars
        }

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        """One symbol, to satisfy the PriceSource protocol.

        Prefer `histories` wherever more than one ticker is wanted: this method
        spends a whole request on a single symbol, which is exactly the habit
        that got the yfinance path throttled.
        """
        frames = self.histories([ticker], days=days)
        frame = frames.get(ticker.upper())
        if frame is None or frame.empty:
            raise DataError(f"{ticker}: Alpaca returned no rows")
        return frame

    def shares_float(self, ticker: str) -> float | None:
        """Always None. Alpaca's bars API carries no fundamentals.

        Deliberately not faked from shares outstanding or any other proxy. The
        tradability gate reads None as "unknown, check it by hand", which is
        true, where a wrong number would be quietly acted on.
        """
        return None

    @staticmethod
    def _to_frame(
        ticker: str, bars: list[dict], days: int, cutoff: pd.Timestamp | None
    ) -> pd.DataFrame:
        frame = pd.DataFrame(bars)
        missing = {"t", "o", "h", "l", "c", "v"} - set(frame.columns)
        if missing:
            raise DataError(f"{ticker}: Alpaca response missing fields {sorted(missing)}")

        frame = frame.rename(
            columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        )
        # Alpaca stamps daily bars at 04:00 UTC rather than midnight. Normalising
        # keeps the index shape identical to the other sources, so a date
        # comparison anywhere else in the project cannot fail on a stray time.
        frame.index = pd.to_datetime(frame["t"]).dt.tz_localize(None).dt.normalize()
        frame = frame[["open", "high", "low", "close", "volume"]].astype(float)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        if cutoff is not None:
            frame = frame[frame.index <= cutoff]
        return validate_bars(frame.tail(days), ticker)
