"""The breakout screen, tested against what the course actually says.

This file was rewritten after an audit found the screen had the source
inverted: it gated on the 3-bar setup, which page 79 calls "just another
elevating factor", and scored the retest as a garnish, when pages 75 and 76
make the retest the whole point. The old tests encoded the wrong rules
faithfully, which is the failure mode nobody notices — a green suite proving
the software does the wrong thing correctly.

Every chart shares one scaffold: a three-touch struggle at resistance 100, a
bar that breaks it, a small test bar, a confirmation bar, then a pullback to
the level that closes back above it. Each test overrides exactly the bars that
carry the rule under test.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from helpers import quote_from
from stocksignal.config import Config
from stocksignal.screens.breakout import screen_breakout


def bar(open_: float, high: float, low: float, close: float, volume: float = 1_000_000) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close, "volume": float(volume)}


def flat(price: float, volume: float = 1_000_000) -> dict:
    return bar(price, price, price, price, volume)


@pytest.fixture
def cfg() -> Config:
    """Small windows so a hand-built chart stays short enough to reason about."""
    return Config(
        sma_fast=5,
        sma_slow=10,
        min_history_days=10,
        avg_volume_window=10,
        level_swing_lookback=2,
        level_tolerance_pct=1.0,
        level_min_touches=3,
        level_lookback_days=60,
        level_break_lookback=6,
        breakout_retest_window=10,
    )


# The struggle: three touches of 100 and back down, which is what makes 100 a
# level rather than a coincidence.
STRUGGLE = [flat(p) for p in [90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 100, 95, 90, 95]]

# Body 9.0 on a 10.5 range, on double volume: an unambiguous break of 100.
IGNITE = bar(96.0, 106.0, 95.5, 105.0, volume=2_000_000)
# Body 0.5, and its low stays well above the ignition bar's low.
BABY = bar(105.0, 106.0, 103.0, 104.5)
# Holds above the baby.
CONFIRM = bar(104.5, 108.0, 104.0, 107.0)
# A break that runs away and is never tested: baby, confirm, then two more up bars.
NEVER_TESTED = [
    bar(105.0, 106.0, 103.0, 104.5),
    bar(104.5, 108.0, 104.0, 107.0),
    bar(107.0, 112.0, 106.5, 111.0),
    bar(111.0, 115.0, 110.5, 114.0),
]
# The pullback to the level...
DIP = bar(107.0, 107.0, 100.5, 101.0)
# ...and the close back above it. This pair is the retest.
RECOVER = bar(101.0, 106.0, 100.8, 105.0)


def chart(*, tail: list[dict] | None = None, **overrides) -> pd.DataFrame:
    """The scaffold, with named bars swapped out by keyword."""
    named = {"ignite": IGNITE, "baby": BABY, "confirm": CONFIRM, "dip": DIP, "recover": RECOVER}
    named.update({k: v for k, v in overrides.items() if v is not None})
    rows = STRUGGLE + [named[n] for n in ("ignite", "baby", "confirm", "dip", "recover")]
    if tail is not None:
        # Everything after the igniting bar, for tests that need a different
        # number of bars rather than different ones.
        rows = STRUGGLE + [named["ignite"]] + tail
    index = pd.bdate_range(end=pd.Timestamp("2026-08-07"), periods=len(rows))
    return pd.DataFrame(rows, index=index)[["open", "high", "low", "close", "volume"]]


def run(df: pd.DataFrame, cfg: Config):
    return screen_breakout(df, quote_from(df), cfg)


class TestTheScaffoldItself:
    def test_the_textbook_setup_passes(self, cfg):
        result = run(chart(), cfg)
        assert result.passed, result.reasons
        assert result.score > 0


class TestTheRetestIsAGate:
    """The correction this rewrite exists for.

    Page 75: "if you want to trade a quality breakout, wait until a push back
    and start showing price strength again." Page 76: "this reassurance is
    key." The chapter's takeaway box lists two items and both are the retest.
    The old screen scored it as a +0.3 bonus.
    """

    def test_a_break_with_no_pullback_yet_does_not_pass(self, cfg):
        # Price breaks out and runs away without ever being tested.
        result = run(chart(tail=NEVER_TESTED), cfg)
        assert not result.passed
        assert any("retested" in r for r in result.reasons)

    def test_the_rejection_says_unfinished_rather_than_failed(self, cfg):
        # A breakout waiting for its pullback is not a bad setup, and the digest
        # has to say which of the two it is or the reader learns nothing.
        reasons = " ".join(run(chart(tail=NEVER_TESTED), cfg).reasons)
        assert "unfinished rather than failed" in reasons

    def test_a_dip_that_never_recovers_does_not_count(self, cfg):
        # Touching the level is half of it. Holding above it is the other half.
        result = run(chart(recover=bar(101.0, 101.5, 98.0, 99.0)), cfg)
        assert not result.passed

    def test_a_retest_outside_the_window_does_not_count(self, cfg):
        # A pullback three months later is a separate event that happens to be
        # near the same price, not a test of this break.
        result = run(chart(), replace(cfg, breakout_retest_window=1))
        assert not result.passed

    def test_the_gate_can_be_turned_off(self, cfg):
        loose = replace(cfg, breakout_require_retest=False)
        assert run(chart(tail=NEVER_TESTED), loose).passed


class TestTheHealthyUptrendGate:
    """Page 75 opens the quality section with it, so it is a gate."""

    def test_a_close_below_the_slow_average_fails(self, cfg):
        # The retest still holds (102 is above the level), but the last three
        # closes average 103.3, so price is fading rather than trending.
        fading = replace(cfg, sma_fast=2, sma_slow=3)
        result = run(chart(recover=bar(101.0, 106.0, 100.8, 102.0)), fading)
        assert not result.passed
        assert any("uptrend" in r or "average" in r for r in result.reasons)

    def test_too_little_history_to_judge_the_trend_fails_honestly(self, cfg):
        result = run(chart(), replace(cfg, sma_slow=500, min_history_days=500))
        assert not result.passed
        assert "not enough history" in " ".join(result.reasons)


class TestTheThreeBarSetupIsAnElevatingFactor:
    """Page 79: "this is just another elevating factor in our favor.\""""

    def test_a_missing_setup_lowers_the_score_but_still_passes(self, cfg):
        # The baby bar is bigger than the ignition bar, so there is no setup.
        # Under the old screen this was a hard failure.
        fat = bar(105.0, 118.0, 104.0, 117.0)
        result = run(chart(baby=fat, confirm=bar(117.0, 120.0, 116.0, 119.0)), cfg)
        assert result.passed, result.reasons
        assert result.score < run(chart(), cfg).score

    def test_the_setup_is_ignite_then_baby_then_confirm_in_that_order(self, cfg):
        # Page 77: "we get an uptrend then with the IGNITE, then we test this
        # direction change using the BABY and then we have the CONFIRMATION
        # using the 3rd bar." The old code compared the breaking bar to the bar
        # BEFORE it, and quoted the rulebook as saying "before it" — two words
        # that appear in no source.
        reasons = " ".join(run(chart(), cfg).reasons)
        assert "3-bar setup" in reasons

    def test_two_baby_bars_are_credited_as_the_four_bar_variant(self, cfg):
        # Page 81: two baby bars "could be even slightly better because we have
        # 2 tests of price strengths".
        four_bar = [
            bar(105.0, 106.0, 103.0, 104.5),  # baby one
            bar(104.5, 105.5, 103.5, 104.0),  # baby two
            bar(104.0, 108.0, 103.8, 107.0),  # confirmation
            DIP,
            RECOVER,
        ]
        result = run(chart(tail=four_bar), cfg)
        assert result.passed, result.reasons
        assert "4-bar setup" in " ".join(result.reasons)

    def test_a_fat_baby_is_positional_not_a_percentage(self, cfg):
        # Page 80: "when the WICK passed below the IGNITION bar". The old screen
        # measured total wick as a share of the baby's own range against an
        # invented 60% threshold, which is a different quantity entirely.
        # Ignition low is 95.5, so a baby dipping to 95.0 gave the whole move back.
        fat_baby = bar(105.0, 106.0, 95.0, 104.5)
        result = run(chart(baby=fat_baby), cfg)
        assert result.passed, "a fat baby removes the bonus, it does not reject the breakout"
        assert "fat baby" in " ".join(result.reasons)
        assert result.score < run(chart(), cfg).score

    def test_a_baby_with_a_big_wick_that_stays_above_the_ignite_is_fine(self, cfg):
        # 60% of range in wick, but it never dipped below the ignition bar, so
        # the course has no objection. The old threshold rejected this.
        wicky = bar(104.6, 106.5, 103.0, 104.5)
        assert run(chart(baby=wicky), cfg).passed


