"""Scanner behaviour, including the failure paths that matter most.

The interesting tests here are not "does a good ticker pass". They are "does one
broken ticker take down the whole run". Robustness is the difference between a
script and a tool.
"""

from __future__ import annotations

import pandas as pd
import pytest

from helpers import make_bars
from stocksignal.config import Config
from stocksignal.data import DataError, SyntheticSource, last_business_day, validate_bars
from stocksignal.scanner import scan, scan_ticker


class FakeSource:
    """A price source that returns exactly what a test tells it to."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        floats: dict[str, float | None] | None = None,
    ):
        self.frames = frames
        self.floats = floats or {}

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        if ticker not in self.frames:
            raise DataError(f"{ticker}: not in the fake source")
        return self.frames[ticker]

    def shares_float(self, ticker: str) -> float | None:
        return self.floats.get(ticker, 50_000_000)


@pytest.fixture
def cfg() -> Config:
    return Config(sma_fast=5, sma_slow=10, min_history_days=20, avg_volume_window=10)


class TestScanTicker:
    def test_uptrend_produces_a_signal(self, cfg):
        src = FakeSource({"UP": make_bars([100 + i * 1.5 for i in range(80)])})
        sig = scan_ticker("UP", src, cfg)
        assert sig is not None
        assert sig.ticker == "UP"
        assert sig.score > 0
        assert "trend" in sig.passed_screens

    def test_downtrend_produces_nothing(self, cfg):
        src = FakeSource({"DOWN": make_bars([220 - i * 1.5 for i in range(80)])})
        assert scan_ticker("DOWN", src, cfg) is None

    def test_a_signal_carries_its_reasoning(self, cfg):
        src = FakeSource({"UP": make_bars([100 + i * 1.5 for i in range(80)])})
        sig = scan_ticker("UP", src, cfg)
        assert sig is not None and len(sig.reasons) >= 2


class TestScanWatchlist:
    def test_ranks_by_score_descending(self, cfg):
        src = FakeSource(
            {
                "GENTLE": make_bars([100 + i * 0.6 for i in range(80)]),
                "STEEP": make_bars([100 + i * 3.0 for i in range(80)]),
            }
        )
        report = scan(["GENTLE", "STEEP"], src, cfg)
        assert [s.ticker for s in report.signals] == ["STEEP", "GENTLE"]

    def test_one_broken_ticker_does_not_kill_the_run(self, cfg):
        src = FakeSource({"GOOD": make_bars([100 + i * 1.5 for i in range(80)])})
        report = scan(["GOOD", "MISSING"], src, cfg)
        assert [s.ticker for s in report.signals] == ["GOOD"]
        assert report.errors and report.errors[0][0] == "MISSING"

    def test_rejections_are_recorded_with_a_reason(self, cfg):
        src = FakeSource({"THIN": make_bars([100.0] * 80, volume=1_000)})
        report = scan(["THIN"], src, cfg)
        assert not report.signals
        assert report.rejected[0][0] == "THIN"
        assert "volume" in report.rejected[0][1]

    def test_every_ticker_is_accounted_for(self, cfg):
        src = FakeSource(
            {
                "GOOD": make_bars([100 + i * 1.5 for i in range(80)]),
                "BAD": make_bars([220 - i * 1.5 for i in range(80)]),
                "THIN": make_bars([100.0] * 80, volume=1_000),
            }
        )
        report = scan(["GOOD", "BAD", "THIN", "MISSING"], src, cfg)
        assert report.scanned == 4


class TestSyntheticSource:
    def test_is_deterministic(self):
        a = SyntheticSource(seed=1).history("AAPL", days=100)
        b = SyntheticSource(seed=1).history("AAPL", days=100)
        pd.testing.assert_frame_equal(a, b)

    def test_different_tickers_differ(self):
        src = SyntheticSource(seed=1)
        assert not src.history("AAPL", 100)["close"].equals(src.history("MSFT", 100)["close"])

    def test_produces_valid_bars(self):
        df = SyntheticSource().history("SPY", days=120)
        assert len(df) == 120
        assert (df["high"] >= df["low"]).all()
        assert df.index.is_monotonic_increasing


class TestValidateBars:
    def test_rejects_a_missing_column(self):
        df = pd.DataFrame({"close": [1.0]}, index=pd.bdate_range("2026-01-01", periods=1))
        with pytest.raises(DataError, match="missing columns"):
            validate_bars(df, "X")

    def test_rejects_an_empty_frame(self):
        df = pd.DataFrame(
            {c: [] for c in ("open", "high", "low", "close", "volume")},
            index=pd.DatetimeIndex([]),
        )
        with pytest.raises(DataError, match="no rows"):
            validate_bars(df, "X")

    def test_rejects_a_non_datetime_index(self):
        df = make_bars([1.0, 2.0]).reset_index(drop=True)
        with pytest.raises(DataError, match="DatetimeIndex"):
            validate_bars(df, "X")

    def test_sorts_an_out_of_order_index(self):
        df = make_bars([1.0, 2.0, 3.0]).iloc[::-1]
        assert validate_bars(df, "X").index.is_monotonic_increasing


class TestLastBusinessDay:
    """The weekend roll back. Regression cover for a bug that only fired on a Saturday.

    `SyntheticSource.history` builds its index with `pd.bdate_range(end=..., periods=days)`
    and its columns from arrays of length `days`. Hand `bdate_range` a weekend date and it
    hands back one row fewer, so the frame refuses to build. Every test passed midweek.
    """

    def test_a_weekday_is_left_alone(self):
        thursday = pd.Timestamp("2026-08-06")
        assert last_business_day(thursday) == thursday

    def test_saturday_rolls_back_to_friday(self):
        assert last_business_day(pd.Timestamp("2026-08-08")) == pd.Timestamp("2026-08-07")

    def test_sunday_rolls_back_to_friday(self):
        assert last_business_day(pd.Timestamp("2026-08-09")) == pd.Timestamp("2026-08-07")

    def test_a_time_of_day_is_stripped(self):
        stamped = pd.Timestamp("2026-08-06 14:32:11")
        assert last_business_day(stamped) == pd.Timestamp("2026-08-06")

    def test_every_day_of_a_week_yields_the_full_row_count(self):
        """The actual failure, reproduced directly rather than through the source."""
        for day in pd.date_range("2026-08-03", "2026-08-09"):
            idx = pd.bdate_range(end=last_business_day(day), periods=120)
            assert len(idx) == 120, f"{day.day_name()} produced {len(idx)} rows"
