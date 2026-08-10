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
from stocksignal.scanner import build_quote, load_benchmark, scan, scan_ticker


class FakeSource:
    """A price source that returns exactly what a test tells it to."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        floats: dict[str, float | None] | None = None,
    ):
        self.frames = frames
        self.floats = floats or {}
        self.calls: list[str] = []

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        self.calls.append(ticker)
        if ticker not in self.frames:
            raise DataError(f"{ticker}: not in the fake source")
        return self.frames[ticker]

    def shares_float(self, ticker: str) -> float | None:
        return self.floats.get(ticker, 50_000_000)


@pytest.fixture
def cfg() -> Config:
    # Mirrors the fixture in conftest.py, including the pinned gap thresholds.
    # See that docstring for why they cannot be left at the production defaults.
    return Config(
        sma_fast=5,
        sma_slow=10,
        min_history_days=20,
        avg_volume_window=10,
        min_sma_gap_pct=0.5,
        sma_gap_strong_pct=5.0,
    )


def geometric_bars(moves: list[float], start: float = 100.0):
    """Bars built from a list of daily returns, so beta is exactly predictable."""
    closes = [start]
    for m in moves:
        closes.append(closes[-1] * (1 + m))
    return make_bars(closes)


class TestBenchmarkAndBeta:
    """Beta is the third of the course's scan filters and it needs a benchmark.

    The behaviour that matters is not "can it divide". It is that one benchmark
    fetch serves a whole watchlist, and that losing the benchmark costs you the
    beta reading rather than the scan.
    """

    def _pair(self, cfg, multiple: float):
        bench_moves = [0.01, -0.02, 0.03, -0.01, 0.02] * 16
        asset_moves = [m * multiple for m in bench_moves]
        return {
            cfg.beta_benchmark: geometric_bars(bench_moves),
            "HIGH": geometric_bars(asset_moves),
        }

    def test_beta_lands_on_the_quote_when_a_benchmark_is_supplied(self, cfg):
        frames = self._pair(cfg, 3.0)
        src = FakeSource(frames)
        bench = load_benchmark(src, cfg)
        quote = build_quote("HIGH", frames["HIGH"], cfg, 50_000_000, bench)
        assert quote.beta == pytest.approx(3.0, rel=0.05)

    def test_beta_is_unknown_without_a_benchmark(self, cfg):
        frames = self._pair(cfg, 3.0)
        quote = build_quote("HIGH", frames["HIGH"], cfg, 50_000_000)
        assert quote.beta is None

    def test_a_missing_benchmark_is_survivable(self, cfg):
        # The provider has no SPY at all. Beta goes unknown, the scan continues.
        src = FakeSource({"UP": make_bars([100 + i * 1.5 for i in range(80)])})
        assert load_benchmark(src, cfg) is None
        report = scan(["UP"], src, cfg)
        assert report.signals
        assert any("beta unknown" in r for r in report.signals[0].reasons)

    def test_the_benchmark_is_fetched_once_for_the_whole_watchlist(self, cfg):
        frames = self._pair(cfg, 3.0)
        frames["ALSO"] = make_bars([100 + i * 1.5 for i in range(80)])
        src = FakeSource(frames)
        scan(["HIGH", "ALSO"], src, cfg)
        assert src.calls.count(cfg.beta_benchmark) == 1

    def test_a_low_beta_ticker_is_rejected_by_the_gate(self, cfg):
        # Moves exactly with the market, so beta is 1 and the swing filter says no.
        frames = self._pair(cfg, 1.0)
        report = scan(["HIGH"], FakeSource(frames), cfg)
        assert not report.signals
        assert "beta" in report.rejected[0][1]


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
