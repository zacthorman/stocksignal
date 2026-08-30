"""Tests for the cash reading.

The important ones are the three-way distinction the module exists to protect:
"generates cash" and "burns cash but has years of it" and "we could not look"
are three different answers, and every one of them has to survive the round
trip through `to_dict`.
"""

from __future__ import annotations

import math

import pytest

from stocksignal.cashflow import CashReading, to_dict


def test_self_funding_is_infinite_runway_not_unknown():
    """A company that funds itself has no burn to survive, which is not the same
    as having an unknown runway. Collapsing the two would let a profitable
    business and an unreadable one share a verdict."""
    r = CashReading("T", operating_cash_flow=90e6, free_cash_flow=40e6, cash_and_equivalents=10e6)
    assert r.runway_years == math.inf
    assert r.verdict == "SELF-FUNDING"
    assert r.company_health_points == 25
    d = to_dict(r)
    assert d["self_funding"] is True
    assert d["runway_years"] is None  # inf does not survive JSON, the flag carries it


def test_missing_data_is_unknown_and_never_zero():
    r = CashReading("T")
    assert r.runway_years is None
    assert r.company_health_points is None
    assert r.verdict == "UNKNOWN"
    assert r.generates_cash is None
    assert "not available" in r.notes[0]


def test_runway_is_cash_over_burn():
    r = CashReading(
        "T", operating_cash_flow=-30e6, free_cash_flow=-50e6, cash_and_equivalents=150e6
    )
    assert r.runway_years == pytest.approx(3.0)
    assert r.verdict == "FUNDED"


@pytest.mark.parametrize(
    ("cash", "fcf", "expected"),
    [
        (500e6, -100e6, 25),  # 5 years
        (300e6, -100e6, 20),  # 3 years
        (200e6, -100e6, 15),  # 2 years
        (100e6, -100e6, 10),  # 1 year
        (50e6, -100e6, 0),  # half a year, under the template's lowest rung
    ],
)
def test_company_health_follows_the_templates_own_rule(cash, fcf, expected):
    """1yr = 10, 2yr = 15, 3yr = 20, 5yr = 25, verbatim from the sheet.

    This is the only one of the twelve growth-template categories that can be
    computed, and the reason it is legitimate to compute it is that the template
    states the rule. The other ten are left alone.
    """
    r = CashReading("T", free_cash_flow=fcf, cash_and_equivalents=cash)
    assert r.company_health_points == expected


def test_verdict_thresholds():
    def v(cash, fcf):
        return CashReading("T", free_cash_flow=fcf, cash_and_equivalents=cash).verdict

    assert v(400e6, -100e6) == "FUNDED"
    assert v(150e6, -100e6) == "TIGHT"
    assert v(50e6, -100e6) == "BURNING"


def test_cash_conversion_is_undefined_against_a_loss():
    """A ratio against negative net income is not interpretable, and returning a
    number there would be worse than returning nothing."""
    loss = CashReading("T", operating_cash_flow=10e6, net_income=-5e6)
    assert loss.cash_conversion is None
    assert "does not apply" in " ".join(loss.notes)

    profit = CashReading("T", operating_cash_flow=10e6, net_income=8e6)
    assert profit.cash_conversion == pytest.approx(1.25)


def test_weak_conversion_says_so_plainly():
    r = CashReading("T", operating_cash_flow=3e6, net_income=10e6)
    assert r.cash_conversion == pytest.approx(0.3)
    assert "running well ahead of the cash" in " ".join(r.notes)


def test_ocf_trend_needs_three_readings():
    assert CashReading("T", ocf_history=(1.0, 2.0)).ocf_trend is None
    assert CashReading("T", ocf_history=(1.0, 2.0, 3.0, 4.0)).ocf_trend == "improving"
    assert CashReading("T", ocf_history=(4.0, 3.0, 2.0, 1.0)).ocf_trend == "deteriorating"
    # A spike then a collapse is not improving, even though the ends point up
    # and only one step falls. This is the case the first version got wrong.
    assert CashReading("T", ocf_history=(1.0, 9.0, 2.0, 3.0)).ocf_trend == "erratic"
    assert CashReading("T", ocf_history=(1.0, 3.0, 2.0, 4.0)).ocf_trend == "erratic"


def test_net_cash_is_cash_minus_debt():
    def net(cash, debt=None):
        return CashReading("T", cash_and_equivalents=cash, total_debt=debt).net_cash

    assert net(10e6, 4e6) == pytest.approx(6e6)
    assert net(1e6, 9e6) == pytest.approx(-8e6)
    assert net(1e6) is None


def test_notes_read_the_statements_in_michaels_order():
    """Cash flow, then balance sheet, then income statement. The order is the
    argument, so it is worth a test rather than a comment."""
    r = CashReading(
        "T",
        operating_cash_flow=-20e6,
        free_cash_flow=-40e6,
        cash_and_equivalents=120e6,
        total_debt=10e6,
        net_income=-25e6,
        ocf_history=(-50e6, -35e6, -20e6),
    )
    joined = r.notes
    assert joined[0].startswith("Cash flow statement")
    balance = next(i for i, n in enumerate(joined) if n.startswith("Balance sheet"))
    income = next(i for i, n in enumerate(joined) if n.startswith("Income statement"))
    assert 0 < balance < income


def test_to_dict_round_trips_every_state():
    for r in (
        CashReading("A"),
        CashReading("B", free_cash_flow=5e6, cash_and_equivalents=1e6),
        CashReading("C", free_cash_flow=-5e6, cash_and_equivalents=10e6),
    ):
        d = to_dict(r)
        assert d["ticker"] == r.ticker
        assert d["verdict"] == r.verdict
        assert isinstance(d["notes"], list) and d["notes"]
