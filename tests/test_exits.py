"""Tests for sizing and exits.

The ones that matter are the three that encode a decision rather than a
calculation: VALIDATION never sells, a gap fills at the open, and the stop is
assumed to win an ambiguous bar. Each of those is a place where a plausible
alternative implementation would quietly flatter every backtest downstream.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.exits import CLOSED, HOLDING, TRAILING, Position, open_alerts, walk
from stocksignal.position import atr, build_plan, place_stop, size_position


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(open, high, low, close) per bar, on business days."""
    idx = pd.bdate_range("2026-01-01", periods=len(rows))
    return pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1_000_000.0] * len(rows),
        },
        index=idx,
    )


def flat(n: int, price: float = 100.0, wobble: float = 1.0) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = price + np.sin(np.arange(n) / 5) * wobble
    return pd.DataFrame(
        {
            "open": close,
            "high": close + wobble,
            "low": close - wobble,
            "close": close,
            "volume": np.full(n, 1e6),
        },
        index=idx,
    )


# --------------------------------------------------------------------------
# The decisions, not the arithmetic
# --------------------------------------------------------------------------


def test_validation_never_sells():
    """Page 107 says the first candle opening below the 9 SMA is validation, not
    a concrete exit point: the moment to re-weigh the factors and decide. If
    this ever closes a position, the tool has started trading."""
    df = bars([(100, 101, 99, 100)] * 12 + [(80, 82, 79, 81)])
    pos = Position(ticker="T", entry=100.0, stop=50.0)
    walk(df, pos)
    kinds = [e.kind for e in pos.events]
    assert "VALIDATION" in kinds
    assert pos.state != CLOSED
    assert pos.exit_price is None
    assert all(not e.is_instruction for e in pos.events if e.kind == "VALIDATION")


def test_only_the_stop_and_the_trail_are_instructions():
    df = bars([(100, 101, 99, 100), (100, 101, 40, 60)])
    pos = Position(ticker="T", entry=100.0, stop=90.0)
    walk(df, pos)
    instructions = [e for e in pos.events if e.is_instruction]
    assert len(instructions) == 1
    assert instructions[0].kind == "STOP"


def test_a_gap_through_the_stop_fills_at_the_open():
    """A stop at 90 with the bar opening at 70 fills at 70. Assuming 90 would be
    a fill nobody gets, and it is the single easiest way to make a backtest
    flatter itself."""
    df = bars([(70, 72, 68, 71)])
    pos = Position(ticker="T", entry=100.0, stop=90.0)
    walk(df, pos)
    assert pos.exit_reason == "STOP"
    assert pos.exit_price == pytest.approx(70.0)
    assert pos.pnl_pct == pytest.approx(-30.0)


def test_a_normal_stop_hit_fills_at_the_stop():
    df = bars([(95, 96, 89, 91)])
    pos = Position(ticker="T", entry=100.0, stop=90.0)
    walk(df, pos)
    assert pos.exit_price == pytest.approx(90.0)


def test_the_stop_wins_a_bar_that_touches_both():
    """Daily bars cannot say which came first, so the pessimistic reading is
    the honest one. The optimistic version manufactures winners out of
    ambiguity."""
    df = bars([(100, 130, 85, 120)])
    pos = Position(ticker="T", entry=100.0, stop=90.0, target=120.0)
    walk(df, pos)
    assert pos.exit_reason == "STOP"


# --------------------------------------------------------------------------
# The trailing stop, which is post-target only
# --------------------------------------------------------------------------


def test_the_trail_only_starts_after_the_target():
    """Pages 237 to 238: 5%, and only AFTER the target is hit. A trail from
    entry is a different strategy, not a different implementation."""
    df = bars([(100, 104, 99, 103), (103, 106, 102, 105)])
    pos = Position(ticker="T", entry=100.0, stop=90.0, target=120.0)
    walk(df, pos)
    assert pos.state == HOLDING
    assert pos.stop == pytest.approx(90.0)  # untouched, no ratchet before target


def test_hitting_the_target_switches_to_trailing_and_does_not_sell():
    df = bars([(100, 125, 99, 122)])
    pos = Position(ticker="T", entry=100.0, stop=90.0, target=120.0)
    walk(df, pos)
    assert pos.state == TRAILING
    assert pos.is_open
    assert pos.stop == pytest.approx(125.0 * 0.95)


def test_the_trail_ratchets_up_and_never_down():
    df = bars([(100, 125, 99, 122), (122, 140, 121, 138), (138, 139, 130, 132)])
    pos = Position(ticker="T", entry=100.0, stop=90.0, target=120.0)
    walk(df, pos)
    assert pos.peak == pytest.approx(140.0)
    assert pos.stop == pytest.approx(140.0 * 0.95)


