"""Tests for the opportunity card.

Two kinds of test in here, and the second kind is the point.

The ordinary kind builds a frame with a deliberate shape and asserts on the
maths. The other kind asserts on what the card REFUSES to do: no target without
a growth direction, no score from the ledger, no silent stop on the ratio's own
support. Those are the properties that make the card trustworthy, and a
property nobody tests is a property that quietly disappears in six months.

The two worked examples from the course (RAD, pages 219 to 225, and JMIA, pages
226 to 232) are reproduced as tests. If a refactor changes the arithmetic, the
course's own numbers stop coming out, which is a far better failure signal than
any hand-invented fixture.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from helpers import make_bars
from stocksignal.card_render import (
    render_card_markdown,
    render_card_telegram,
    render_cards_telegram,
)
from stocksignal.config import Config
from stocksignal.levels import RESISTANCE, SUPPORT, Level
from stocksignal.opportunity import (
    BIG,
    DISCOUNTED,
    HUMAN,
    MODEL,
    MOMENTUM,
    NEGATIVE,
    POSITIVE,
    UNATTRIBUTED,
    UNKNOWN,
    CardConfig,
    GrowthDirection,
    build_card,
    classify_play,
    discounted_target,
    hard_stop,
    median_anchor,
    momentum_target,
    position_plan,
    reward_risk,
)


def level(price: float, kind: str, touches: int = 3) -> Level:
    return Level(
        price=price,
        touches=touches,
        first_touch=date(2025, 1, 1),
        last_touch=date(2026, 1, 1),
        kind=kind,
    )


POSITIVE_CALL = GrowthDirection(
    POSITIVE, ("quarterly revenue up 11.5%",), date(2026, 8, 11), "test"
)


# --- The median anchor -----------------------------------------------------------


def test_median_is_the_midpoint_of_the_range_not_of_the_closes():
    """Page 220 eyeballs the middle of the visible channel, which is the range.

    The frame is deliberately skewed: most bars sit near 10, a few spike to 40.
    A close-median lands near 10; the range midpoint lands near 25. The course
    draws the second one.
    """
    closes = [10.0] * 90 + [40.0] * 10
    median, basis = median_anchor(make_bars(closes), CardConfig())

    low, high = 10.0 * 0.99, 40.0 * 1.01
    assert median == pytest.approx((low + high) / 2.0)
    assert any("median of closes" in b for b in basis)
    assert any("skewed year" in b for b in basis)


def test_median_includes_the_crash_rather_than_trimming_it():
    """Page 220: "We need to include everything on the price chart for that year"."""
    steady = [100.0] * 200
    with_crash = steady[:100] + [40.0] + steady[101:]

    without, _ = median_anchor(make_bars(steady), CardConfig())
    with_it, _ = median_anchor(make_bars(with_crash), CardConfig())

    assert with_it < without, "the crash must move the anchor, not be trimmed away"


def test_short_history_is_reported_not_hidden():
    _, basis = median_anchor(make_bars([100.0] * 30), CardConfig())
    assert any("only 30 sessions" in b for b in basis)


# --- Which method applies --------------------------------------------------------


def test_play_type_splits_on_the_median():
    """RAD at 9 against a 14 median is discounted; JMIA at 38 against 20 is momentum."""
    assert classify_play(9.0, 14.0) == DISCOUNTED
    assert classify_play(38.13, 20.0) == MOMENTUM
    assert classify_play(14.0, 14.0) == "at median"


# --- The discounted target, and the course's RAD numbers -------------------------


def test_rad_worked_example_from_pages_224_to_225():
    """The course sets RAD's target at 17 as the midpoint of two resistances.

    Page 225: "So we set the price target right in the middle of these two
    Resistance levels i.e. 17$." With the median at 14 and resistances at 15.5
    and 18.5, the midpoint is 17.
    """
    levels = (
        level(9.5, SUPPORT),
        level(15.5, RESISTANCE),
        level(18.5, RESISTANCE),
    )
    target = discounted_target(levels, median=14.0, close=9.0, direction=POSITIVE_CALL)

    assert target.price == pytest.approx(17.0)
    assert target.method == DISCOUNTED
    assert target.upside_pct(9.0) == pytest.approx((17.0 - 9.0) / 9.0 * 100.0)


def test_no_target_without_a_researched_growth_direction():
    """The refusal that matters most. Page 233 calls direction the key step."""
    levels = (level(15.5, RESISTANCE), level(18.5, RESISTANCE))

    for direction in (GrowthDirection(), GrowthDirection(NEGATIVE)):
        target = discounted_target(levels, median=14.0, close=9.0, direction=direction)
        assert target.price is None
        assert any("not placed" in b for b in target.basis)


def test_discounted_target_needs_two_resistances_above_the_median():
    levels = (level(15.5, RESISTANCE),)
    target = discounted_target(levels, median=14.0, close=9.0, direction=POSITIVE_CALL)

    assert target.price is None
    assert "found 1" in target.basis[0]


def test_resistance_below_the_median_does_not_count():
    """Page 224's construction is about levels price ran to FROM the median."""
    levels = (level(12.0, RESISTANCE), level(15.5, RESISTANCE), level(18.5, RESISTANCE))
    target = discounted_target(levels, median=14.0, close=9.0, direction=POSITIVE_CALL)

    assert target.price == pytest.approx(17.0), "the 12.0 level must be ignored"


