"""Tests for the balance sheet reading.

The ones that matter are the two the real data forced: negative NTAV means
different things for an acquirer than for a company capitalising its own costs,
and a missing line is not a pass.
"""

from __future__ import annotations

import pytest

from stocksignal.balance import CRITICAL, SERIOUS, BalanceSheet, to_dict


def sheet(**kw) -> BalanceSheet:
    base = dict(
        ticker="T",
        assets=100e6,
        assets_current=60e6,
        liabilities=40e6,
        liabilities_current=30e6,
        equity=60e6,
        cash=20e6,
        revenue=50e6,
    )
    base.update(kw)
    return BalanceSheet(**base)


def flags_of(b: BalanceSheet, check: str):
    return [f for f in b.flags if f.check == check]


# --------------------------------------------------------------------------
# Michael's four spot checks
# --------------------------------------------------------------------------


def test_current_ratio_below_one_is_flagged():
    """His only stated threshold: below 1.0 the company may struggle to meet
    its short-term commitments."""
    b = sheet(assets_current=20e6, liabilities_current=30e6)
    assert b.current_ratio == pytest.approx(0.667, rel=1e-2)
    assert b.net_current_assets == pytest.approx(-10e6)
    assert flags_of(b, "current ratio")[0].severity == SERIOUS


def test_a_healthy_current_ratio_raises_nothing():
    assert not flags_of(sheet(), "current ratio")


def test_ntav_strips_intangibles_from_nav():
    """The mining example: NAV said 30m, the market said 3m, and the gap was
    30m of capitalised drilling booked as an asset."""
    b = sheet(assets=32e6, liabilities=2e6, equity=30e6, intangibles=29e6)
    assert b.nav == pytest.approx(30e6)
    assert b.ntav == pytest.approx(1e6)


def test_nav_falls_back_to_reported_equity():
    """Small caps sometimes tag equity and not the totals. The accounting
    equation makes the two the same thing, so the fallback is exact."""
    b = BalanceSheet("T", equity=42e6)
    assert b.nav == pytest.approx(42e6)


def test_debt_free_is_reported_as_a_state():
    assert sheet(debt_long=0.0).debt_free is True
    assert sheet(debt_long=5e6).debt_free is False
    assert sheet().debt_free is None  # not reported, which is not the same as zero


def test_net_debt_is_negative_when_the_company_holds_net_cash():
    assert sheet(debt_long=5e6, cash=20e6).net_debt == pytest.approx(-15e6)


def test_receivables_outrunning_payables_is_check_four():
    """His check 4 exactly: receivables growing faster than payables means cash
    is leaving the business faster than it comes in."""
    b = sheet(receivables=200e6, prev_receivables=100e6, payables=110e6, prev_payables=100e6)
    assert b.receivable_growth == pytest.approx(100.0)
    assert b.payable_growth == pytest.approx(10.0)
    assert b.receivable_gap == pytest.approx(90.0)
    assert flags_of(b, "receivables vs payables")[0].severity == SERIOUS


def test_receivables_outrunning_revenue_is_the_sharper_tell():
    """Revenue can be booked without the cash arriving. If receivables grow
    faster than the sales that created them, the gap is uncollected."""
    b = sheet(receivables=200e6, prev_receivables=100e6, revenue=110e6, prev_revenue=100e6)
    assert b.receivables_outrunning_revenue == pytest.approx(90.0)
    assert flags_of(b, "receivables vs revenue")


def test_receivables_growing_in_line_with_revenue_raises_nothing():
    b = sheet(
        receivables=110e6,
        prev_receivables=100e6,
        revenue=110e6,
        prev_revenue=100e6,
        payables=110e6,
        prev_payables=100e6,
    )
    assert not flags_of(b, "receivables vs revenue")
    assert not flags_of(b, "receivables vs payables")


def test_receivable_days_measures_the_collection_lag():
    b = sheet(receivables=25e6, revenue=100e6)
    assert b.receivable_days == pytest.approx(91.25)


# --------------------------------------------------------------------------
# The distinction the real data forced
# --------------------------------------------------------------------------


