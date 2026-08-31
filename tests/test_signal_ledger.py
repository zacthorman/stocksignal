"""Tests for the committed signal ledger.

The one that matters is that the record survives. Between 11 and 28 August 2026
the scheduled scan logged thirteen trading days of signals to a database on an
ephemeral runner and every one was deleted with the runner.
"""

from __future__ import annotations

import json
from datetime import date

from stocksignal import signal_log
from stocksignal.models import Signal

AS_OF = date(2026, 8, 28)


def sig(ticker: str, score: float = 1.0) -> Signal:
    return Signal(ticker=ticker, as_of=AS_OF, close=100.0, score=score)


# --------------------------------------------------------------------------
# The ledger is the record
# --------------------------------------------------------------------------


def test_a_day_of_signals_is_written_as_one_file_per_day(tmp_path):
    path = signal_log.write_ledger([sig("TXG"), sig("SSRM")], tmp_path)
    assert path == tmp_path / "2026-08-28.jsonl"
    rows = signal_log.read_ledger(path)
    assert {r["ticker"] for r in rows} == {"TXG", "SSRM"}
    assert all(r["as_of"] == "2026-08-28" for r in rows)
    assert all(r["source"] == signal_log.SCAN for r in rows)


def test_rows_are_written_best_first():
    """The digest ranks, so the record should agree with what was shown."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = signal_log.write_ledger([sig("LOW", 0.4), sig("HIGH", 1.5)], d)
        assert [r["ticker"] for r in signal_log.read_ledger(path)] == ["HIGH", "LOW"]


def test_a_rerun_rewrites_the_day_rather_than_doubling_it(tmp_path):
    """Whole file, not an append. Git history carries the append-only rule, and
    a revision should show as a diff rather than as a second copy of everything."""
    signal_log.write_ledger([sig("TXG"), sig("SSRM")], tmp_path)
    path = signal_log.write_ledger([sig("TXG")], tmp_path)
    assert len(signal_log.read_ledger(path)) == 1


def test_a_day_with_no_signals_writes_nothing_and_says_so(tmp_path):
    assert signal_log.write_ledger([], tmp_path) is None
    assert not list(tmp_path.glob("*.jsonl"))


# --------------------------------------------------------------------------
# The database is a derived cache
# --------------------------------------------------------------------------


def test_the_database_can_be_rebuilt_from_the_ledger(tmp_path):
    signal_log.write_ledger([sig("TXG"), sig("SSRM")], tmp_path)
    db = tmp_path / "signals.db"
    assert signal_log.import_ledgers(tmp_path, db) == 2
    assert {r["ticker"] for r in signal_log.signals_on(AS_OF, db)} == {"TXG", "SSRM"}


def test_rebuilding_replaces_rather_than_duplicating(tmp_path):
    """A cache you cannot rebuild is a second source of truth waiting to
    disagree with the first."""
    signal_log.write_ledger([sig("TXG")], tmp_path)
    db = tmp_path / "signals.db"
    signal_log.import_ledgers(tmp_path, db)
    signal_log.import_ledgers(tmp_path, db)
    assert len(signal_log.signals_on(AS_OF, db)) == 1


def test_rebuilding_leaves_outcomes_alone(tmp_path):
    """A score computed against a signal is not derivable from the ledger, so
    it has to survive a rebuild of everything that is."""
    signal_log.write_ledger([sig("TXG")], tmp_path)
    db = tmp_path / "signals.db"
    signal_log.import_ledgers(tmp_path, db)
    with signal_log.connect(db) as conn:
        sid = conn.execute("SELECT id FROM signals").fetchone()["id"]
        conn.execute(
            "INSERT INTO outcomes (signal_id, checked_at, horizon_days, close_then, "
            "close_now, return_pct) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "2026-09-28", 20, 100.0, 110.0, 10.0),
        )
    signal_log.import_ledgers(tmp_path, db)
    with signal_log.connect(db) as conn:
        assert conn.execute("SELECT count(*) c FROM outcomes").fetchone()["c"] == 1


# --------------------------------------------------------------------------
# Provenance, so a rebuilt row can never pass as a logged one
# --------------------------------------------------------------------------


def test_a_reconstructed_row_is_marked_as_one(tmp_path):
    path = signal_log.write_ledger([sig("TXG")], tmp_path, source=signal_log.RECONSTRUCTED)
    row = signal_log.read_ledger(path)[0]
    assert row["source"] == "reconstructed from digest"


def test_every_line_is_valid_json_on_its_own(tmp_path):
    """JSONL, so a truncated file loses its last line and not the whole record."""
    path = signal_log.write_ledger([sig("TXG"), sig("SSRM")], tmp_path)
    for line in path.read_text().splitlines():
        assert json.loads(line)["ticker"]
