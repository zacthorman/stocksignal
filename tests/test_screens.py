"""Screen behaviour: does each rule from the rulebook actually fire?

Every test here maps to a line in the written strategy. If a rule changes, a
test changes with it, and the diff shows exactly which rule moved.
"""

from __future__ import annotations

import pytest

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

    def test_a_penny_stock_is_rejected_on_price(self, cfg):
        # Course page 142: 15 dollars is the swing floor. A 4 dollar stock can
        # clear every other gate and still not be swingable.
        bars = make_bars([4.0] * 80)
        result = screen_tradability(bars, quote_from(bars), cfg)
        assert not result.passed
        assert "swing floor" in " ".join(result.reasons)

    def test_low_beta_is_rejected(self, cfg, rising_bars):
        q = quote_from(rising_bars, beta=0.9)
        result = screen_tradability(rising_bars, q, cfg)
        assert not result.passed
        assert "beta" in " ".join(result.reasons)

    def test_high_beta_passes(self, cfg, rising_bars):
        q = quote_from(rising_bars, beta=2.5)
        assert screen_tradability(rising_bars, q, cfg).passed

    def test_unknown_beta_passes_but_warns(self, cfg, rising_bars):
        # Same contract as an unknown float: a gap in the data is not evidence
        # against the stock, so it is surfaced rather than acted on.
        result = screen_tradability(rising_bars, quote_from(rising_bars), cfg)
        assert result.passed
        assert any("beta unknown" in r for r in result.reasons)


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


class TestRelativeGapScoring:
    """Scoring the gap against the ticker's own history rather than a fixed number.

    The problem this exists to solve: with a slow average as long as 180, the gap
    mostly measures how volatile a stock is. A fixed percentage ceiling therefore
    scores a crypto miner as permanently strong and an index fund as permanently
    weak, which is a statement about volatility wearing a trend's clothing.
    """

    def _cfg(self, **kw):
        base = dict(
            sma_fast=5,
            sma_slow=10,
            min_history_days=20,
            avg_volume_window=10,
            min_sma_gap_pct=0.5,
            sma_gap_strong_pct=5.0,
            gap_scoring="relative",
            gap_relative_min_samples=10,
        )
        return Config(**{**base, **kw})

    def test_an_unusually_wide_gap_for_this_stock_scores_high(self):
        # Long steady climb, then an acceleration. The final bar's gap should
        # rank near the top of the stock's own readings.
        closes = [100 + i * 0.4 for i in range(120)] + [148 + i * 4.0 for i in range(10)]
        df = make_bars(closes)
        result = screen_trend(df, quote_from(df), self._cfg())
        assert result.passed
        assert result.score > 0.9
        assert "its own" in " ".join(result.reasons) or "own" in " ".join(result.reasons)

    def test_a_typical_gap_for_this_stock_scores_mid(self):
        df = make_bars([100 * (1.004**i) for i in range(160)])
        result = screen_trend(df, quote_from(df), self._cfg())
        assert result.passed
        assert 0.1 < result.score < 0.99

    def test_the_score_is_a_percentile_so_it_never_leaves_the_unit_range(self):
        df = make_bars([100 * (1.02**i) for i in range(160)])
        result = screen_trend(df, quote_from(df), self._cfg())
        assert 0.0 <= result.score <= 1.0

    def test_too_little_history_falls_back_and_says_so(self):
        df = make_bars([100 + i * 1.5 for i in range(40)])
        result = screen_trend(df, quote_from(df), self._cfg(gap_relative_min_samples=500))
        assert result.passed
        joined = " ".join(result.reasons)
        assert "under the 500" in joined
        assert "fixed" in joined

    def test_absolute_and_relative_disagree_on_the_same_chart(self):
        # The point of having both. If they always agreed there would be
        # nothing for the backtest to choose between.
        df = make_bars([100 * (1.01**i) for i in range(160)])
        q = quote_from(df)
        absolute = screen_trend(df, q, self._cfg(gap_scoring="absolute")).score
        relative = screen_trend(df, q, self._cfg()).score
        assert absolute != pytest.approx(relative)

    def test_an_unknown_scoring_mode_is_rejected_at_config_time(self):
        with pytest.raises(ValueError, match="gap_scoring"):
            Config(gap_scoring="vibes")

    def test_relative_mode_asks_for_more_history(self):
        absolute = Config(gap_scoring="absolute")
        relative = Config(gap_scoring="relative")
        assert relative.required_history > absolute.required_history
