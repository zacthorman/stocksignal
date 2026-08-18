"""Tests for the Growth Template valuation chain.

The template has no worked example anywhere, not in the spreadsheet, not in the
course, so there is no published number to reproduce. Every test here is
therefore either arithmetic checked by hand against the cell formulas, or a
guard on one of the model's failure modes.

The failure modes are the important half. This model multiplies a growth rate by
up to 1.5 or down to 0.25 on the strength of judgement calls with no rubric, and
then divides by 0.035, which turns a 40% growth rate into a 17x sales multiple.
Small input errors do not stay small. Every guard below exists because the
template itself would print the wrong answer without complaint.
"""

from __future__ import annotations

import pytest

from stocksignal.growth_template import (
    CATEGORIES,
    MATURITY_MAX,
    SP500_GROWTH,
    SP500_MULTIPLE,
    Scorecard,
    ScoreLine,
    TemplateError,
    fair_multiple,
    render_valuation,
    value,
    yoy_growth,
)


def full_card(
    points_each: float = 15.0, maturity: float = 0.0, reasoning: str = "checked"
) -> Scorecard:
    """A scorecard with every category filled, capped at each category's max."""
    lines = {
        key: ScoreLine(min(points_each, maximum), maximum, reasoning)
        for key, _, maximum in CATEGORIES
    }
    return Scorecard(lines, ScoreLine(maturity, MATURITY_MAX, reasoning))


def mid_card() -> Scorecard:
    """A scorecard landing in the 160-169 band, where the adjustment is exactly 0%.

    Chosen so the band contributes nothing and the tests below measure the
    arithmetic rather than the band lookup. 17 points where the cap allows it
    totals 165.
    """
    return Scorecard(
        {key: ScoreLine(min(17, maximum), maximum, "mid") for key, _, maximum in CATEGORIES}
    )


# --- The arithmetic --------------------------------------------------------------


def test_yoy_growth_matches_the_cell_formula():
    """`=(B4-B3)/B3`. Four revenues give three growth rates."""
    assert yoy_growth([100.0, 110.0, 121.0]) == pytest.approx((0.10, 0.10))


def test_growth_from_a_zero_base_year_raises_rather_than_dividing():
    with pytest.raises(TemplateError, match="zero base year"):
        yoy_growth([0.0, 100.0])


def test_the_eleven_positive_categories_sum_to_exactly_200():
    """The template shows /200 and the eleven caps must actually reach it."""
    assert sum(maximum for _, _, maximum in CATEGORIES) == 200


def test_maturity_subtracts_rather_than_adds():
    """`=SUM(B3:B13)-B14`, the real range is -25 to 200, not 0 to 200."""
    with_penalty = full_card(15.0, maturity=25.0)
    without = full_card(15.0, maturity=0.0)

    assert with_penalty.total == without.total - 25


def test_fair_multiple_matches_the_calculation_center():
    """`=(B9/B10)*B11`. Growing at exactly the index average earns exactly 1.5x."""
    assert fair_multiple(SP500_GROWTH) == pytest.approx(SP500_MULTIPLE)
    assert fair_multiple(0.35) == pytest.approx(15.0)


def test_band_adjustment_is_relative_not_absolute():
    """ "+50%" multiplies the growth rate by 1.5. It does not add 50 points.

    Cell B6 is `=B4+(B4*B5)`, which is the whole argument.
    """
    top = Scorecard({k: ScoreLine(m, m, "max") for k, _, m in CATEGORIES})
    assert top.total == 200
    assert top.band()[0] == 0.50

    result = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], top)
    assert result.average_growth == pytest.approx(0.20)
    assert result.anticipated_growth == pytest.approx(0.30), "0.20 * 1.5, not 0.20 + 0.50"


def test_price_target_is_revenue_per_share_times_the_multiple():
    """`=(B8/D8)*E8`, checked by hand.

    Revenue 100 → 120 is 20% growth. A 160-169 band adds nothing, so anticipated
    stays 20%, the multiple is (0.20/0.035)*1.5 = 8.571x, next year's revenue is
    144, and with 10 shares that is 14.4 per share → 123.43.
    """
    card = mid_card()
    assert 160 <= card.total <= 169

    result = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card)

    assert result.fair_multiple == pytest.approx(0.20 / 0.035 * 1.5)
    year, revenue, _, target = result.projections[0]
    assert year == 2024
    assert revenue == pytest.approx(144.0)
    assert target == pytest.approx(144.0 / 10.0 * result.fair_multiple)


