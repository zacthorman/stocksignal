"""Indicator maths, checked against numbers worked out by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocksignal.indicators import (
    average_volume,
    body_and_wick,
    pct_gap,
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