# --- The momentum target, and the course's JMIA numbers --------------------------


def test_jmia_worked_example_from_pages_231_to_232():
    """Average run-up 18, price 38.13: one iteration ≈ 55, three ≈ 90.

    Built as three clean 18-dollar legs so the average is exactly 18, which is
    the number the course's text quotes. The individual magnitudes behind it did
    not survive OCR, so only the average and the two results are checkable.
    """
    closes: list[float] = []
    for _ in range(3):
        closes += list(np.linspace(20.13, 38.13, 30))
        closes += list(np.linspace(38.13, 20.13, 30))
    closes += list(np.linspace(20.13, 38.13, 30))

    df = make_bars(closes)
    cfg = Config(sma_fast=5, sma_slow=10, min_history_days=20, level_swing_lookback=5)

    one = momentum_target(df, cfg, CardConfig(run_up_iterations=1), 38.13, POSITIVE_CALL)
    three = momentum_target(df, cfg, CardConfig(run_up_iterations=3), 38.13, POSITIVE_CALL)

    assert one.price == pytest.approx(55.0, abs=2.5), "one iteration lands near the course's 55"
    assert three.price == pytest.approx(90.0, abs=7.0), "three iterations land near 90"
    assert three.price - 38.13 == pytest.approx(3 * (one.price - 38.13))


def test_momentum_target_also_refuses_without_a_direction():
    df = make_bars(list(np.linspace(20, 38, 120)))
    cfg = Config(sma_fast=5, sma_slow=10, min_history_days=20)

    target = momentum_target(df, cfg, CardConfig(), 38.0, GrowthDirection())
    assert target.price is None


def test_iterations_default_to_one_so_bullishness_is_never_inherited():
    assert CardConfig().run_up_iterations == 1.0


# --- Risk, reward and the stop ---------------------------------------------------


def test_reward_risk_is_target_over_support_per_page_242():
    """Page 242's own numbers: entry 1, support 0.50, target 10 → 9 up, 0.50 down."""
    assert reward_risk(1.0, 10.0, 0.5) == pytest.approx(18.0)
    assert reward_risk(7.0, 10.0, 0.5) == pytest.approx(3.0 / 6.5)


def test_reward_risk_is_none_rather_than_infinite_when_a_leg_is_missing():
    assert reward_risk(10.0, None, 5.0) is None
    assert reward_risk(10.0, 20.0, None) is None
    assert reward_risk(10.0, 20.0, 10.0) is None, "zero downside is not an infinite ratio"


def test_hard_stop_takes_the_nearest_support_below():
    levels = (level(80.0, SUPPORT), level(90.0, SUPPORT), level(120.0, RESISTANCE))
    stop, basis = hard_stop(levels, close=100.0, card=CardConfig())

    assert stop == pytest.approx(90.0)
    assert "234" in basis[0]


