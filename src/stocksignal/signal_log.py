"""Append-only SQLite log of every signal the scanner ever produced.

This file is the reason the project is worth building. Anyone can print a list
of tickers. Keeping an honest, timestamped record of what you claimed and then
scoring it later against what actually happened is the part that turns a toy
into evidence, and it is the part that makes the project worth talking about in
an interview.

Rules: rows are never updated and never deleted. A mistake gets a new row.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from stocksignal.models import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at   TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    close       REAL NOT NULL,
    score       REAL NOT NULL,
    screens     TEXT NOT NULL,
    reasons     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_as_of  ON signals(as_of);

CREATE TABLE IF NOT EXISTS outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   INTEGER NOT NULL REFERENCES signals(id),
    checked_at  TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    close_then  REAL NOT NULL,
    close_now   REAL NOT NULL,
    return_pct  REAL NOT NULL
);
"""


@contextmanager
def connect(db_path: Path | str = "signals.db"):
    """Open the log, creating the schema on first use."""
    path = Path(db_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_signals(signals: Iterable[Signal], db_path: Path | str = "signals.db") -> int:
    """Write signals to the log. Returns how many rows were written."""
    rows = [
        (
            datetime.now().isoformat(timespec="seconds"),
            s.as_of.isoformat(),
            s.ticker,
            s.close,
            s.score,
            ",".join(s.passed_screens),
            " | ".join(s.reasons),
        )
        for s in signals
    ]
    if not rows:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO signals (logged_at, as_of, ticker, close, score, screens, reasons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def recent(limit: int = 20, db_path: Path | str = "signals.db") -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def signals_on(day: date, db_path: Path | str = "signals.db") -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM signals WHERE as_of = ? ORDER BY score DESC", (day.isoformat(),)
        ).fetchall()
