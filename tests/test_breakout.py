"""The breakout screen: five rules from the rulebook, tested one at a time.

Every chart below shares the same shape: a three-touch struggle at resistance
100 (from `zigzag`, the same pattern proven in `test_levels.py`), then a fixed
baby bar and igniting bar that break it. Each test overrides exactly the one
bar that carries the rule under test and leaves the rest of the scaffold
alone, so a failing test points at one rule, not a chart shape.

The baby and igniting bar numbers are worked out by hand in the session log,
not guessed: body, wick and volume ratios are chosen so each gate sits clearly
on one side of its floor, with enough headroom that a small config change
would not flip the test by accident.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from helpers import make_bars, quote_from
from stocksignal.config import Config
from stocksignal.screens.breakout import screen_breakout


def bar(open_: float, high: float, low: float, close: float, volume: float = 1_000_000) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": float(volume)}


def flat(price: float, volume: float = 1_000_000) -> dict:
    return bar(price, price, price, price, volume)


def zigzag(peak: float, trough: float, middle: float, cycles: int) -> list[float]:
    """Same builder as test_levels.py: trough, middle, peak, middle, repeated."""
    out = [trough]
    for _ in range(cycles):
        out += [middle, peak, middle, trough]
    return out


def build(rows: list[dict]) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp("2026-08-07"), periods=len(rows))
    return pd.DataFrame(rows, index=idx)[["open", "high", "low", "close", "volume"]]


# Body 2, wick 1.0 over a 3.0 range: a healthy, unremarkable small bar.
DEFAULT_BABY = bar(97.0, 99.5, 96.5, 99.0, volume=1_000_000)
# Body 9, wick 1.5: 4.5x the baby bar's body and 8.3% of its own close.
DEFAULT_IGNITION = bar(99.0, 109.0, 98.5, 108.0, volume=2_000_000)
# Green, holds above its open.
DEFAULT_FOLLOW = bar(108.0, 111.0, 107.5, 110.0, volume=1_200_000)


def make_breakout_chart(
    baby: dict | None = None,
    ignition: dict | None = None,
    follow: dict | None = None,
    include_follow: bool = True,
    extra: list[dict] | None = None,
    buffer_bars: int = 4,
) -> pd.DataFrame:
    """The shared scaffold: struggle at 100, then baby / ignition / follow-through.

    Flat buffer bars sit between the struggle and the baby bar. They exist so
    that `level_break_lookback`'s "earlier" reference bar (used by
    `classify_levels` to detect the flip) always lands in this buffer zone
    rather than back inside the struggle itself, whatever the total length of
    a given test's chart turns out to be. Without them, "earlier" can land
    exactly on the 100.0 touch and the strict "<" in the flip check silently
    fails to detect the break.

    `buffer_bars` also doubles as the knob for how stale the resistance touch
    is by the time the breakout fires: more buffer bars between the struggle
    and the baby bar means more sessions between the level's last confirmed
    touch and "today", without moving the baby / ignition / follow-through
    bars themselves or their volume.
    """
    rows = [flat(p) for p in zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3)]
    rows += [flat(95.0) for _ in range(buffer_bars)]
    rows.append(baby or dict(DEFAULT_BABY))
    rows.append(ignition or dict(DEFAULT_IGNITION))
    if include_follow:
        rows.append(follow or dict(DEFAULT_FOLLOW))
    if extra:
        rows.extend(extra)
    return build(rows)


@pytest.fixture
def brk_cfg() -> Config:
    """Small windows so the hand-built charts stay short, matching test_levels.py's lvl_cfg."""
    return Config(
        sma_fast=5,
        sma_slow=10,
        min_history_days=10,
        avg_volume_window=10,
        level_swing_lookback=2,
        level_tolerance_pct=1.0,
        level_min_touches=3,
        level_lookback_days=60,
        level_fresh_days=10,
        level_break_lookback=5,
        breakout_volume_spike_min=1.5,
        breakout_volume_spike_strong=3.0,
        breakout_ignition_min_body_pct=1.5,
        breakout_ignition_strong_ratio=3.0,
        breakout_baby_max_wick_pct=60.0,
        breakout_dip_tolerance_pct=1.5,
        breakout_dip_reject_bonus=0.3,
        w_breakout_volume=1 / 3,
        w_breakout_ignition=1 / 3,
        w_breakout_recency=1 / 3,
    )


