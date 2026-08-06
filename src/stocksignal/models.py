"""The shapes that move between modules.

Keeping these as plain frozen dataclasses (rather than passing dicts around)
is the single highest-leverage habit in this repo. Every function signature
then tells you what it needs, your editor autocompletes fields, and a typo in a
field name is an error rather than a silent None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Quote:
    """A single ticker's latest state, plus the reference data the gates need."""

    ticker: str
    as_of: date
    close: float
    avg_volume: float
    latest_volume: float
    shares_float: float | None = None

    @property
    def volume_ratio(self) -> float:
        """Today's volume against the recent average. Above 1 means unusual interest."""
        if self.avg_volume <= 0:
            return 0.0
        return self.latest_volume / self.avg_volume


@dataclass(frozen=True)
class ScreenResult:
    """What one screen decided, and why.

    `reasons` is not decoration. The rulebook says every signal ships with the
    reasoning attached, so the strings here are the product, not logging.
    """

    name: str
    passed: bool
    score: float = 0.0
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True)
class Signal:
    """A ticker that cleared every hard gate, with its screen results attached."""

    ticker: str
    as_of: date
    close: float
    score: float
    results: tuple[ScreenResult, ...] = field(default=())

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for r in self.results:
            out.extend(r.reasons)
        return out

    @property
    def passed_screens(self) -> list[str]:
        return [r.name for r in self.results if r.passed]
