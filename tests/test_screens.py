"""Screen behaviour: does each rule from the rulebook actually fire?

Every test here maps to a line in the written strategy. If a rule changes, a
test changes with it, and the diff shows exactly which rule moved.
"""

from __future__ import annotations

from helpers import make_bars, quote_from
from stocksignal.config import Config
from stocksignal.screens import screen_tradability, screen_trend


class TestTradabilityGate:
    def test_liquid_large_float_ticker_passes(self, cfg, rising_bars):
        q = quote_from(rising_bars, shares_float=50_000_000)
        assert screen_tradability(rising_bars, q, cfg).passed

    def test_thin_volume_is_rejected(self, cfg):
        bars = make_bars([100.0] * 80, volume=50_000)
        result = screen_tradability(bars, quote_from(bars), cfg)
        assert not result.passed
        assert "avg volume" in result.reasons[0]

    def test_low_float_is_rejected(self, cfg, rising_bars):
        q = quote_from(rising_bars, shares_float=1_000_000)
        result = screen_tradability(rising_bars, q, cfg)
        assert not result.passed
        assert "low float" in " ".join(result.reasons)

    def test_unknown_float_passes_but_warns(self, cfg, rising_bars):
        q = quote_from(rising_bars, shares_float=None)
        result = screen_tradability(rising_bars, q, cfg)
        assert result.passed
        assert any("float unknown" in r for r in result.reasons)

    def test_short_history_is_rejected(self, cfg):
        bars = make_bars([100.0 + i for i in range(15)])
        result = screen_tradability(bars, quote_from(bars), cfg)
        assert not result.passed
        assert "history" in " ".join(result.reasons)

    def test_the_volume_floor_comes_from_config_not_the_code(self, rising_bars):
        strict = Config(sma_fast=5, sma_slow=10, min_history_days=20, min_avg_volume=9_000_000)
        assert not screen_tradability(rising_bars, quote_from(rising_bars), strict).passed


class TestTrendScreen:
    def test_clean_uptrend_passes(self, cfg, rising_bars):
        result = screen_trend(rising_bars, quote_from(rising_bars), cfg)
        assert result.passed
        assert result.score > 0

    def test_downtrend_fails(self, cfg, falling_bars):
        result = screen_trend(falling_bars, quote_from(falling_bars), cfg)
        assert not result.passed

    def test_sideways_chop_fails(self, cfg, flat_bars):
        assert not screen_trend(flat_bars, quote_from(flat_bars), cfg).passed

    def test_a_gap_under_the_floor_is_chop_not_a_trend(self, cfg):
        creeping = make_bars([100 + i * 0.05 for i in range(80)])
        result = screen_trend(creeping, quote_from(creeping), cfg)
        assert not result.passed
        assert "chop" in " ".join(result.reasons)

    def test_score_rises_with_the_sma_gap(self, cfg):
        gentle = make_bars([100 + i * 0.6 for i in range(80)])
        steep = make_bars([100 + i * 3.0 for i in range(80)])
        gentle_score = screen_trend(gentle, quote_from(gentle), cfg).score
        steep_score = screen_trend(steep, quote_from(steep), cfg).score
        assert steep_score > gentle_score

    def test_score_is_capped_at_one(self, cfg):
        vertical = make_bars([100 * (1.08**i) for i in range(80)])
        assert screen_trend(vertical, quote_from(vertical), cfg).score <= 1.0

    def test_not_enough_history_fails_cleanly(self, cfg):
        bars = make_bars([100.0, 101.0, 102.0])
        result = screen_trend(bars, quote_from(bars), cfg)
        assert not result.passed
        assert "history" in " ".join(result.reasons)

    def test_a_pass_always_explains_itself(self, cfg, rising_bars):
        result = screen_trend(rising_bars, quote_from(rising_bars), cfg)
        assert result.reasons, "every result must carry its reasoning"

    def test_a_failure_always_explains_itself(self, cfg, falling_bars):
        result = screen_trend(falling_bars, quote_from(falling_bars), cfg)
        assert result.reasons
