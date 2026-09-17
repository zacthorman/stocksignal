"""What the scan remembers between runs, which until now was nothing.

THE COMPLAINT THIS ANSWERS. The freeze review on 31 August counted eleven days
of digests and found TXG, SSRM and CHYM on every one of them, six names on ten
or more, and 136 distinct names passing at least once out of a 256-name
universe. The digest had no notion of "new today" and no memory of what had
already been looked at and declined, so most of each morning's message was the
previous morning's message. That is the thing most likely to make a daily
message stop being read.

TWO KINDS OF MEMORY, AND THEY ARE DIFFERENT.

**Recurrence** is a fact, computed from the committed ledger: how many scans in
a row has this name passed. Nothing is decided by it, it is printed.

**Dismissal** is Zac's decision, recorded so the tool stops asking. This is the
one place the digest is allowed to move a name out of the way, and the reason it
is allowed is that the judgement is the reader's own. The balance layer refuses
to filter because the tool's opinion must not silently remove a name; a person
saying "I have looked at this and the answer is no" is the opposite case.

EVEN SO, DISMISSALS ARE MOVED AND NOT DELETED, AND THEY EXPIRE. A dismissed name
still appears in the digest, under its own heading, with the reason and the days
remaining. A "no" from six weeks ago was a judgement about a chart that has
since changed, and a screener that honoured it forever would be letting a stale
decision quietly shrink the universe. Same argument as the growth direction
call ageing out after a reporting cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from stocksignal.models import Signal
from stocksignal.signal_log import LEDGER_DIR, read_ledger

DISMISSALS = Path("data/dismissed.json")

DEFAULT_DISMISSAL_DAYS = 30
"""Shorter than the growth direction's 90.

The direction call ages on the reporting cycle because that is what refreshes
it. A dismissal is a judgement about a chart, and a chart changes faster than a
quarterly report. Thirty days is a month of trading, long enough to stop the
name nagging and short enough that a setup which genuinely developed gets asked
again."""


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st. The digest prints run
    lengths every morning and two is the commonest one, so "2th" would have
    been on nearly every card."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


@dataclass(frozen=True)
class Recurrence:
    """How long a name has been passing, as a fact and not a verdict."""

    ticker: str
    run_length: int
    first_seen: date

    @property
    def is_new(self) -> bool:
        return self.run_length == 1

    def describe(self) -> str:
        if self.is_new:
            return "new today"
        return f"{ordinal(self.run_length)} scan running, first seen {self.first_seen.isoformat()}"


@dataclass(frozen=True)
class Dismissal:
    ticker: str
    on: date
    reason: str = ""
    days: int = DEFAULT_DISMISSAL_DAYS

    @property
    def expires_on(self) -> date:
        return self.on + timedelta(days=self.days)

    def active_on(self, day: date) -> bool:
        return day < self.expires_on

    def describe(self, day: date) -> str:
        left = (self.expires_on - day).days
        why = f", {self.reason}" if self.reason else ""
        plural = "" if left == 1 else "s"
        return f"dismissed {self.on.isoformat()}{why}. Returns in {left} day{plural}"


def load_dismissals(path: Path | str = DISMISSALS) -> dict[str, Dismissal]:
    """Read the dismissal file. A missing file is an empty memory, not an error."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        t.upper(): Dismissal(
            ticker=t.upper(),
            on=date.fromisoformat(e["on"]),
            reason=e.get("reason", ""),
            days=int(e.get("days", DEFAULT_DISMISSAL_DAYS)),
        )
        for t, e in raw.items()
    }


def run_lengths(
    tickers: set[str], today: date, ledger_dir: Path | str = LEDGER_DIR
) -> dict[str, Recurrence]:
    """How many scans in a row each ticker has passed, today included.

    CONSECUTIVE SCANS, NOT CONSECUTIVE DAYS. The scan runs on weekdays, so a
    name passing on Friday and again on Monday has a run of two. Counting
    calendar days would break every run over every weekend and report the whole
    board as new every Monday, which is the same bug in the other direction.

    A day the scan did not run at all leaves no ledger file and therefore no
    gap, which is the honest reading: nothing was observed, so nothing is known
    about whether the name would have passed.
    """
    days: list[tuple[date, set[str]]] = []
    for f in sorted(Path(ledger_dir).glob("*.jsonl"), reverse=True):
        try:
            day = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if day >= today:
            continue
        days.append((day, {r["ticker"].upper() for r in read_ledger(f)}))

    out: dict[str, Recurrence] = {}
    for ticker in {t.upper() for t in tickers}:
        run, first = 1, today
        for day, names in days:
            if ticker not in names:
                break
            run += 1
            first = day
        out[ticker] = Recurrence(ticker=ticker, run_length=run, first_seen=first)
    return out


@dataclass(frozen=True)
class ScanMemory:
    """Everything the digest knows about what came before."""

    recurrences: dict[str, Recurrence]
    dismissals: dict[str, Dismissal]
    as_of: date

    @classmethod
    def build(
        cls,
        signals: list[Signal],
        as_of: date,
        ledger_dir: Path | str = LEDGER_DIR,
        dismissals_path: Path | str = DISMISSALS,
    ) -> ScanMemory:
        tickers = {s.ticker for s in signals}
        return cls(
            recurrences=run_lengths(tickers, as_of, ledger_dir),
            dismissals=load_dismissals(dismissals_path),
            as_of=as_of,
        )

    def is_dismissed(self, ticker: str) -> bool:
        d = self.dismissals.get(ticker.upper())
        return d is not None and d.active_on(self.as_of)

    def recurrence(self, ticker: str) -> Recurrence | None:
        return self.recurrences.get(ticker.upper())

    def split(self, signals: list[Signal]) -> tuple[list[Signal], list[Signal], list[Signal]]:
        """New, continuing, dismissed. In that order, because that is the order
        they are worth reading in: the only genuinely new information first."""
        new, continuing, dismissed = [], [], []
        for s in signals:
            if self.is_dismissed(s.ticker):
                dismissed.append(s)
                continue
            r = self.recurrence(s.ticker)
            (new if r is not None and r.is_new else continuing).append(s)
        return new, continuing, dismissed