def test_two_supports_below_when_highly_bullish_per_page_235():
    levels = (level(80.0, SUPPORT), level(90.0, SUPPORT))
    stop, _ = hard_stop(levels, 100.0, CardConfig(stop_two_supports_below=True))
    assert stop == pytest.approx(80.0)


def test_wanting_two_supports_but_having_one_says_so():
    levels = (level(90.0, SUPPORT),)
    stop, basis = hard_stop(levels, 100.0, CardConfig(stop_two_supports_below=True))

    assert stop == pytest.approx(90.0)
    assert "could not go two down" in basis[0]


# --- Sizing ----------------------------------------------------------------------


def test_position_cap_is_twenty_percent_per_page_40():
    plan = position_plan(close=50.0, stop=45.0, card=CardConfig(account_size=10_000))

    assert plan.max_position_value == pytest.approx(2_000.0)
    assert plan.shares_at_cap == 40
    assert plan.risk_per_share == pytest.approx(5.0)
    assert plan.max_loss_at_cap == pytest.approx(200.0)


def test_no_account_size_means_no_invented_sizing():
    plan = position_plan(50.0, 45.0, CardConfig())
    assert plan.shares_at_cap is None
    assert "set account_size" in plan.note


# --- The whole card --------------------------------------------------------------


def from_pivots(pivots: list[float], span: int = 12) -> list[float]:
    """Interpolate between turning points, so the frame has levels ON PURPOSE.

    An earlier version of these fixtures used a sine wave over a rising base,
    which looks like a chart with levels and has none: every peak prints at a
    different price, so nothing ever clusters to three touches. Every card test
    built on it passed while asserting on `None`, including the one guarding
    the stop-on-support warning, the single most important behaviour in the
    module was covered by a test that could not fail. Naming the pivots means
    the levels are known before the assertions are written.
    """
    out: list[float] = []
    for start, end in zip(pivots, pivots[1:]):  # noqa: B905, lengths differ by one, by design
        out += list(np.linspace(start, end, span, endpoint=False))
    out.append(pivots[-1])
    return out


@pytest.fixture
def trending_frame() -> pd.DataFrame:
    """A range-bound year: lows near 100, resistance near 142 and 161, closing 112.

    Chosen so the discounted branch is the live one, 112 sits below the 130
    median, and so both resistances above the median exist, which is what the
    page 224 construction needs.
    """
    return make_bars(
        from_pivots([100, 160, 110, 140, 100, 158, 105, 142, 101, 159, 104, 141, 100, 160, 112]),
        volume=3_000_000,
    )


@pytest.fixture
def card_cfg() -> Config:
    return Config(
        sma_fast=9,
        sma_slow=50,
        min_history_days=60,
        avg_volume_window=10,
        level_swing_lookback=4,
        level_lookback_days=252,
        level_tolerance_pct=2.0,
    )


def test_the_fixture_actually_produces_levels(trending_frame, card_cfg):
    """Guards the guard. If this fails, every card test below is meaningless."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)

    assert card.support is not None, "fixture must produce a support below price"
    assert card.resistance is not None, "fixture must produce a resistance above price"
    assert card.target.price is not None, "fixture must produce a placeable target"


def test_card_without_research_carries_the_missing_step_warning(trending_frame, card_cfg):
    card = build_card("TEST", trending_frame, card_cfg)

    assert card.direction.call == UNKNOWN
    assert card.target.price is None
    assert any("most important step" in w for w in card.warnings)


def test_card_never_exposes_a_ledger_total(trending_frame, card_cfg):
    """The ledger is two lists and no arithmetic. Page 131."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)

    assert not hasattr(card, "score")
    assert not hasattr(card, "net_factors")
    for attribute in vars(card):
        assert "total" not in attribute


def test_stop_on_the_ratio_support_raises_the_session_four_warning(trending_frame, card_cfg):
    """The card's one deliberate departure from the course.

    Gate 1 wants a close floor; page 234 wants the stop on it. This project's
    backtest measured that pairing stopping out 77% of trades against a 57%
    control, and it moved the same screen from the 96th percentile to the 10th.
    Whenever the two coincide, the card must say so, unconditionally, with no
    `if` in the assertion, which is how the previous version of this test
    managed to pass without ever checking anything.
    """
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)

    assert card.hard_stop == pytest.approx(card.support)
    assert card.reward_risk is not None
    warning = [w for w in card.warnings if w.startswith("STOP SITS ON")]
    assert len(warning) == 1
    assert "77%" in warning[0] and "Widen the stop or size down" in warning[0]


