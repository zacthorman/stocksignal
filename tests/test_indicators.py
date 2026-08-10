"""Indicator maths, checked against numbers worked out by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocksignal.indicators import (
    average_volume,
    beta,
    body_and_wick,
    pct_gap,
    rsi,
    sma,
    swing_points,
    true_range,
)


class TestSMA:
    def test_matches_a_hand_calculation(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        # Last three values are 3, 4, 5, so the 3-day average is 4.
        assert sma(s, 3).iloc[-1] == pytest.approx(4.0)

    def test_leading_values_are_nan_not_partial_averages(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = sma(s, 3)
        assert result.iloc[:2].isna().all()
        assert result.notna().sum() == 3

    def test_rejects_a_zero_window(self):
        with pytest.raises(ValueError):
            sma(pd.Series([1.0]), 0)


class TestPctGap:
    def test_fast_above_slow_is_positive(self):
        assert pct_gap(105, 100) == pytest.approx(5.0)

    def test_fast_below_slow_is_negative(self):
        assert pct_gap(95, 100) == pytest.approx(-5.0)

    def test_zero_slow_does_not_divide_by_zero(self):
        assert pct_gap(10, 0) == 0.0


class TestAverageVolume:
    def test_averages_the_window(self):
        v = pd.Series([100.0] * 10 + [200.0] * 10)
        assert average_volume(v, 10) == pytest.approx(200.0)

    def test_short_series_uses_what_it_has(self):
        assert average_volume(pd.Series([50.0, 150.0]), 20) == pytest.approx(100.0)

    def test_empty_series_is_zero_not_an_error(self):
        assert average_volume(pd.Series([], dtype=float), 20) == 0.0


class TestSwingPoints:
    def test_finds_the_obvious_peak(self):
        prices = [1, 2, 3, 4, 5, 9, 5, 4, 3, 2, 1]
        idx = pd.bdate_range(end="2026-08-05", periods=len(prices))
        high = pd.Series(prices, index=idx, dtype=float)
        low = pd.Series(prices, index=idx, dtype=float)
        highs, lows = swing_points(high, low, lookback=2)
        assert 9.0 in highs.values

    def test_rejects_a_zero_lookback(self):
        s = pd.Series([1.0, 2.0, 3.0])
        with pytest.raises(ValueError):
            swing_points(s, s, lookback=0)


class TestTrueRange:
    def test_uses_the_widest_of_the_three_spans(self):
        df = pd.DataFrame(
            {
                "open": [10.0, 12.0],
                "high": [11.0, 15.0],
                "low": [9.0, 13.0],
                "close": [10.5, 14.0],
            }
        )
        # Second bar gaps up: high 15 against a previous close of 10.5 is 4.5,
        # which is wider than its own 2-point span.
        assert true_range(df).iloc[-1] == pytest.approx(4.5)


class TestBodyAndWick:
    def test_splits_a_candle_into_body_and_wick(self):
        row = pd.Series({"open": 10.0, "high": 13.0, "low": 9.0, "close": 12.0})
        body, wick = body_and_wick(row)
        assert body == pytest.approx(2.0)
        assert wick == pytest.approx(2.0)

    def test_a_doji_is_all_wick(self):
        row = pd.Series({"open": 10.0, "high": 12.0, "low": 8.0, "close": 10.0})
        body, wick = body_and_wick(row)
        assert body == pytest.approx(0.0)
        assert wick == pytest.approx(4.0)


class TestRSI:
    def test_a_series_that_only_rises_pins_at_100(self):
        s = pd.Series([100.0 + i for i in range(30)])
        # No down days at all, so average loss is zero and the ratio is infinite.
        assert rsi(s, 14).iloc[-1] == pytest.approx(100.0)

    def test_a_series_that_only_falls_pins_at_0(self):
        s = pd.Series([200.0 - i for i in range(30)])
        assert rsi(s, 14).iloc[-1] == pytest.approx(0.0)

    def test_a_flat_series_is_neutral_not_a_division_by_zero(self):
        s = pd.Series([100.0] * 30)
        assert rsi(s, 14).iloc[-1] == pytest.approx(50.0)

    def test_equal_sized_up_and_down_days_hover_around_50(self):
        # Alternating +2 / -2. Average gain and average loss are equal in the
        # long run, so RSI sits at 50, but Wilder's smoothing weights the most
        # recent bar, so it oscillates a couple of points either side depending
        # on whether the last bar was up or down. Asserting exactly 50 here
        # would be asserting that the smoothing does not work.
        s = pd.Series([100.0 + (2.0 if i % 2 else 0.0) for i in range(40)])
        settled = rsi(s, 14).dropna()
        assert settled.min() > 45.0
        assert settled.max() < 55.0

    def test_the_first_period_values_are_nan(self):
        s = pd.Series([100.0 + i for i in range(30)])
        result = rsi(s, 14)
        assert result.iloc[:14].isna().all()
        assert result.notna().sum() == len(s) - 14

    def test_too_short_a_series_is_all_nan_rather_than_an_error(self):
        assert rsi(pd.Series([100.0, 101.0, 102.0]), 14).isna().all()

    def test_rejects_a_period_below_two(self):
        with pytest.raises(ValueError):
            rsi(pd.Series([1.0, 2.0]), 1)

    def test_an_oversold_selloff_reads_below_thirty(self):
        # A long calm stretch, then a sharp sustained drop. This is the shape
        # the checklist calls a "good deal", so it has to land under the line.
        calm = [100.0 + (0.1 if i % 2 else -0.1) for i in range(40)]
        selloff = [100.0 - i * 3.0 for i in range(1, 15)]
        result = rsi(pd.Series(calm + selloff), 14).iloc[-1]
        assert result < 30.0


class TestBeta:
    def _pair(self, asset_moves, bench_moves):
        idx = pd.bdate_range(end="2026-08-05", periods=len(asset_moves) + 1)
        asset = pd.Series(np.cumprod([100.0] + [1 + m for m in asset_moves]), index=idx)
        bench = pd.Series(np.cumprod([100.0] + [1 + m for m in bench_moves]), index=idx)
        return asset, bench

    def test_a_stock_that_moves_exactly_with_the_market_is_one(self):
        moves = [0.01, -0.02, 0.03, -0.01, 0.02] * 4
        asset, bench = self._pair(moves, moves)
        assert beta(asset, bench, window=252) == pytest.approx(1.0)

    def test_a_stock_that_moves_twice_as_hard_is_two(self):
        bench_moves = [0.01, -0.02, 0.03, -0.01, 0.02] * 4
        asset_moves = [m * 2 for m in bench_moves]
        asset, bench = self._pair(asset_moves, bench_moves)
        assert beta(asset, bench, window=252) == pytest.approx(2.0, rel=0.05)

    def test_a_stock_that_moves_against_the_market_is_negative(self):
        bench_moves = [0.01, -0.02, 0.03, -0.01, 0.02] * 4
        asset_moves = [-m for m in bench_moves]
        asset, bench = self._pair(asset_moves, bench_moves)
        assert beta(asset, bench, window=252) < 0

    def test_a_motionless_benchmark_is_unknown_not_infinity(self):
        asset, bench = self._pair([0.01, -0.02, 0.03] * 4, [0.0] * 12)
        assert beta(asset, bench, window=252) is None

    def test_no_overlapping_sessions_is_unknown(self):
        a = pd.Series([100.0, 101.0], index=pd.bdate_range("2020-01-01", periods=2))
        b = pd.Series([100.0, 101.0], index=pd.bdate_range("2024-01-01", periods=2))
        assert beta(a, b) is None

    def test_only_the_window_is_measured(self):
        # Twice as volatile for the recent stretch, flat-tracking before it.
        # A window of 10 must see only the recent behaviour.
        bench_moves = [0.01, -0.01] * 20
        asset_moves = [0.01, -0.01] * 15 + [0.03, -0.03] * 5
        asset, bench = self._pair(asset_moves, bench_moves)
        assert beta(asset, bench, window=10) == pytest.approx(3.0, rel=0.05)

    def test_rejects_a_window_below_two(self):
        asset, bench = self._pair([0.01] * 5, [0.01] * 5)
        with pytest.raises(ValueError):
            beta(asset, bench, window=1)


def test_no_indicator_mutates_its_input():
    """A function that quietly edits the frame you passed it is a bug factory."""
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [1e6, 1e6],
        }
    )
    before = df.copy(deep=True)
    true_range(df)
    sma(df["close"], 2)
    average_volume(df["volume"], 2)
    assert np.array_equal(df.values, before.values)
