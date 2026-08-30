"""The balance sheet readings, cached, so the daily scan can use them.

WHY A CACHE AND NOT A LIVE READ. The scan runs every weekday against about 256
tickers. Balance sheets change when a company files, which is four times a year,
so fetching 256 companyfacts payloads daily would be 250 requests to the SEC for
an answer that changed on none of them. Worse, the scan runs in GitHub Actions
where a slow EDGAR would turn a two-minute job into a twenty-minute one and take
the digest down with it.

So `scripts/balance_sweep.py --store` writes `data/balance.json`, that file is
COMMITTED, and the scan reads it. The trade is staleness, and staleness is
handled the only honest way available: the file carries the date it was built
and every digest prints how old it is.

THREE RULES THIS MODULE EXISTS TO ENFORCE.

**It never filters.** An AVOID verdict does not remove a candidate from the
digest. The scan reports; Zac decides. That is the same position as the
opportunity card refusing to print a price target it cannot justify, and the
same position as `balance.py` refusing to sum its own flags. A screener that
silently dropped names on a fundamentals reading would be making the decision
and hiding the reason.

**Missing is not a pass, again.** A ticker with no reading prints "no balance
reading" next to its signal. It does not print nothing. This is the third place
in this project that rule has had to be written down and the second time it was
broken in code before being caught.

**Unreadable is not the same as unread.** The sweep records why each failure
failed, and the foreign issuers are the large case: 35 of the watchlist file
under IFRS and this reader covers us-gaap only. The digest says so by name
rather than leaving ASML looking like a company with nothing to report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# A filing quarter plus a fortnight of filing lag. Past this, at least one set of
# accounts has almost certainly landed that the store has never seen.
STALE_AFTER_DAYS = 105

DEFAULT_STORE = Path("data/balance.json")


@dataclass(frozen=True)
class StoredFlag:
    severity: str
    check: str
    message: str = ""


@dataclass(frozen=True)
class Reading:
    ticker: str
    verdict: str
    coverage: int
    flags: tuple[StoredFlag, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """One line, for the digest table and the phone."""
        if not self.flags:
            return f"{self.verdict}, {self.coverage} of 4 checks answered, no flags"
        checks = ", ".join(sorted({f.check for f in self.flags}))
        return f"{self.verdict}, {self.coverage} of 4 checks answered: {checks}"

    def detail(self) -> list[str]:
        """The full reading, for a card rather than a digest line.

        The four spot checks in his order, then every flag with the numbers
        behind it. A card is already a page of working, so the reading gets its
        argument rather than its headline: the point of a flag is the figure
        that produced it, and "CONCERN" on its own is a rating, which is exactly
        what `balance.py` refuses to produce.
        """
        out = [f"**{self.verdict}**, {self.coverage} of 4 checks answered.", ""]
        out += [f"{i}. {note.split('. ', 1)[-1]}" for i, note in enumerate(self.notes, start=1)]
        if self.notes:
            out.append("")
        if not self.flags:
            out.append("No flags.")
            return out
        for f in sorted(self.flags, key=lambda f: SEVERITY_ORDER.get(f.severity, 9)):
            out.append(f"- **{f.severity.upper()}, {f.check}.** {f.message}")
        return out


SEVERITY_ORDER = {"critical": 0, "serious": 1, "watch": 2}


@dataclass(frozen=True)
class BalanceStore:
    as_of: date
    readings: dict[str, Reading]
    unreadable: dict[str, str]

    @classmethod
    def load(cls, path: Path | str = DEFAULT_STORE) -> BalanceStore | None:
        """The store, or None when there is no file.

        None rather than an empty store on purpose. An empty store and a missing
        one are different states and the digest says different things about
        them: one means every name came back unreadable, which would be alarming,
        the other means nobody has run the sweep.
        """
        path = Path(path)
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        readings = {
            t: Reading(
                ticker=t,
                verdict=r["verdict"],
                coverage=int(r.get("coverage", 0)),
                flags=tuple(
                    StoredFlag(f["severity"], f["check"], f.get("message", ""))
                    for f in r.get("flags", ())
                ),
                notes=tuple(r.get("notes", ())),
            )
            for t, r in (raw.get("readings") or {}).items()
        }
        return cls(
            as_of=date.fromisoformat(raw["as_of"]),
            readings=readings,
            unreadable=dict(raw.get("unreadable") or {}),
        )

    def days_old(self, today: date | None = None) -> int:
        return ((today or date.today()) - self.as_of).days

    def is_stale(self, today: date | None = None) -> bool:
        return self.days_old(today) > STALE_AFTER_DAYS

    def header(self, today: date | None = None) -> str:
        n = self.days_old(today)
        line = (
            f"Balance readings as of {self.as_of.isoformat()}, {n} day"
            f"{'' if n == 1 else 's'} old. "
            f"{len(self.readings)} read, {len(self.unreadable)} unreadable."
        )
        if self.is_stale(today):
            line += (
                f" **Over {STALE_AFTER_DAYS} days old, so at least one quarter of accounts "
                f"has been filed that these readings have never seen.** Rerun the sweep."
            )
        return line

    def line(self, ticker: str) -> str:
        """One line about this ticker's balance sheet. Never empty."""
        r = self.readings.get(ticker.upper())
        if r is not None:
            return r.summary
        why = self.unreadable.get(ticker.upper())
        if why is not None:
            return f"no balance reading, {why}"
        return "no balance reading, this ticker is not in the store"


MISSING_STORE_NOTE = (
    "No balance readings attached. Build them with "
    "`scripts/balance_sweep.py --store data/balance.json` and commit the file. "
    "Until then every candidate below is a price reading only, with nothing said "
    "about cash, debt, or what the sheet is made of."
)