def test_no_warning_when_the_stop_is_clear_of_the_ratio_support(trending_frame, card_cfg):
    """The mirror case. A warning that fires on every card is wallpaper.

    Dropping the stop two supports below (page 235) separates it from the level
    the ratio was measured against, and the warning must then go quiet.
    """
    df = make_bars(
        # Two distinct support clusters below price: one near 99, one near 80.
        from_pivots([100, 160, 101, 140, 80, 158, 99, 142, 81, 159, 100, 141, 80.5, 160, 112]),
        volume=3_000_000,
    )
    card = build_card(
        "TEST", df, card_cfg, CardConfig(stop_two_supports_below=True), direction=POSITIVE_CALL
    )

    assert card.hard_stop is not None and card.support is not None
    assert card.hard_stop < card.support, "the stop must sit below the ratio's support"
    assert not any(w.startswith("STOP SITS ON") for w in card.warnings)


def test_card_always_names_what_it_cannot_see(trending_frame, card_cfg):
    """Absence of a catalyst from the ledger is not evidence there is no catalyst."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)
    missing = [w for w in card.warnings if "Not represented here" in w]

    assert len(missing) == 1
    for term in ("news catalysts", "insider", "offerings"):
        assert term in missing[0]


def test_entry_plan_always_contains_the_confirmation_trigger(trending_frame, card_cfg):
    """Page 135: the only difference between the good and bad plans is the trigger."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)
    assert "only on a confirmation candle" in card.entry_plan


def test_exit_plan_calls_validation_a_re_weigh_not_a_sell(trending_frame, card_cfg):
    """Page 107 is explicit that validation is not a concrete exit point."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)

    assert "re-weigh" in card.exit_plan
    assert "not an automatic sell" in card.exit_plan


def test_negative_direction_lands_in_the_ledger_as_a_big_factor(trending_frame, card_cfg):
    card = build_card(
        "TEST", trending_frame, card_cfg, direction=GrowthDirection(NEGATIVE, ("guidance cut",))
    )
    negatives = [f for f in card.deprecating if "NEGATIVE" in f.text]

    assert negatives and negatives[0].weight == BIG


def test_volume_spike_in_an_uptrend_is_a_big_factor_per_page_119(trending_frame, card_cfg):
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL, volume_ratio=3.0)
    spikes = [f for f in card.elevating if "volume spike" in f.text]

    assert spikes, "a 3x volume day must appear in the ledger"


# --- Rendering -------------------------------------------------------------------


def test_telegram_card_puts_the_critical_warnings_first(trending_frame, card_cfg):
    card = build_card("TEST", trending_frame, card_cfg)
    text = render_card_telegram(card)

    assert text.startswith("⚠️"), "an unresearched card must lead with the warning"
    assert text.index("⚠️") < text.index("TEST")


def test_telegram_card_stays_under_the_limit(trending_frame, card_cfg):
    cards = [
        build_card(f"TICK{i}", trending_frame, card_cfg, direction=POSITIVE_CALL) for i in range(9)
    ]
    text = render_cards_telegram(cards)

    assert len(text) <= 4096
    assert "and 6 more" in text


def test_empty_card_list_says_so_rather_than_going_silent():
    """The same reasoning as notify.py: silence is indistinguishable from a crash."""
    assert "Nothing passed" in render_cards_telegram([])


def test_markdown_card_follows_the_seven_step_skeleton(trending_frame, card_cfg):
    text = render_card_markdown(
        build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)
    )

    for heading in (
        "## 1. Timeframe",
        "## 2. Risk vs reward",
        "## 3. Elevating and deprecating factors",
        "## 4. Long term",
        "## 5. News catalysts",
        "## 6. Analyst price target",
        "## 7. Is it worth it?",
    ):
        assert heading in text


def test_markdown_card_states_what_it_did_not_fetch(trending_frame, card_cfg):
    text = render_card_markdown(
        build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)
    )

    assert "Not fetched" in text
    assert "cannot answer it" in text


def test_sizing_renders_as_one_sentence_not_two_lines(trending_frame, card_cfg):
    """Regression. `add` writes a LINE, so continuing a sentence with a second
    call put ", risking 9 to the stop." on its own line starting with a comma."""
    card = build_card(
        "TEST", trending_frame, card_cfg, CardConfig(account_size=10_000), POSITIVE_CALL
    )
    text = render_card_markdown(card)
    sizing = [ln for ln in text.splitlines() if ln.startswith("**Sizing.**")]

    assert len(sizing) == 1
    assert "risking" in sizing[0], "the risk figure must stay on the sizing line"
    assert not any(ln.startswith(", risking") for ln in text.splitlines())


def test_entry_plan_leads_with_the_biggest_factor_not_the_first(trending_frame, card_cfg):
    """Regression. Taking `elevating[0]` headlined "okay deal" on a card whose
    strongest point was a researched positive growth direction."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)
    big = [f for f in card.elevating if f.weight == BIG]

    assert big, "fixture must produce at least one big elevating factor"
    lead = big[0].text.split(":")[0]
    assert card.entry_plan.startswith(f"I am noticing {lead}")


