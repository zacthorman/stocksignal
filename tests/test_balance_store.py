"""Tests for the cached balance readings the daily scan reads.

The ones that matter are the three the module exists to enforce: it never
filters, a missing reading is announced rather than omitted, and a stale store
says how stale it is.
"""

from __future__ import annotations

import json
from datetime import date

from stocksignal.balance_store import (
    MISSING_STORE_NOTE,
    STALE_AFTER_DAYS,
    BalanceStore,
    Reading,
    StoredFlag,
)
from stocksignal.digest import render_markdown
from stocksignal.models import Signal
from stocksignal.scanner import ScanReport

AS_OF = date(2026, 8, 30)
AS_OF_ISO = AS_OF.isoformat()


def store_file(tmp_path, as_of=AS_OF_ISO, readings=None, unreadable=None):
    path = tmp_path / "balance.json"
    path.write_text(
        json.dumps(
            {
                "as_of": as_of,
                "readings": readings
                if readings is not None
                else {
                    "TEM": {
                        "verdict": "CONCERN",
                        "coverage": 3,
                        "flags": [
                            {"severity": "serious", "check": "negative NTAV"},
                            {"severity": "serious", "check": "receivables vs revenue"},
                        ],
                    },
                    "SEZL": {"verdict": "SOLID", "coverage": 3, "flags": []},
                },
                "unreadable": unreadable
                if unreadable is not None
                else {"ASML": "files no us-gaap facts, only ['ifrs-full']"},
            }
        )
    )
    return path


def report(*tickers) -> ScanReport:
    signals = tuple(
        Signal(ticker=t, as_of=AS_OF, close=100.0, score=1.0) for t in tickers
    )
    return ScanReport(as_of=AS_OF, signals=signals, rejected=(), errors=())


# --------------------------------------------------------------------------
# Loading, and the difference between empty and absent
# --------------------------------------------------------------------------


def test_a_missing_file_loads_as_none_not_as_an_empty_store(tmp_path):
    """Nobody has run the sweep, and every name came back unreadable, are
    different states. The digest says different things about them."""
    assert BalanceStore.load(tmp_path / "nothing-here.json") is None


def test_readings_and_unreadables_both_survive_the_round_trip(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    assert s is not None
    assert s.readings["TEM"].verdict == "CONCERN"
    assert s.readings["TEM"].coverage == 3
    assert "ASML" in s.unreadable


# --------------------------------------------------------------------------
# Missing is not a pass, for the third time in this project
# --------------------------------------------------------------------------


def test_a_ticker_with_no_reading_says_so(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    assert "not in the store" in s.line("NVDA")


def test_an_unreadable_ticker_gives_the_reason_rather_than_silence(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    line = s.line("ASML")
    assert "no balance reading" in line
    assert "us-gaap" in line, "the digest should name the cause, not just the gap"


def test_a_digest_with_no_store_announces_it(tmp_path):
    md = render_markdown(report("TEM"), balance=None)
    assert MISSING_STORE_NOTE in md
    assert "TEM" in md, "and the candidate still appears"


# --------------------------------------------------------------------------
# It never filters
# --------------------------------------------------------------------------


def test_an_avoid_verdict_does_not_remove_the_candidate(tmp_path):
    path = store_file(
        tmp_path,
        readings={
            "CMCO": {
                "verdict": "AVOID",
                "coverage": 4,
                "flags": [{"severity": "critical", "check": "negative NTAV"}],
            }
        },
    )
    md = render_markdown(report("CMCO"), balance=BalanceStore.load(path))
    assert "CMCO" in md
    assert "AVOID" in md
    assert "never filters" in md


def test_every_candidate_carries_a_balance_line(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    md = render_markdown(report("TEM", "SEZL", "NVDA"), balance=s)
    assert md.count("**Balance sheet:**") == 3, "including the one with no reading"


# --------------------------------------------------------------------------
# Staleness, the price of caching
# --------------------------------------------------------------------------


def test_a_fresh_store_is_not_stale(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    assert not s.is_stale(AS_OF)
    assert "0 days old" in s.header(AS_OF)


def test_a_store_older_than_a_filing_quarter_says_so(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    later = date.fromordinal(AS_OF.toordinal() + STALE_AFTER_DAYS + 1)
    assert s.is_stale(later)
    assert "Rerun the sweep" in s.header(later)
    assert "has been filed that these readings have never seen" in s.header(later)


def test_the_header_reports_both_halves(tmp_path):
    s = BalanceStore.load(store_file(tmp_path))
    header = s.header(AS_OF)
    assert "2 read" in header
    assert "1 unreadable" in header


# --------------------------------------------------------------------------
# The card surface, where the reading gets its argument rather than its headline
# --------------------------------------------------------------------------


def reading(**kw) -> Reading:
    base = dict(
        ticker="TEM",
        verdict="CONCERN",
        coverage=3,
        flags=(
            StoredFlag("serious", "negative NTAV", "Net tangible assets are NEGATIVE at -334m."),
            StoredFlag("watch", "collection period", "Receivable days went from 81 to 89."),
            StoredFlag("critical", "made up", "Only here to check the ordering."),
        ),
        notes=(
            "1. Cash of 605m, covering 162% of current liabilities.",
            "2. 51% of assets are current, 36% are goodwill and intangibles.",
            "3. Debt: not reported separately.",
            "4. Receivables +101% against payables at +52%.",
        ),
    )
    base.update(kw)
    return Reading(**base)


def test_the_detail_carries_the_numbers_not_just_the_verdict():
    """A card prints the argument. The argument is the figure behind the flag."""
    body = "\n".join(reading().detail())
    assert "-334m" in body
    assert "162% of current liabilities" in body
    assert "Receivables +101%" in body


def test_the_detail_puts_the_worst_flag_first():
    lines = [ln for ln in reading().detail() if ln.startswith("- **")]
    assert lines[0].startswith("- **CRITICAL")
    assert lines[-1].startswith("- **WATCH")


def test_a_clean_sheet_says_no_flags_rather_than_printing_nothing():
    body = "\n".join(reading(verdict="SOLID", flags=()).detail())
    assert "No flags." in body


def test_the_card_prints_the_reading_above_the_ledger_and_says_why():
    from helpers import minimal_card  # noqa: PLC0415

    md = minimal_card(balance=reading())
    assert md.index("balance sheet") < md.index("Elevating and deprecating")
    assert "not folded into the ledger" in md


def test_a_card_with_no_reading_says_so_rather_than_omitting_the_section():
    from helpers import minimal_card  # noqa: PLC0415

    md = minimal_card(balance=None)
    assert "**No reading.**" in md
    assert "price and geometry reading only" in md
