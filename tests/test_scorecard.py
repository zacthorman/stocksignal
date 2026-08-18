"""Tests for the twelve-factor scorecard.

The ones that matter are the abstention tests. A model that quietly scores an
unmeasurable factor as zero looks identical to one that measures it and finds
nothing, and the difference is the whole reason `coverage` exists.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.models import Quote
from stocksignal.scorecard import (
    FACTORS,
    Factor,
    Scorecard,
    score_ticker,
    to_dict,
)


def frame(closes: list[float], volume: float = 1_000_000) -> pd.DataFrame:
    """Bars with a given close path. Highs and lows sit a fixed 1% either side."""
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    close = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(len(close), volume, dtype=float),
        },
        index=idx,
    )


def quote_for(df: pd.DataFrame, ticker: str = "TEST") -> Quote:
    return Quote(
        ticker=ticker,
        as_of=df.index[-1].date(),
        close=float(df["close"].iloc[-1]),
        avg_volume=float(df["volume"].iloc[-20:].mean()),
        latest_volume=float(df["volume"].iloc[-1]),
    )


def rising(n: int = 600, start: float = 20.0, step: float = 0.05) -> pd.DataFrame:
    return frame([start + step * i for i in range(n)])


# --------------------------------------------------------------------------
# Abstention: the reason this model is not a plain float.
# --------------------------------------------------------------------------


def test_unfetchable_factors_abstain_rather_than_scoring_zero():
    df = rising()
    card = score_ticker(df, quote_for(df))
    by_key = {f.key: f for f in card.factors}
    for key in ("catalyst", "analyst"):
        assert by_key[key].points is None, f"{key} must abstain, not score"
        assert by_key[key].fraction is None
    assert "Clear catalyst" in card.unmeasured
    assert "No analyst downgrade" in card.unmeasured


def test_coverage_falls_when_a_factor_abstains():
    df = rising()
    card = score_ticker(df, quote_for(df))
    assert card.coverage < 1.0
    assert card.coverage == pytest.approx(len(card.measured_factors) / len(card.factors))


def test_an_abstaining_factor_does_not_drag_the_score_down():
    """A card of all-perfect measured factors still scores 100 with two abstentions.

    This is the property that makes abstention safe. If the two unfetchable
    factors were scored zero instead, the ceiling would be 83 and every name
    would be marked down for data the tool never had.
    """
    weight = 100 / 12
    factors = tuple(
        Factor(
            key=spec.key,
            label=spec.label,
            kind=spec.kind,
            source=spec.source,
            weight=weight,
            points=None if spec.key in ("catalyst", "analyst") else weight,
            value=None,
            detail="",
        )
        for spec in FACTORS
    )
    card = Scorecard(
        ticker="T", as_of=pd.Timestamp("2026-01-01").date(), close=1.0, factors=factors
    )
    assert card.score == pytest.approx(100.0)
    assert card.coverage == pytest.approx(10 / 12)


def test_a_card_with_nothing_measurable_scores_zero_and_does_not_divide_by_zero():
    factors = tuple(
        Factor(spec.key, spec.label, spec.kind, spec.source, 100 / 12, None, None, "")
        for spec in FACTORS
    )
    card = Scorecard(
        ticker="T", as_of=pd.Timestamp("2026-01-01").date(), close=1.0, factors=factors
    )
    assert card.score == 0.0
    assert card.coverage == 0.0


# --------------------------------------------------------------------------
# The factors themselves.
# --------------------------------------------------------------------------


def test_directional_strength_is_zero_below_the_slow_sma():
    """A long decline puts price under the 180 SMA, which is the regime line."""
    df = frame([50.0 - 0.05 * i for i in range(600)])
    card = score_ticker(df, quote_for(df))
    factor = next(f for f in card.factors if f.key == "directional_strength")
    assert factor.points == 0.0
    assert "below the 180 SMA" in factor.detail


def test_directional_strength_scores_above_the_slow_sma():
    df = rising()
    factor = next(f for f in score_ticker(df, quote_for(df)).factors
                  if f.key == "directional_strength")
    assert factor.points is not None and factor.points > 0
    assert "above the 180 SMA" in factor.detail


def test_confirmation_decays_with_distance_from_the_cross():
    """The course calls confirmation an event. A fresh cross must outrank a stale one.

    This is the difference the repo already has on the record as an open note:
    `trend.py` asks whether price is above the line at all, which stays true for
    a whole run. Here it is a gradient, so the two readings can be compared
    rather than argued about.
    """
    fresh = frame([30.0] * 400 + [20.0] * 100 + [31.0])
    stale = rising()
    f_fresh = next(f for f in score_ticker(fresh, quote_for(fresh)).factors
                   if f.key == "confirmation")
    f_stale = next(f for f in score_ticker(stale, quote_for(stale)).factors
                   if f.key == "confirmation")
    assert f_fresh.points > f_stale.points


def test_deal_quality_grades_oversold_above_fair_value_above_overbought():
    oversold = frame([100.0 - 1.0 * i for i in range(300)] + [40.0] * 200 + [39.0])
    overbought = rising()
    f_os = next(f for f in score_ticker(oversold, quote_for(oversold)).factors
                if f.key == "deal_quality")
    f_ob = next(f for f in score_ticker(overbought, quote_for(overbought)).factors
                if f.key == "deal_quality")
    assert f_os.points > f_ob.points


def test_volume_reads_the_ratio_not_a_boolean():
    df = rising()
    quiet = quote_for(df)
    loud = Quote(
        ticker="TEST", as_of=quiet.as_of, close=quiet.close,
        avg_volume=quiet.avg_volume, latest_volume=quiet.avg_volume * 4,
    )
    f_quiet = next(f for f in score_ticker(df, quiet).factors if f.key == "volume")
    f_loud = next(f for f in score_ticker(df, loud).factors if f.key == "volume")
    assert f_loud.points > f_quiet.points
    assert f_loud.points == pytest.approx(f_loud.weight)  # 4x is past the strong ceiling


def test_long_term_prefers_a_name_low_in_its_range():
    """The one factor where a high price scores badly, matching the page 142 sort."""
    at_high = rising()
    off_high = frame([20.0 + 0.05 * i for i in range(500)] + [30.0 - 0.1 * i for i in range(100)])
    f_high = next(f for f in score_ticker(at_high, quote_for(at_high)).factors
                  if f.key == "long_term")
    f_off = next(f for f in score_ticker(off_high, quote_for(off_high)).factors
                 if f.key == "long_term")
    assert f_off.points > f_high.points


# --------------------------------------------------------------------------
# Config is read, not hard-coded. The repo's rule 1.
# --------------------------------------------------------------------------


def test_factors_read_their_thresholds_from_config():
    """A deliberately silly config must change the answer.

    The repo's first convention is that a bare threshold inside a screen is a
    bug, and the stated way to prove it is to pass an absurd value and watch
    the verdict move.
    """
    # A monotonic path pins RSI at 100 and no threshold can move it, so this
    # needs a series that actually oscillates. That is itself worth knowing:
    # the fixture has to be non-degenerate for the assertion to mean anything.
    df = frame([20.0 + 0.05 * i + (2.0 if i % 2 else -2.0) for i in range(600)])
    q = quote_for(df)
    normal = score_ticker(df, q, DEFAULT_CONFIG)
    silly = Config(rsi_oversold=99.0, rsi_overbought=99.5)
    changed = score_ticker(df, q, silly)
    a = next(f for f in normal.factors if f.key == "deal_quality")
    b = next(f for f in changed.factors if f.key == "deal_quality")
    assert a.points != b.points


# --------------------------------------------------------------------------
# Re-weighting, which is what the dashboard does in the browser.
# --------------------------------------------------------------------------


def test_rescore_matches_the_default_score_under_the_default_weights():
    df = rising()
    card = score_ticker(df, quote_for(df))
    weights = {spec.key: spec.weight for spec in FACTORS}
    assert card.rescore(weights) == pytest.approx(card.score)


def test_zeroing_a_weight_removes_that_factor_entirely():
    df = rising()
    card = score_ticker(df, quote_for(df))
    strongest = max(card.measured_factors, key=lambda f: f.fraction)
    weights = {spec.key: spec.weight for spec in FACTORS}
    weights[strongest.key] = 0.0
    assert card.rescore(weights) < card.score


def test_every_factor_carries_a_reason():
    """Rule 3 of the repo: the reasoning is the product, not logging."""
    df = rising()
    for factor in score_ticker(df, quote_for(df)).factors:
        assert factor.detail.strip(), f"{factor.key} shipped without a reason"


def test_to_dict_exports_fraction_separately_from_points():
    """The dashboard re-weights client side, so it needs the reading unweighted."""
    df = rising()
    payload = to_dict(score_ticker(df, quote_for(df)))
    assert set(payload) >= {"ticker", "score", "band", "coverage", "unmeasured", "factors"}
    for f in payload["factors"]:
        if f["fraction"] is None:
            assert f["points"] is None
        else:
            assert f["points"] == pytest.approx(f["fraction"] * f["weight"], rel=1e-3)


def test_bands_are_ordered_and_reachable():
    for floor, name, _note in (
        (85.0, "STRONG", ""), (70.0, "WORTH A LOOK", ""), (50.0, "WATCH", ""), (10.0, "SKIP", "")
    ):
        card = Scorecard(
            ticker="T",
            as_of=pd.Timestamp("2026-01-01").date(),
            close=1.0,
            factors=(Factor("k", "l", "gate", "s", 100.0, floor, None, "x"),),
        )
        assert card.band[0] == name