def test_the_trail_eventually_closes_the_position():
    df = bars([(100, 125, 99, 122), (122, 126, 100, 105)])
    pos = Position(ticker="T", entry=100.0, stop=90.0, target=120.0)
    walk(df, pos)
    assert pos.state == CLOSED
    assert pos.exit_reason == "STOP"
    assert pos.pnl_pct > 0  # the trail protected the gain


def test_open_alerts_reads_only_the_newest_bar():
    """The daily job: tell the bot what you hold, it reads today and reports."""
    df = bars([(100, 101, 99, 100)] * 12 + [(80, 82, 79, 81)])
    pos = Position(ticker="T", entry=100.0, stop=50.0)
    events = open_alerts(df, pos)
    assert [e.kind for e in events] == ["VALIDATION"]


# --------------------------------------------------------------------------
# Stops
# --------------------------------------------------------------------------


def test_the_atr_stop_sits_outside_one_average_range():
    df = flat(60, 100.0, wobble=2.0)
    value = atr(df, DEFAULT_CONFIG.atr_period)
    stop, basis, _ = place_stop(df, 100.0, DEFAULT_CONFIG)
    assert basis == "atr"
    assert 100.0 - stop > value


def test_the_support_stop_abstains_without_a_level():
    """92% of setups in this project have no three-touch level below. Abstaining
    is correct there; inventing a level is not."""
    stop, basis, reasons = place_stop(flat(60), 100.0, Config(stop_rule="support"))
    assert stop is None
    assert "no three-touch support" in reasons[0]


def test_the_atr_stop_says_when_it_is_tighter_than_the_rulebooks():
    df = flat(60, 100.0, wobble=0.2)
    _, _, reasons = place_stop(df, 100.0, DEFAULT_CONFIG, support=80.0)
    assert any("ABOVE the three-touch support" in r for r in reasons)


def test_stop_rules_read_config_not_hard_coded_numbers():
    df = flat(60, 100.0, wobble=2.0)
    tight, _, _ = place_stop(df, 100.0, Config(atr_stop_multiple=0.5))
    wide, _, _ = place_stop(df, 100.0, Config(atr_stop_multiple=8.0))
    assert wide < tight


# --------------------------------------------------------------------------
# Sizing: two ceilings, the smaller binds
# --------------------------------------------------------------------------


def test_a_tight_stop_is_bound_by_the_concentration_cap():
    """20% of 10,000 is 2,000, so 20 shares at 100. The 1% risk budget over a
    1.00 stop would allow 100, so the cap is what stops you."""
    shares, binding, _ = size_position(100.0, 99.0, 10_000.0)
    assert shares == 20
    assert binding == "concentration"


def test_a_wide_stop_is_bound_by_the_risk_budget():
    """A 50-point stop against a 100 risk budget allows 2 shares, far under the
    20 the cap would permit. This is the case the course's 20% rule alone
    cannot see, because it says nothing about risk."""
    shares, binding, _ = size_position(100.0, 50.0, 10_000.0)
    assert shares == 2
    assert binding == "risk"


def test_shares_are_floored_never_rounded_up():
    """Rounding up quietly breaches whichever limit was binding."""
    shares, _, _ = size_position(30.0, 29.0, 10_000.0)
    assert shares == 66  # 2000 / 30 = 66.67


def test_no_stop_falls_back_to_the_cap_and_says_so():
    shares, binding, reasons = size_position(100.0, None, 10_000.0)
    assert shares == 20
    assert binding == "concentration"
    assert "Size this by hand" in reasons[0]


def test_a_stop_at_or_above_entry_is_not_treated_as_a_stop():
    shares, binding, _ = size_position(100.0, 100.0, 10_000.0)
    assert binding == "concentration"


# --------------------------------------------------------------------------
# The warning that carries this project's own measured finding
# --------------------------------------------------------------------------


def test_a_stop_on_the_ratio_support_is_flagged():
    """The 77% shakeout, surfaced at the point of use rather than in a document
    nobody rereads."""
    plan = build_plan("T", flat(60), 100.0, 10_000.0, Config(stop_rule="support"), support=99.9)
    assert any("EARNED THE RATIO" in w for w in plan.warnings)


def test_a_stop_inside_one_atr_is_flagged():
    plan = build_plan(
        "T",
        flat(60, 100.0, wobble=3.0),
        100.0,
        10_000.0,
        Config(stop_rule="percent", stop_percent=0.5),
    )
    assert any("inside the noise" in w for w in plan.warnings)


def test_a_plan_reports_reward_risk_and_account_share():
    plan = build_plan("T", flat(60), 100.0, 10_000.0, Config(stop_rule="percent"), target=120.0)
    assert plan.reward_risk == pytest.approx(20.0 / 8.0, rel=1e-3)
    assert 0 < plan.account_pct <= 20.0