def test_negative_ntav_from_acquisition_goodwill_is_serious_not_critical():
    """Tempus carries 825m of goodwill and intangibles from buying Ambry and
    Paige. Goodwill only arises on acquisition, so it is a business someone paid
    cash for, and negative NTAV is the ordinary arithmetic of an acquirer. The
    first version returned AVOID here, which was the rule misfiring."""
    b = sheet(
        assets=2274.8e6, liabilities=1783.5e6, equity=491.3e6, goodwill=470.2e6, intangibles=355.3e6
    )
    assert b.ntav < 0
    ntav_flags = flags_of(b, "negative NTAV")
    assert ntav_flags and ntav_flags[0].severity == SERIOUS
    assert "GOODWILL" in ntav_flags[0].message
    assert b.verdict != "AVOID"


def test_negative_ntav_from_self_generated_intangibles_stays_critical():
    """No goodwill, so the intangibles were created rather than bought. This is
    the mining-company trap and it keeps the harsher reading."""
    b = sheet(assets=100e6, liabilities=60e6, equity=40e6, intangibles=55e6, goodwill=2e6)
    ntav_flags = flags_of(b, "negative NTAV")
    assert ntav_flags and ntav_flags[0].severity == CRITICAL
    assert b.verdict == "AVOID"


def test_intangibles_growing_without_revenue_prompts_a_look():
    b = sheet(intangibles=30e6, prev_intangibles=10e6, revenue=105e6, prev_revenue=100e6)
    assert flags_of(b, "capitalised costs")


# --------------------------------------------------------------------------
# Missing is not zero, and not a pass
# --------------------------------------------------------------------------


def test_an_unreadable_balance_sheet_is_unknown_not_solid():
    """A company that does not report the split has not passed the current
    ratio test, it has declined to answer it."""
    b = BalanceSheet("T")
    assert b.current_ratio is None
    assert b.verdict == "UNKNOWN"


def test_a_clean_sheet_with_every_line_present_reads_solid():
    b = sheet(
        receivables=110e6,
        prev_receivables=100e6,
        payables=105e6,
        prev_payables=100e6,
        prev_revenue=45e6,
        debt_long=0.0,
    )
    assert not b.flags
    assert b.verdict == "SOLID"


def test_the_four_notes_answer_in_his_order():
    b = sheet(receivables=110e6, prev_receivables=100e6, debt_long=0.0)
    notes = b.notes
    assert len(notes) == 4
    assert notes[0].startswith("1.") and "Cash" in notes[0]
    assert notes[1].startswith("2.") and "current" in notes[1]
    assert notes[2].startswith("3.") and "debt" in notes[2].lower()
    assert notes[3].startswith("4.") and "Receivables" in notes[3]


def test_to_dict_round_trips_and_carries_the_flags():
    d = to_dict(sheet(assets_current=10e6, liabilities_current=30e6))
    assert d["verdict"] in {"SOLID", "WATCH", "CONCERN", "AVOID", "UNKNOWN"}
    assert d["current_ratio"] == pytest.approx(0.33, abs=0.01)
    assert any(f["check"] == "current ratio" for f in d["flags"])
    assert len(d["notes"]) == 4


# --------------------------------------------------------------------------
# Coverage, added because SEZL earned SOLID with a check it never ran
# --------------------------------------------------------------------------


def test_a_sheet_that_answers_almost_nothing_is_unknown_not_solid():
    """No flag can fire without a number, so a silent company collects none and
    would otherwise take the best verdict on the board. Silence is not a pass."""
    b = sheet(assets=100e6, liabilities=40e6, equity=60e6, cash=None, revenue=None)
    assert sum(b.coverage) < 3
    assert b.verdict == "UNKNOWN"


def test_three_of_four_checks_answered_still_earns_a_verdict():
    """Sezzle files no trade receivable line, so check 4 cannot run, but cash,
    tangibility and debt all answer. Abstaining on one check should be visible,
    not disqualifying."""
    b = sheet(
        assets=400.2e6,
        assets_current=351.9e6,
        liabilities=230.4e6,
        liabilities_current=89.8e6,
        equity=169.8e6,
        cash=64.1e6,
        intangibles=3.3e6,
        goodwill=None,
        debt_long=140.0e6,
        receivables=None,
        prev_receivables=None,
        revenue=235.9e6,
        prev_revenue=139.4e6,
    )
    assert b.coverage == (True, True, True, False)
    assert b.verdict == "SOLID"


def test_an_unreported_receivable_line_says_so_rather_than_blaming_the_prior_year():
    b = sheet(receivables=None, prev_receivables=None)
    note = [n for n in b.notes if n.startswith("4.")][0]
    assert "no trade receivable line is reported" in note
    assert "prior-year" not in note