# --- The refusals ----------------------------------------------------------------


def test_below_120_refuses_rather_than_inventing_an_earnings_model():
    """The template forks to a model that neither it nor the course supplies."""
    card = full_card(points_each=5.0)
    assert card.total < 120

    with pytest.raises(TemplateError, match="earnings model"):
        card.band()


def test_shrinking_company_refuses_rather_than_printing_a_negative_target():
    """The spreadsheet would happily produce a negative multiple and a negative price."""
    card = mid_card()

    with pytest.raises(TemplateError, match="shrinking company"):
        value("T", [2022, 2023], [120.0, 100.0], [10.0, 10.0], card)


def test_zero_or_negative_share_count_refuses():
    card = mid_card()

    with pytest.raises(TemplateError, match="positive"):
        value("T", [2022, 2023], [100.0, 120.0], [10.0, 0.0], card)


def test_mismatched_input_lengths_refuse():
    card = mid_card()

    with pytest.raises(TemplateError, match="same length"):
        value("T", [2022, 2023], [100.0, 120.0], [10.0], card)


def test_points_above_the_category_cap_refuse():
    with pytest.raises(TemplateError, match="outside 0 to 10"):
        ScoreLine(11, 10, "too many")


# --- The warnings ----------------------------------------------------------------


def test_runaway_multiple_is_flagged_but_never_clamped():
    """The model's central weakness must stay visible in the output.

    Growing at 70% earns a 30x price-to-sales under this formula. Real markets
    do not sustain that. Clamping it quietly would hide the flaw behind a
    plausible-looking number, so the number stands and the warning goes next
    to it.
    """
    card = mid_card()
    result = value("T", [2022, 2023], [100.0, 170.0], [10.0, 10.0], card)

    assert result.fair_multiple == pytest.approx(0.70 / 0.035 * 1.5)
    assert result.fair_multiple > 25
    assert any("beyond anything markets sustain" in w for w in result.warnings)
    assert result.near_target is not None, "the number is reported, not suppressed"


def test_flat_share_count_warns_about_dilution():
    """The column header says "Include Dilution" and these are high-beta names."""
    card = mid_card()
    result = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card)

    assert any("dilution is modelled as zero" in w for w in result.warnings)


def test_dilution_lowers_the_target():
    card = mid_card()
    flat = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card)
    diluted = value("T", [2022, 2023], [100.0, 120.0], [10.0, 12.0], card)

    assert diluted.near_target < flat.near_target


def test_short_history_is_warned_about():
    card = mid_card()
    result = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card)

    assert any("the template averages 4" in w for w in result.warnings)


def test_unexplained_points_are_named():
    """Nine categories have no rubric, so the reasoning IS the method."""
    lines = {k: ScoreLine(min(15, m), m, "") for k, _, m in CATEGORIES}
    card = Scorecard(lines)

    assert set(card.unexplained) == {k for k, _, _ in CATEGORIES}

    result = value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card)
    assert any("no reasoning recorded" in w for w in result.warnings)


def test_missing_categories_are_named_rather_than_silently_zero():
    card = Scorecard({"company_health": ScoreLine(25, 25, "5 years of cash")})

    assert "scalability" in card.missing
    with pytest.raises(TemplateError):
        card.band()  # 25 is below 120, so it correctly refuses


# --- Rendering -------------------------------------------------------------------


def test_render_leads_with_the_not_a_course_method_caveat():
    card = mid_card()
    text = render_valuation(
        value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card), close=10.0
    )

    assert "Not a course method" in text.split("## The chain")[0]
    assert "second" in text and "opinion" in text


def test_render_shows_every_intermediate():
    card = mid_card()
    text = render_valuation(value("T", [2022, 2023], [100.0, 120.0], [10.0, 10.0], card))

    for fragment in (
        "Historical YoY growth",
        "Average",
        "Scorecard",
        "Anticipated growth",
        "Fair multiple",
    ):
        assert fragment in text
