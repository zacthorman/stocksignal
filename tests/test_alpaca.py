"""AlpacaSource, exercised without a network or an account.

The `fetch` callable is injected, so every test here drives real code paths with
canned responses. The three that matter are pagination, the SIP feed parameter,
and that one request serves many symbols. Everything else is plumbing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stocksignal.data import DataError
from stocksignal.sources import AlpacaSource


def bar(day: str, close: float = 100.0, volume: float = 1_000_000.0) -> dict:
    return {
        "t": f"{day}T05:00:00Z",
        "o": close * 0.99,
        "h": close * 1.01,
        "l": close * 0.98,
        "c": close,
        "v": volume,
        "n": 1000,
        "vw": close,
    }


class Recorder:
    """Stands in for the HTTP layer and remembers what it was asked for."""

    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.calls: list[dict] = []

    def __call__(self, url: str, params: dict, headers: dict) -> dict:
        self.calls.append({"url": url, "params": dict(params), "headers": headers})
        return self.pages[len(self.calls) - 1]


@pytest.fixture
def creds() -> dict:
    return {"key_id": "test-key", "secret_key": "test-secret"}


class TestFeedParameter:
    def test_every_request_asks_for_sip_explicitly(self, creds):
        # The whole point. Left to default, a free account silently gets IEX,
        # whose volume is a fraction of the real figure, and the volume filter
        # then rejects the market without anything erroring.
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        AlpacaSource(**creds, fetch=rec).histories(["AAPL"], days=10)
        assert rec.calls[0]["params"]["feed"] == "sip"

    def test_the_feed_can_be_overridden_for_a_paid_account(self, creds):
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        AlpacaSource(**creds, feed="iex", fetch=rec).histories(["AAPL"], days=10)
        assert rec.calls[0]["params"]["feed"] == "iex"


class TestBatching:
    def test_many_symbols_cost_one_request(self, creds):
        symbols = [f"SYM{i}" for i in range(50)]
        rec = Recorder(
            [{"bars": {s: [bar("2026-08-03")] for s in symbols}, "next_page_token": None}]
        )
        frames = AlpacaSource(**creds, fetch=rec).histories(symbols, days=10)
        assert len(rec.calls) == 1, "50 symbols must not cost 50 requests"
        assert len(frames) == 50

    def test_symbols_go_up_comma_separated_and_upper_cased(self, creds):
        rec = Recorder([{"bars": {}, "next_page_token": None}])
        AlpacaSource(**creds, fetch=rec).histories(["aapl", "msft"], days=10)
        assert rec.calls[0]["params"]["symbols"] == "AAPL,MSFT"

    def test_an_empty_ticker_list_makes_no_request_at_all(self, creds):
        rec = Recorder([])
        assert AlpacaSource(**creds, fetch=rec).histories([], days=10) == {}
        assert rec.calls == []


class TestPagination:
    def test_it_follows_the_token_until_the_data_runs_out(self, creds):
        rec = Recorder(
            [
                {"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": "page2"},
                {"bars": {"AAPL": [bar("2026-08-04")]}, "next_page_token": "page3"},
                {"bars": {"AAPL": [bar("2026-08-05")]}, "next_page_token": None},
            ]
        )
        frames = AlpacaSource(**creds, fetch=rec).histories(["AAPL"], days=10)
        assert len(rec.calls) == 3
        assert len(frames["AAPL"]) == 3, "bars from every page must be kept"

    def test_the_token_is_passed_back_on_the_next_request(self, creds):
        rec = Recorder(
            [
                {"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": "page2"},
                {"bars": {"AAPL": [bar("2026-08-04")]}, "next_page_token": None},
            ]
        )
        AlpacaSource(**creds, fetch=rec).histories(["AAPL"], days=10)
        assert "page_token" not in rec.calls[0]["params"]
        assert rec.calls[1]["params"]["page_token"] == "page2"


class TestFrameShape:
    def test_columns_are_renamed_to_the_project_convention(self, creds):
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        df = AlpacaSource(**creds, fetch=rec).history("AAPL", days=10)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_the_index_is_naive_dates_like_every_other_source(self, creds):
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        df = AlpacaSource(**creds, fetch=rec).history("AAPL", days=10)
        assert df.index.tz is None, "a tz-aware index would break comparisons elsewhere"

    def test_duplicate_timestamps_keep_the_last_and_stay_sorted(self, creds):
        rec = Recorder(
            [
                {
                    "bars": {
                        "AAPL": [
                            bar("2026-08-04", close=50.0),
                            bar("2026-08-03"),
                            bar("2026-08-04", close=99.0),
                        ]
                    },
                    "next_page_token": None,
                }
            ]
        )
        df = AlpacaSource(**creds, fetch=rec).history("AAPL", days=10)
        assert len(df) == 2
        assert df.index.is_monotonic_increasing
        assert df["close"].iloc[-1] == pytest.approx(99.0)

    def test_only_the_requested_number_of_sessions_comes_back(self, creds):
        days = pd.bdate_range(end="2026-08-07", periods=30).strftime("%Y-%m-%d")
        rec = Recorder([{"bars": {"AAPL": [bar(d) for d in days]}, "next_page_token": None}])
        df = AlpacaSource(**creds, fetch=rec).history("AAPL", days=10)
        assert len(df) == 10


class TestFailureModes:
    def test_missing_credentials_say_which_variables_to_set(self):
        source = AlpacaSource(key_id="", secret_key="", fetch=lambda *a: {})
        with pytest.raises(DataError, match="ALPACA_API_KEY_ID"):
            source.history("AAPL")

    def test_credentials_travel_in_the_headers(self, creds):
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        AlpacaSource(**creds, fetch=rec).histories(["AAPL"], days=10)
        assert rec.calls[0]["headers"]["APCA-API-KEY-ID"] == "test-key"
        assert rec.calls[0]["headers"]["APCA-API-SECRET-KEY"] == "test-secret"

    def test_an_unknown_symbol_raises_rather_than_returning_an_empty_frame(self, creds):
        rec = Recorder([{"bars": {}, "next_page_token": None}])
        with pytest.raises(DataError, match="no rows"):
            AlpacaSource(**creds, fetch=rec).history("NOPE", days=10)

    def test_a_malformed_response_names_the_missing_fields(self, creds):
        rec = Recorder(
            [
                {
                    "bars": {"AAPL": [{"t": "2026-08-03T05:00:00Z", "c": 100.0}]},
                    "next_page_token": None,
                }
            ]
        )
        with pytest.raises(DataError, match="missing fields"):
            AlpacaSource(**creds, fetch=rec).history("AAPL", days=10)

    def test_symbols_absent_from_the_response_are_absent_not_empty(self, creds):
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        frames = AlpacaSource(**creds, fetch=rec).histories(["AAPL", "GONE"], days=10)
        assert set(frames) == {"AAPL"}


class TestPartialBars:
    """Today's bar is not today's bar until the session has finished.

    Mid-session the provider returns the day so far: a close that is really the
    last print and a volume a fraction of the final figure. It arrives looking
    exactly like a settled bar, which is what makes it dangerous.
    """

    def _at(self, hhmm: str):
        hour, minute = (int(p) for p in hhmm.split(":"))
        from datetime import datetime as dt

        from stocksignal.sources.alpaca import MARKET_TZ

        return lambda: dt(2026, 8, 10, hour, minute, tzinfo=MARKET_TZ)

    def _source(self, creds, clock):
        days = ["2026-08-06", "2026-08-07", "2026-08-10"]
        rec = Recorder([{"bars": {"SPY": [bar(d) for d in days]}, "next_page_token": None}])
        return AlpacaSource(**creds, fetch=rec, clock=clock)

    def test_todays_bar_is_dropped_while_the_session_is_open(self, creds):
        # 11:00 ET, market open. The 10 August bar is still being written.
        df = self._source(creds, self._at("11:00")).history("SPY", days=10)
        assert str(df.index[-1].date()) == "2026-08-07"
        assert len(df) == 2

    def test_todays_bar_is_kept_once_the_session_has_settled(self, creds):
        # 16:30 ET, after the bell plus settling time.
        df = self._source(creds, self._at("16:30")).history("SPY", days=10)
        assert str(df.index[-1].date()) == "2026-08-10"
        assert len(df) == 3

    def test_the_boundary_is_the_settling_time_not_the_bell(self, creds):
        # 16:05 is after the close but inside the window where late prints
        # still move the daily bar, so it does not count yet.
        df = self._source(creds, self._at("16:05")).history("SPY", days=10)
        assert str(df.index[-1].date()) == "2026-08-07"

    def test_it_can_be_turned_off_deliberately(self, creds):
        days = ["2026-08-06", "2026-08-07", "2026-08-10"]
        rec = Recorder([{"bars": {"SPY": [bar(d) for d in days]}, "next_page_token": None}])
        source = AlpacaSource(**creds, fetch=rec, clock=self._at("11:00"), drop_partial_bars=False)
        assert len(source.history("SPY", days=10)) == 3


class TestIndexNormalisation:
    def test_daily_bars_land_on_midnight_not_04_00(self, creds):
        # Alpaca stamps daily bars at 04:00 UTC. Left alone, the index carries a
        # time component the other sources do not have, and any date comparison
        # elsewhere becomes a coin flip.
        rec = Recorder([{"bars": {"AAPL": [bar("2026-08-03")]}, "next_page_token": None}])
        df = AlpacaSource(**creds, fetch=rec, drop_partial_bars=False).history("AAPL", days=5)
        assert df.index[0] == pd.Timestamp("2026-08-03")
        assert df.index[0].hour == 0


class TestSharesFloat:
    def test_float_is_unknown_rather_than_invented(self, creds):
        # Alpaca has no fundamentals. Returning None makes the gate warn; making
        # a number up from shares outstanding would make it act.
        assert AlpacaSource(**creds, fetch=lambda *a: {}).shares_float("AAPL") is None