class TestTheOverboughtPenalty:
    """Pages 72 to 74 call an extreme entry a deprecating factor, not a bar."""

    def test_an_overbought_entry_costs_score_but_still_passes(self, cfg):
        strict = replace(cfg, rsi_oversold=0.5, rsi_overbought=1.0)  # force the penalty on
        result = run(chart(), strict)
        assert result.passed
        assert "deprecating" in " ".join(result.reasons)
        assert result.score < run(chart(), replace(cfg, rsi_overbought=99.0)).score

    def test_the_score_never_goes_negative(self, cfg):
        harsh = replace(cfg, rsi_oversold=0.5, rsi_overbought=1.0, breakout_overbought_penalty=10.0)
        assert run(chart(), harsh).score >= 0.0


class TestScoring:
    def test_a_stronger_volume_spike_scores_higher(self, cfg):
        quiet = run(chart(ignite=replace_volume(IGNITE, 1_600_000)), cfg)
        loud = run(chart(ignite=replace_volume(IGNITE, 5_000_000)), cfg)
        assert quiet.passed and loud.passed
        assert loud.score > quiet.score

    def test_volume_is_not_a_gate(self, cfg):
        # The course never makes it one; it calls a spike "a lot of investor
        # interest", which is an elevating factor.
        result = run(chart(ignite=replace_volume(IGNITE, 200_000)), cfg)
        assert result.passed, result.reasons

    def test_the_weights_come_from_config_not_the_code(self, cfg):
        base = run(chart(), cfg).score
        heavier = run(chart(), replace(cfg, w_breakout_volume=2.0)).score
        assert heavier > base


class TestTheResistanceGate:
    def test_no_level_at_all_fails(self, cfg):
        drift = pd.DataFrame(
            [flat(90.0 + i * 0.5) for i in range(25)],
            index=pd.bdate_range(end=pd.Timestamp("2026-08-07"), periods=25),
        )[["open", "high", "low", "close", "volume"]]
        result = run(drift, cfg)
        assert not result.passed
        assert "three-touch" in " ".join(result.reasons)

    def test_a_break_older_than_the_window_fails(self, cfg):
        result = run(chart(), replace(cfg, level_break_lookback=1))
        assert not result.passed
        assert "too old to act on" in " ".join(result.reasons)


def replace_volume(row: dict, volume: float) -> dict:
    return {**row, "volume": float(volume)}
