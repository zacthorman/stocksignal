"""The signal log: append-only, and honest about what it stored."""

from __future__ import annotations

from datetime import date

import pytest

from stocksignal import signal_log
from stocksignal.models import ScreenResult, Signal


@pytest.fixture
def db(tmp_path):
    """A throwaway database per test. Never write to the real one from a test."""
    return tmp_path / "test-signals.db"


def a_signal(ticker: str = "AAPL", score: float = 1.2) -> Signal:
    return Signal(
        ticker=ticker,
        as_of=date(2026, 8, 5),
        close=210.5,
        score=score,
        results=(
            ScreenResult("tradability", True, 2.0, ("avg volume clears the floor",)),
            ScreenResult("trend", True, 0.8, ("close is above both averages",)),
        ),
    )


def test_writes_and_reads_back(db):
    assert signal_log.log_signals([a_signal()], db) == 1
    rows = signal_log.recent(10, db)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["close"] == pytest.approx(210.5)


def test_stores_the_reasoning_not_just_the_verdict(db):
    signal_log.log_signals([a_signal()], db)
    row = signal_log.recent(1, db)[0]
    assert "avg volume" in row["reasons"]
    assert "tradability" in row["screens"]


def test_appends_rather_than_replaces(db):
    signal_log.log_signals([a_signal("AAPL")], db)
    signal_log.log_signals([a_signal("AAPL")], db)
    assert len(signal_log.recent(10, db)) == 2


def test_empty_input_writes_nothing(db):
    assert signal_log.log_signals([], db) == 0


def test_query_by_day(db):
    signal_log.log_signals([a_signal("AAPL"), a_signal("MSFT", score=0.4)], db)
    rows = signal_log.signals_on(date(2026, 8, 5), db)
    assert [r["ticker"] for r in rows] == ["AAPL", "MSFT"]  # ordered by score


def test_schema_is_created_on_first_use(db):
    assert not db.exists()
    signal_log.recent(1, db)
    assert db.exists()
