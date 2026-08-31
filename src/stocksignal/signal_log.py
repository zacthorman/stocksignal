"""The record of every signal the scanner ever produced.

This file is the reason the project is worth building. Anyone can print a list
of tickers. Keeping an honest, timestamped record of what you claimed and then
scoring it later against what actually happened is the part that turns a toy
into evidence.

IT HAD NEVER ONCE DONE THAT, AND THE REVIEW ON 31 AUGUST 2026 IS WHERE IT CAME
OUT. The scheduled scan passed `--log`, which wrote `signals.db` on a GitHub
runner. `signals.db` is gitignored, the workflow committed only `digests/`, and
the runner was destroyed a minute later. Thirteen trading days of signals were
written and deleted. The local database held 313 rows from 7 and 10 August and
nothing since, and the `outcomes` table had never held a single row.

So the source of truth is no longer the database. It is `signals/YYYY-MM-DD.jsonl`,
one line per signal, committed alongside the digest for exactly the reason the
digest is committed: it is the only record of what the tool CLAIMED at the time,
which is what you need to score the calls later without marking your own
homework.

WHAT "APPEND-ONLY" NOW MEANS, BECAUSE IT HAS MOVED. The old rule was that rows
are never updated and never deleted. The ledger keeps that guarantee somewhere
better: **git history is the append-only log.** A day's file is written whole,
so re-running a day rewrites its file, and if the content differs the diff is
visible in the commit rather than buried as extra rows nobody queries. Nothing
is lost, and a revision announces itself.

`signals.db` is now a DERIVED CACHE, rebuilt from the ledger with
`import_ledgers`. Deleting it costs nothing. Deleting a ledger file loses
evidence, which is why they are committed and the database is not.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from stocksignal.models import Signal

LEDGER_DIR = Path("signals")
"""Where the committed record lives. One file a day, beside `digests/`."""

SCAN = "scan"
RECONSTRUCTED = "reconstructed from digest"
"""Provenance for a ledger row.

Rows recovered from a digest after the fact carry the numbers the digest
printed and nothing more: the digest records ticker, close, score and reasons,
so a reconstructed row has those and no `logged_at` wall-clock time. Marked
rather than silently mixed in, on the same principle as the vault's
reconstructed daily logs. A record that cannot say where it came from is worth
less than one that can."""

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


def ledger_path(day: date, ledger_dir: Path | str = LEDGER_DIR) -> Path:
    return Path(ledger_dir) / f"{day.isoformat()}.jsonl"


def write_ledger(
    signals: Iterable[Signal],
    ledger_dir: Path | str = LEDGER_DIR,
    source: str = SCAN,
) -> Path | None:
    """Write one day's signals as the committed record. Returns the path.

    WHOLE FILE, NOT AN APPEND. A rerun of the same day rewrites that day's file,
    so the git diff shows what changed rather than the file quietly growing two
    copies of everything. Git history carries the append-only guarantee.

    Returns None when there were no signals, and writes nothing. That is the one
    case where absence is safe, because the digest for the same day already says
    "No candidates passed today" in words. Silence and failure still must not
    look the same, and the digest is where that is enforced.
    """
    rows = list(signals)
    if not rows:
        return None

    day = rows[0].as_of
    stamp = datetime.now().isoformat(timespec="seconds")
    path = ledger_path(day, ledger_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "as_of": s.as_of.isoformat(),
                    "ticker": s.ticker,
                    "close": s.close,
                    "score": s.score,
                    "screens": list(s.passed_screens),
                    "reasons": list(s.reasons),
                    "logged_at": stamp,
                    "source": source,
                },
                sort_keys=True,
            )
            for s in sorted(rows, key=lambda s: (-s.score, s.ticker))
        )
        + "\n"
    )
    return path


def read_ledger(path: Path | str) -> list[dict]:
    """One day's committed record, as dicts. Blank lines are skipped."""
    lines = Path(path).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def import_ledgers(
    ledger_dir: Path | str = LEDGER_DIR, db_path: Path | str = "signals.db"
) -> int:
    """Rebuild the database from the committed ledger. Returns rows written.

    The database is a derived cache, so this REPLACES its contents rather than
    appending to them. That is not a breach of the append-only rule, it is the
    rule moving to where it can actually be kept: the ledger files are the
    record and their history is in git, and a cache you cannot rebuild from the
    record is a second source of truth waiting to disagree with the first.

    `outcomes` is deliberately left alone. Scores computed against a signal are
    not derivable from the ledger and must survive a rebuild.
    """
    files = sorted(Path(ledger_dir).glob("*.jsonl"))
    rows = []
    for f in files:
        for row in read_ledger(f):
            rows.append(
                (
                    row.get("logged_at", ""),
                    row["as_of"],
                    row["ticker"],
                    row["close"],
                    row["score"],
                    ",".join(row.get("screens", ())),
                    " | ".join(row.get("reasons", ())),
                )
            )
    with connect(db_path) as conn:
        conn.execute("DELETE FROM signals")
        conn.executemany(
            "INSERT INTO signals (logged_at, as_of, ticker, close, score, screens, reasons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def recent(limit: int = 20, db_path: Path | str = "signals.db") -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def signals_on(day: date, db_path: Path | str = "signals.db") -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM signals WHERE as_of = ? ORDER BY score DESC", (day.isoformat(),)
        ).fetchall()