class TestResistanceBreakGate:
    def test_no_levels_at_all_fails(self, brk_cfg):
        # A pure uptrend has no swing highs, so there is nothing to break.
        df = make_bars([100 + i for i in range(40)])
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "no three-touch resistance level found" in " ".join(result.reasons)

    def test_a_level_that_was_never_broken_fails(self, brk_cfg):
        # Same struggle at 100, but price never closes back above it.
        rows = [flat(p) for p in zigzag(peak=100.0, trough=90.0, middle=95.0, cycles=3)]
        rows += [flat(95.0), flat(96.0), flat(97.0), flat(98.0)]
        df = build(rows)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "never been broken" in " ".join(result.reasons)

    def test_a_break_older_than_the_lookback_window_fails(self, brk_cfg):
        # The default scaffold breaks out cleanly through 100 (proven by the
        # textbook-pass test), but here it then holds well above the level for
        # 8 more quiet sessions before "today" instead of stopping right after
        # the follow-through bar. The actual break sits 9 sessions back by the
        # time the screen runs, and level_break_lookback here is only 5, so it
        # falls outside the window the rulebook means by "in the last few
        # sessions". It is a real, held breakout, just too old to be today's
        # trigger, and that is a different situation from one that never broke
        # at all.
        stale_tail = [flat(105.0) for _ in range(8)]
        df = make_breakout_chart(extra=stale_tail)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "too old to act on" in " ".join(result.reasons)

    def test_a_baby_bar_that_closes_exactly_at_resistance_still_counts(self, brk_cfg):
        # The baby bar closes at exactly 100.0, precisely on the resistance
        # level, then the igniting bar clears it. That is still a real break:
        # the bar spent the whole session at or below the level and the next
        # one took price decisively above it. A fix that required the baby
        # bar to close strictly under the level would silently drop this
        # pattern, so this locks in that it still counts.
        baby = bar(98.0, 100.3, 97.7, 100.0, volume=1_000_000)
        ignition = bar(100.0, 109.0, 99.5, 108.0, volume=2_000_000)
        df = make_breakout_chart(baby=baby, ignition=ignition)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert result.passed


class TestVolumeSpikeGate:
    def test_no_spike_fails(self, brk_cfg):
        # Same as the rest of the scaffold: ignition volume matches the average.
        ignition = bar(99.0, 109.0, 98.5, 108.0, volume=1_000_000)
        df = make_breakout_chart(ignition=ignition)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "volume" in " ".join(result.reasons)

    def test_the_spike_floor_comes_from_config_not_the_code(self, brk_cfg):
        df = make_breakout_chart()
        lenient = replace(brk_cfg, breakout_volume_spike_min=1.1)
        strict = replace(brk_cfg, breakout_volume_spike_min=2.5)
        assert screen_breakout(df, quote_from(df), lenient).passed
        assert not screen_breakout(df, quote_from(df), strict).passed


class TestIgnitionBarGate:
    def test_must_be_bigger_than_the_baby_bar(self, brk_cfg):
        # Body 3 on the baby bar, body 2.5 on the "igniting" bar: still clears
        # the absolute size floor (2.5 / 101.5 = 2.5%) but is not bigger than
        # the bar before it, so only the relative check should fail.
        baby = bar(96.0, 99.3, 95.7, 99.0, volume=1_000_000)
        ignition = bar(99.0, 102.0, 98.7, 101.5, volume=2_000_000)
        follow = bar(101.5, 103.5, 101.2, 103.0, volume=1_200_000)
        df = make_breakout_chart(baby=baby, ignition=ignition, follow=follow)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "not bigger than the baby" in " ".join(result.reasons)

    def test_must_clear_the_absolute_body_floor(self, brk_cfg):
        # Bigger than the baby bar (0.5 vs 0.1) but only 0.47% of its own
        # close, well under the 1.5% floor for a bar the rulebook calls "big".
        baby = bar(98.9, 99.05, 98.85, 99.0, volume=1_000_000)
        ignition = bar(105.0, 106.0, 104.5, 105.5, volume=2_000_000)
        follow = bar(105.5, 107.5, 105.2, 107.0, volume=1_200_000)
        df = make_breakout_chart(baby=baby, ignition=ignition, follow=follow)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "under the" in " ".join(result.reasons) and "floor for a big bar" in " ".join(
            result.reasons
        )


class TestBabyBarWickDisqualifier:
    def test_a_massive_wick_disqualifies_the_setup(self, brk_cfg):
        # Body 1, wick 9 over a range of 10: a 90% wick, the fat-wick baby bar
        # the build plan names directly.
        baby = bar(98.0, 104.0, 94.0, 99.0, volume=1_000_000)
        df = make_breakout_chart(baby=baby)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "wick" in " ".join(result.reasons)

    def test_the_wick_floor_comes_from_config_not_the_code(self, brk_cfg):
        baby = bar(98.0, 104.0, 94.0, 99.0, volume=1_000_000)
        df = make_breakout_chart(baby=baby)
        lenient = replace(brk_cfg, breakout_baby_max_wick_pct=95.0)
        assert screen_breakout(df, quote_from(df), lenient).passed


class TestFollowThroughGate:
    def test_a_red_second_candle_fails(self, brk_cfg):
        follow = bar(110.0, 110.5, 106.5, 107.0, volume=1_200_000)  # closes under its open
        df = make_breakout_chart(follow=follow)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert not result.passed
        assert "red" in " ".join(result.reasons)

    def test_no_follow_through_bar_yet_still_passes(self, brk_cfg):
        # The breakout happened on the most recent bar, so there is nothing to
        # judge yet. That is not a failure, it is a "come back tomorrow".
        df = make_breakout_chart(include_follow=False)
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert result.passed
        assert "no follow-through" in " ".join(result.reasons)


