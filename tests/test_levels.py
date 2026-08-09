"""Support and resistance levels: clustering, the three-touch rule, and the flip.

Written before `levels.py` existed. Every chart below is built by hand so the answer
can be worked out on paper first, which is the only way to know a test is testing the
code rather than agreeing with it.

The bars here use `high == low == close`. Real bars do not look like that, but it means
a swing point sits at exactly the price written in the list, so an expected level price
is readable straight off the chart instead of being an artefact of the builder.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import numpy as np
import pandas as pd
import pytest

from stocksignal.config import Config
from stocksignal.levels import Level, classify_levels, find_levels


def flat_ohlc(closes: list[float], volume: float = 1_000_000) -> pd.DataFrame:
    """Bars with no intraday range, so every swing point lands on a round number."""
    n = len(closes)
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": np.full(n, float(volume)),
        },
        index=pd.bdate_range(end=pd.Timestamp("2026-08-07"), periods=n),
    )


def zigzag(peak: float, trough: float, middle: float, cycles: int) -> list[float]:
    """A saw tooth: trough, middle, peak, middle, trough, ... with clean pivots.

    One cycle contributes one peak and one trough. The trailing values exist so the
    last pivot is not sitting on the edge of the frame, where a centred rolling window
    cannot see past it and therefore cannot confirm it.
    """
    out = [trough]
    for _ in range(cycles):
        out += [middle, peak, middle, trough]
    return out


@pytest.fixture
def lvl_cfg() -> Config:
    """Small windows so the hand-built charts stay short enough to read."""
    return Config(
        sma_fast=5,
        sma_slow=10,
        min_history_days=20,
        level_swing_lookback=2,
        level_tolerance_pct=1.0,
        level_min_touches=3,
        level_lookback_days=60,
        level_fresh_days=10,
        level_break_lookback=3,
    )


class TestFindingLevels:
    def test_three_touches_of_a_price_make_a_level(self, lvl_cfg):
        # Peaks at 100 on three separate occasions, troughs at 90 on three.
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 96.0])
        levels = find_levels(df, lvl_cfg)
        prices = sorted(round(lv.price, 2) for lv in levels)
        assert prices == [90.0, 100.0]
        assert all(lv.touches >= 3 for lv in levels)

    def test_two_touches_are_not_enough(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=2) + [95.0, 96.0])
        # Two cycles gives two confirmed peaks and two confirmed troughs.
        assert find_levels(df, lvl_cfg) == ()

    def test_the_touch_minimum_comes_from_config_not_the_code(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=2) + [95.0, 96.0])
        lenient = replace(lvl_cfg, level_min_touches=2)
        assert len(find_levels(df, lenient)) == 2

    def test_nearby_prices_cluster_into_a_single_level(self, lvl_cfg):
        # Three peaks at 100.0, 100.5 and 99.6. All inside a 1 percent band, so the
        # rulebook's "three confirmations" is satisfied by three near misses, which is
        # what a real chart actually looks like. A level is a zone, not a line.
        closes = [90.0]
        for peak in (100.0, 100.5, 99.6):
            closes += [95.0, peak, 95.0, 90.0]
        df = flat_ohlc(closes + [95.0, 96.0])
        levels = find_levels(df, lvl_cfg)
        upper = [lv for lv in levels if lv.price > 95]
        assert len(upper) == 1
        assert upper[0].touches == 3
        assert upper[0].price == pytest.approx((100.0 + 100.5 + 99.6) / 3, abs=0.01)

    def test_prices_outside_the_tolerance_stay_separate(self, lvl_cfg):
        # 100 and 106 are six percent apart against a one percent band, so no amount of
        # touching makes them the same level.
        closes = [90.0]
        for peak in (100.0, 106.0, 100.0, 106.0, 100.0, 106.0):
            closes += [95.0, peak, 95.0, 90.0]
        df = flat_ohlc(closes + [95.0, 96.0])
        upper = sorted(round(lv.price, 1) for lv in find_levels(df, lvl_cfg) if lv.price > 95)
        assert upper == [100.0, 106.0]

    def test_the_tolerance_is_a_percentage_not_an_absolute_amount(self, lvl_cfg):
        """The whole reason the band is a percentage, in one test.

        The same 1.50 spread is a 7.5 percent gap on a 20 dollar stock and a 0.4 percent
        gap on a 400 dollar one. A fixed band would call both the same, or neither.
        """
        cheap = flat_ohlc(
            [18.0]
            + [c for p in (20.00, 21.50, 20.00) for c in (19.0, p, 19.0, 18.0)]
            + [19.0, 19.5]
        )
        dear = flat_ohlc(
            [380.0]
            + [c for p in (400.00, 401.50, 400.00) for c in (390.0, p, 390.0, 380.0)]
            + [390.0, 395.0]
        )
        cheap_upper = [lv for lv in find_levels(cheap, lvl_cfg) if lv.price > 19]
        dear_upper = [lv for lv in find_levels(dear, lvl_cfg) if lv.price > 390]
        assert cheap_upper == [], "20.00 and 21.50 are 7.5 percent apart, not one level"
        assert len(dear_upper) == 1, "400.00 and 401.50 are 0.4 percent apart, one level"
        assert dear_upper[0].touches == 3

    def test_the_tolerance_comes_from_config_not_the_code(self, lvl_cfg):
        closes = [90.0]
        for peak in (100.0, 106.0, 100.0, 106.0, 100.0, 106.0):
            closes += [95.0, peak, 95.0, 90.0]
        df = flat_ohlc(closes + [95.0, 96.0])
        absurd = replace(lvl_cfg, level_tolerance_pct=25.0)
        merged = find_levels(df, absurd)
        assert len(merged) == 1, "a 25 percent band swallows every touch into one level"
        assert merged[0].touches > 6, "including the troughs at 90, which a 1% band separates"

    def test_a_level_carries_its_first_and_last_touch_dates(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 96.0])
        top = max(find_levels(df, lvl_cfg), key=lambda lv: lv.price)
        assert top.first_touch < top.last_touch
        assert top.first_touch in {d.date() for d in df.index}
        assert top.last_touch in {d.date() for d in df.index}

    def test_touches_older_than_the_window_do_not_count(self, lvl_cfg):
        """Three touches two years apart is not the same claim as three in a fortnight.

        The window is the decision made before any of this was written: touches outside
        it are not evidence about where price is respected now.
        """
        old = zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3)
        quiet = [95.0] * 80  # long enough to push every touch outside a 60 session window
        df = flat_ohlc(old + quiet)
        assert find_levels(df, lvl_cfg) == ()

    def test_a_recent_level_scores_higher_than_a_stale_one(self, lvl_cfg):
        fresh = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 96.0])
        stale = flat_ohlc(
            zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0] * 30 + [96.0]
        )
        fresh_top = max(find_levels(fresh, lvl_cfg), key=lambda lv: lv.price)
        stale_top = max(find_levels(stale, lvl_cfg), key=lambda lv: lv.price)
        assert fresh_top.recency == 1.0
        assert 0.0 < stale_top.recency < 1.0
        assert fresh_top.touches == stale_top.touches, "same evidence, different freshness"

    def test_a_flat_chart_has_no_levels(self, lvl_cfg):
        assert find_levels(flat_ohlc([100.0] * 40), lvl_cfg) == ()

    def test_too_little_history_fails_quietly_rather_than_exploding(self, lvl_cfg):
        assert find_levels(flat_ohlc([100.0, 101.0, 100.0]), lvl_cfg) == ()


class TestClassifyingLevels:
    def test_a_level_above_price_is_resistance_and_below_is_support(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 95.0])
        marked = classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg)
        by_price = {round(lv.price): lv.kind for lv in marked}
        assert by_price == {100: "resistance", 90: "support"}

    def test_a_resistance_broken_in_the_last_few_sessions_flips_to_support(self, lvl_cfg):
        # Three peaks at 100, then price closes through it and holds above.
        df = flat_ohlc(
            zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [96.0, 99.0, 103.0, 104.0]
        )
        marked = classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg)
        top = max(marked, key=lambda lv: lv.price)
        assert top.kind == "support", "the rulebook: a break above resistance makes it support"
        assert top.flipped is True

    def test_a_support_broken_in_the_last_few_sessions_flips_to_resistance(self, lvl_cfg):
        df = flat_ohlc(
            zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 92.0, 89.0, 86.0, 85.0]
        )
        marked = classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg)
        bottom = min(marked, key=lambda lv: lv.price)
        assert bottom.kind == "resistance"
        assert bottom.flipped is True

    def test_a_level_price_never_crossed_is_not_flipped(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 95.0])
        assert all(
            lv.flipped is False for lv in classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg)
        )

    def test_a_break_older_than_the_break_window_is_not_flagged_as_a_flip(self, lvl_cfg):
        """A flip is news. Six months above an old ceiling is just where the price lives."""
        df = flat_ohlc(
            zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [103.0, 104.0, 105.0, 106.0]
        )
        marked = classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg)
        top = max(marked, key=lambda lv: lv.price)
        assert top.kind == "support", "price is above it, so it is support either way"
        assert top.flipped is False, "the break happened outside the 3 session break window"

    def test_classifying_nothing_returns_nothing(self, lvl_cfg):
        df = flat_ohlc([100.0] * 40)
        assert classify_levels((), df, lvl_cfg) == ()

    def test_classification_does_not_mutate_the_levels_it_was_given(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 95.0])
        found = find_levels(df, lvl_cfg)
        classify_levels(found, df, lvl_cfg)
        assert all(lv.kind == "unclassified" for lv in found), "frozen means frozen"


class TestTheLevelShape:
    def test_a_level_is_frozen(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 96.0])
        lv = find_levels(df, lvl_cfg)[0]
        with pytest.raises(FrozenInstanceError):
            lv.price = 1.0  # type: ignore[misc]

    def test_a_level_reads_as_something_a_human_would_recognise(self, lvl_cfg):
        df = flat_ohlc(zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3) + [95.0, 95.0])
        top = max(classify_levels(find_levels(df, lvl_cfg), df, lvl_cfg), key=lambda lv: lv.price)
        assert isinstance(top, Level)
        assert "resistance" in top.describe()
        assert "3 touches" in top.describe()