def test_entry_plan_names_big_deprecating_factors(trending_frame, card_cfg):
    """Page 133 step 7. A plan that reads as pure enthusiasm while two big
    negatives sit in the ledger misrepresents the card it is summarising."""
    card = build_card("TEST", trending_frame, card_cfg, direction=POSITIVE_CALL)

    if card.big_deprecating:
        assert "Against it:" in card.entry_plan
    else:
        assert "Against it:" not in card.entry_plan


def test_missing_numbers_render_as_n_a_not_as_punctuation(trending_frame, card_cfg):
    """Regression from the em-dash sweep, which turned two placeholders into ", "."""
    card = build_card("TEST", trending_frame, card_cfg)
    text = render_card_telegram(card)

    assert "reward:risk n/a" in text
    assert "reward:risk , " not in text


# --------------------------------------------------------------------------
# Who made the growth direction call, added 2026-08-30
# --------------------------------------------------------------------------


def test_an_unlabelled_direction_is_unattributed_not_human():
    """Absent provenance is not a person. Inferring one from silence is the
    same missing-is-not-zero error this project keeps writing down."""
    d = GrowthDirection(call=POSITIVE, researched_on=date(2026, 8, 30))
    assert d.researched_by == UNATTRIBUTED
    assert not d.is_model_call
    assert "researcher not recorded" in d.describe()


def test_a_model_call_says_so_in_its_own_description():
    d = GrowthDirection(call=POSITIVE, researched_by=MODEL, researched_on=date(2026, 8, 30))
    assert d.is_model_call
    assert "CALLED BY A MODEL" in d.describe()


def test_a_human_call_carries_no_provenance_noise():
    d = GrowthDirection(call=POSITIVE, researched_by=HUMAN, researched_on=date(2026, 8, 30))
    assert d.describe() == "growth direction POSITIVE as of 2026-08-30"


def test_researched_by_is_validated():
    with pytest.raises(ValueError, match="researched_by"):
        GrowthDirection(call=POSITIVE, researched_by="the tea leaves")


def test_a_model_direction_still_places_a_target_but_warns_on_the_card(
    trending_frame, card_cfg
):
    """A warning rather than a refusal.

    Refusing a model-supplied direction would throw away a usable input. What
    the card must not do is let the target look identical either way, because
    the arithmetic downstream is the same and only the warning records that the
    premise was never read by a person.
    """
    model = build_card(
        "TEST",
        trending_frame,
        card_cfg,
        direction=GrowthDirection(
            call=POSITIVE, researched_by=MODEL, researched_on=date.today()
        ),
    )
    human = build_card(
        "TEST",
        trending_frame,
        card_cfg,
        direction=GrowthDirection(
            call=POSITIVE, researched_by=HUMAN, researched_on=date.today()
        ),
    )
    assert model.target.price == human.target.price, "same arithmetic, deliberately"
    assert any("CALLED BY A MODEL" in w for w in model.warnings)
    assert not any("CALLED BY A MODEL" in w for w in human.warnings)