class TestTextbookBreakout:
    def test_a_textbook_breakout_passes(self, brk_cfg):
        df = make_breakout_chart()
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert result.passed
        assert result.score > 0

    def test_a_pass_explains_itself_with_real_numbers(self, brk_cfg):
        df = make_breakout_chart()
        result = screen_breakout(df, quote_from(df), brk_cfg)
        # The ignition body (9.00) and its percentage of close should both show
        # up somewhere in the reasoning, not just a bare "ignition bar: pass".
        joined = " ".join(result.reasons)
        assert "9.00" in joined
        assert "%" in joined

    def test_a_failure_explains_itself(self, brk_cfg):
        df = make_bars([100 + i for i in range(40)])
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert result.reasons


class TestDipAndRejectBonus:
    def test_the_dip_and_reject_raises_the_score(self, brk_cfg):
        baseline = make_breakout_chart()
        base_result = screen_breakout(baseline, quote_from(baseline), brk_cfg)

        # One extra bar: low dips within tolerance of the 100 level, then the
        # same bar closes back above it. The rulebook's preferred pattern.
        dip = bar(109.0, 109.5, 100.8, 101.0, volume=1_200_000)
        with_dip = make_breakout_chart(extra=[dip])
        dip_result = screen_breakout(with_dip, quote_from(with_dip), brk_cfg)

        assert base_result.passed and dip_result.passed
        assert dip_result.score == pytest.approx(
            base_result.score + brk_cfg.breakout_dip_reject_bonus, abs=0.01
        )

    def test_missing_the_dip_is_not_a_failure(self, brk_cfg):
        # The baseline chart never dips back to the level at all, and the
        # rulebook is explicit that the pattern "does not always appear".
        df = make_breakout_chart()
        result = screen_breakout(df, quote_from(df), brk_cfg)
        assert result.passed


class TestScoreComposition:
    def test_score_reads_a_weight_from_config_not_the_code(self, brk_cfg):
        # Ignition strength is capped at exactly 1.0 by the default baby/ignition
        # bars, so isolating that weight gives an exact, not approximate, score.
        isolated = replace(
            brk_cfg, w_breakout_volume=0.0, w_breakout_ignition=1.0, w_breakout_recency=0.0
        )
        df = make_breakout_chart()
        result = screen_breakout(df, quote_from(df), isolated)
        assert result.score == pytest.approx(1.0)

    def test_a_stronger_volume_spike_scores_higher(self, brk_cfg):
        weak = bar(99.0, 109.0, 98.5, 108.0, volume=1_600_000)  # 1.6x, just past the floor
        strong = bar(99.0, 109.0, 98.5, 108.0, volume=3_500_000)  # well past the strong ceiling
        weak_df = make_breakout_chart(ignition=weak)
        strong_df = make_breakout_chart(ignition=strong)
        weak_score = screen_breakout(weak_df, quote_from(weak_df), brk_cfg).score
        strong_score = screen_breakout(strong_df, quote_from(strong_df), brk_cfg).score
        assert strong_score > weak_score

    def test_a_fresher_break_scores_higher_than_a_stale_one(self, brk_cfg):
        # Same baby / ignition / follow-through bars and the same volume in
        # both charts, so volume_strength and ignition_strength are identical
        # between them; only the buffer length changes, which only moves the
        # resistance level's recency. If `level.recency` were hardcoded inside
        # the screen instead of actually read, these two scores would come out
        # equal and this test would catch it.
        #
        #   fresh: buffer_bars=6  -> len(df)=22, last index 21
        #     age = 21 - last_touch(10) = 11
        #     recency = 1 - (11 - level_fresh_days(10)) / (60 - 10) = 1 - 1/50 = 0.98
        #   stale: buffer_bars=30 -> len(df)=46, last index 45
        #     age = 45 - last_touch(10) = 35
        #     recency = 1 - (35 - 10) / 50 = 1 - 25/50 = 0.50
        #
        # Both charts still pass every gate: the extra buffer bars sit at 95.0,
        # below the 100 level, so they never disturb the baby/ignition/follow
        # sequence or the breaking-bar search, which lands on the same two
        # bars either way (proven by the buffer_bars docstring in
        # make_breakout_chart).
        fresh_df = make_breakout_chart(buffer_bars=6)
        stale_df = make_breakout_chart(buffer_bars=30)
        fresh_result = screen_breakout(fresh_df, quote_from(fresh_df), brk_cfg)
        stale_result = screen_breakout(stale_df, quote_from(stale_df), brk_cfg)
        assert fresh_result.passed and stale_result.passed
        assert fresh_result.score > stale_result.score
