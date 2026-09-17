"""Tests for what the scan remembers between runs.

The complaint these answer, from the 31 August freeze review: TXG, SSRM and CHYM
passed on all eleven days of the freeze and the digest had no way to say so.
"""

from __future__ import annotations

import json
from datetime import date

from stocksignal.digest import render_markdown
from stocksignal.memory import (
    DEFAULT_DISMISSAL_DAYS,
    Dismissal,
    ScanMemory,
    ordinal,
    run_lengths,
)
from stocksignal.models import Signal
from stocksignal.scanner import ScanReport
from stocksignal.signal_log import write_ledger

TODAY = date(2026, 8, 31)


def sig(ticker: str, as_of: date = TODAY) -> Signal:
    return Signal(ticker=ticker, as_of=as_of, close=100.0, score=1.0)


def ledger(tmp_path, day: str, tickers: list[str]):
    write_ledger([sig(t, date.fromisoformat(day)) for t in tickers], tmp_path)


def report(*tickers) -> ScanReport:
    return ScanReport(as_of=TODAY, signals=tuple(sig(t) for t in tickers), rejected=(), errors=())


# --------------------------------------------------------------------------
# Recurrence is a fact, counted from the committed ledger
# --------------------------------------------------------------------------


def test_a_name_never_seen_before_is_new(tmp_path):
    ledger(tmp_path, "2026-08-28", ["SSRM"])
    r = run_lengths({"TXG"}, TODAY, tmp_path)["TXG"]
    assert r.is_new
    assert r.describe() == "new today"


def test_a_run_counts_consecutive_scans_not_calendar_days(tmp_path):
    """Friday then Monday is a run of two. Counting calendar days would break
    every run over every weekend and report the whole board as new on Mondays."""
    ledger(tmp_path, "2026-08-27", ["TXG"])
    ledger(tmp_path, "2026-08-28", ["TXG"])
    r = run_lengths({"TXG"}, TODAY, tmp_path)["TXG"]
    assert r.run_length == 3
    assert r.first_seen == date(2026, 8, 27)
    assert not r.is_new


def test_a_gap_ends_the_run(tmp_path):
    ledger(tmp_path, "2026-08-26", ["TXG"])
    ledger(tmp_path, "2026-08-27", ["SSRM"])
    ledger(tmp_path, "2026-08-28", ["TXG"])
    assert run_lengths({"TXG"}, TODAY, tmp_path)["TXG"].run_length == 2


def test_todays_own_ledger_is_ignored(tmp_path):
    """Otherwise a rerun would count the name against itself and nothing would
    ever read as new again."""
    ledger(tmp_path, "2026-08-31", ["TXG"])
    assert run_lengths({"TXG"}, TODAY, tmp_path)["TXG"].is_new


def test_no_ledger_at_all_makes_everything_new(tmp_path):
    assert run_lengths({"TXG", "SSRM"}, TODAY, tmp_path)["SSRM"].is_new


# --------------------------------------------------------------------------
# Dismissal is a decision, and it expires
# --------------------------------------------------------------------------


def test_a_dismissal_expires_and_says_when():
    d = Dismissal("TXG", on=date(2026, 8, 1), reason="no setup", days=30)
    assert d.expires_on == date(2026, 8, 31)
    assert d.active_on(date(2026, 8, 30))
    assert not d.active_on(date(2026, 8, 31)), "a stale no must not shrink the universe"
    assert "no setup" in d.describe(date(2026, 8, 30))


def test_the_default_is_shorter_than_the_growth_direction_cycle():
    """A chart changes faster than a quarterly report."""
    assert DEFAULT_DISMISSAL_DAYS == 30


def test_an_expired_dismissal_stops_applying(tmp_path):
    (tmp_path / "d.json").write_text(
        json.dumps({"TXG": {"on": "2026-07-01", "reason": "old", "days": 30}})
    )
    m = ScanMemory.build([sig("TXG")], TODAY, tmp_path, tmp_path / "d.json")
    assert not m.is_dismissed("TXG")


def test_a_missing_dismissal_file_is_an_empty_memory_not_an_error(tmp_path):
    m = ScanMemory.build([sig("TXG")], TODAY, tmp_path, tmp_path / "nothing.json")
    assert m.dismissals == {}


# --------------------------------------------------------------------------
# What the digest does with it
# --------------------------------------------------------------------------


def test_new_names_come_first_and_continuing_ones_are_still_there(tmp_path):
    ledger(tmp_path, "2026-08-28", ["TXG"])
    m = ScanMemory.build([sig("TXG"), sig("NVDA")], TODAY, tmp_path, tmp_path / "d.json")
    md = render_markdown(report("TXG", "NVDA"), memory=m)
    assert md.index("## New today") < md.index("## Still passing")
    assert "NVDA" in md and "TXG" in md
    assert "2nd scan running" in md
    assert "2th" not in md


def test_a_dismissed_name_is_moved_and_not_removed(tmp_path):
    (tmp_path / "d.json").write_text(
        json.dumps({"TXG": {"on": "2026-08-30", "reason": "no setup", "days": 30}})
    )
    m = ScanMemory.build([sig("TXG")], TODAY, tmp_path, tmp_path / "d.json")
    md = render_markdown(report("TXG"), memory=m)
    assert "## Dismissed (1)" in md
    assert "TXG" in md, "moved out of the way, never deleted"
    assert "no setup" in md
    assert "Returns in 29 days" in md


def test_a_day_with_nothing_new_says_so_rather_than_showing_an_empty_heading(tmp_path):
    ledger(tmp_path, "2026-08-28", ["TXG"])
    m = ScanMemory.build([sig("TXG")], TODAY, tmp_path, tmp_path / "d.json")
    md = render_markdown(report("TXG"), memory=m)
    assert "## New today (0)" in md
    assert "That is a real result" in md


def test_without_a_memory_the_digest_is_unchanged(tmp_path):
    """The memory is optional, so an offline or one-off run still renders."""
    md = render_markdown(report("TXG", "NVDA"))
    assert "## Candidates" in md
    assert "New today" not in md


def test_ordinals_read_as_english():
    got = [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)]
    assert got == "1st 2nd 3rd 4th 11th 12th 13th 21st 22nd 23rd 101st 111th 112th".split()


def test_run_lengths_match_regardless_of_ticker_case(tmp_path):
    ledger(tmp_path, "2026-08-28", ["txg"])
    mem = run_lengths({"TXG"}, TODAY, tmp_path)
    assert mem["TXG"].run_length == 2
