"""The control arm. The classification is the part that can silently go wrong.

A gate rejection wandering into the control cohort would compare the screens
against penny-float names and flatter them; a screen rejection wandering out
would shrink the control to nothing. Both are silent, so both are tested.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stocksignal.control import (
    GATED_OUT,
    SCREENED_OUT,
    ControlResult,
    compare_day,
    independent_days,
    parse_rejections,
    sign_test,
)

DIGEST = """# Signal digest, 2026-09-17

## New today (1)

### 1. ZETA at 30.37 (score 1.20)

- price 30.37 clears the 15.00 swing floor

## Rejected

- **AEHR**: trend: open 88.95 is not above the 9-day SMA 88.98; breakout: no level
- **WYFI**: float 11,316,457 is below the 20,000,000 floor (low float)
- **BRK.B**: beta 1.96 is below the 2.00 floor (moves too much like the market)
- **SNDK**: breakout: no three-touch resistance level found

## Errors

- **XYZ**: rate limited
"""


class TestWhoCountsAsAControl:
    def test_a_screen_rejection_is_the_control_cohort(self):
        out = parse_rejections(DIGEST)
        assert out["AEHR"] == SCREENED_OUT
        assert out["SNDK"] == SCREENED_OUT

    def test_a_gate_rejection_is_not(self):
        out = parse_rejections(DIGEST)
        assert out["WYFI"] == GATED_OUT
        assert out["BRK.B"] == GATED_OUT

    def test_the_candidates_section_is_not_a_rejection(self):
        assert "ZETA" not in parse_rejections(DIGEST)

    def test_other_sections_are_not_raided_for_tickers(self):
        assert "XYZ" not in parse_rejections(DIGEST)

    def test_a_digest_with_no_rejections_is_empty_not_an_error(self):
        assert parse_rejections("# Signal digest\n\nNo candidates passed today.\n") == {}


class TestTheSignTest:
    def test_a_clean_sweep_is_significant(self):
        assert sign_test(10, 0) == pytest.approx(2 / 1024)

    def test_a_coin_flip_is_not(self):
        assert sign_test(1, 1) == pytest.approx(1.0)
        assert sign_test(12, 11) == pytest.approx(1.0)

    def test_no_days_is_not_a_p_value(self):
        assert sign_test(0, 0) != sign_test(0, 0)  # NaN

    def test_it_is_two_sided(self):
        assert sign_test(0, 10) == sign_test(10, 0)


class TestOneDay:
    def test_the_difference_is_between_medians(self):
        out = compare_day(date(2026, 9, 1), 20, {"A": 4.0, "B": 10.0}, {"C": 1.0, "D": 3.0})
        assert out.passed_median == pytest.approx(7.0)
        assert out.control_median == pytest.approx(2.0)
        assert out.difference == pytest.approx(5.0)
        assert out.favours_screens

    def test_a_day_with_an_empty_cohort_is_dropped_not_zeroed(self):
        assert compare_day(date(2026, 9, 1), 20, {}, {"C": 1.0}) is None
        assert compare_day(date(2026, 9, 1), 20, {"A": 1.0}, {}) is None


class TestAcrossDays:
    """Horizon 0 throughout, so every day is its own block and the overlap rule
    stays out of the way of what these are testing. The overlap rule has its own
    class below."""

    def _days(self, diffs):
        return [
            compare_day(date(2026, 9, i + 1), 20, {"A": d}, {"B": 0.0}) for i, d in enumerate(diffs)
        ]

    def test_ties_are_excluded_from_the_sign_test(self):
        result = ControlResult(0, self._days([1.0, -1.0, 0.0]))
        assert len(result.days) == 3
        assert len(result.usable) == 2
        assert (result.wins, result.losses) == (1, 1)
        # Two blocks is below MIN_BLOCKS, so there is deliberately no p here.
        assert result.p_value != result.p_value

    def test_the_headline_is_the_median_of_the_daily_differences(self):
        result = ControlResult(0, self._days([1.0, 2.0, 30.0]))
        assert result.median_difference == pytest.approx(2.0)

    def test_a_consistent_edge_across_days_shows_up_as_a_small_p(self):
        result = ControlResult(0, self._days([1.0] * 8))
        assert result.p_value < 0.01

    def test_no_days_is_not_a_result(self):
        result = ControlResult(0, [])
        assert result.median_difference != result.median_difference  # NaN


# --------------------------------------------------------------------------
# Overlapping days are not separate evidence
# --------------------------------------------------------------------------


def _run(n: int, horizon: int, diff: float = 1.0) -> ControlResult:
    days = [
        compare_day(date(2026, 9, 1) + timedelta(days=i), horizon, {"A": diff}, {"B": 0.0})
        for i in range(n)
    ]
    return ControlResult(horizon, days)


class TestOverlappingDaysAreNotEvidence:
    """Two 20-session windows a day apart share nineteen of their sessions."""

    def test_blocks_are_spaced_a_full_holding_period_plus_one(self):
        # Spacing by the horizon alone would still share the bar where one
        # block sells at the close and the next buys at the open.
        days = [
            compare_day(date(2026, 9, 1) + timedelta(days=i), 5, {"A": float(i)}, {"B": 0.0})
            for i in range(13)
        ]
        assert [d.day.day for d in independent_days(days, 5)] == [1, 7, 13]

    def test_a_longer_horizon_leaves_fewer_blocks(self):
        assert len(_run(20, 20).days) == 20
        assert len(independent_days(_run(20, 20).days, 20)) == 1

    def test_twenty_identical_overlapping_days_do_not_manufacture_significance(self):
        result = _run(20, 5)
        assert result.days_favouring == 20  # descriptive, every day agrees
        assert len(result.usable) == 4  # days 0, 6, 12, 18

    def test_the_descriptive_count_still_sees_every_day(self):
        assert _run(9, 3).days_favouring == 9


class TestAPValueIsWithheldRatherThanPrintedMeaningless:
    def test_one_block_gets_no_p_at_all(self):
        result = _run(20, 20)
        assert len(result.usable) == 1
        assert result.p_value != result.p_value  # NaN, not sign_test(1, 0) == 1.0

    def test_four_blocks_still_get_none_because_they_cannot_reach_a_threshold(self):
        result = _run(20, 5)
        assert len(result.usable) == 4
        assert result.p_value != result.p_value
        assert result.floor_p == pytest.approx(0.125)

    def test_five_blocks_get_one(self):
        result = _run(30, 5)
        assert len(result.usable) == 5
        assert result.p_value == pytest.approx(0.0625)
