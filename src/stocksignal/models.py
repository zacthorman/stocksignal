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
    beta: float | None = None
    """Volatility against the benchmark. None means it could not be measured,
    which is treated as unknown rather than as zero, exactly as `shares_float`
    is. Computing it needs a benchmark series the scanner does not currently
    fetch, so today this is None everywhere outside tests."""

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
        """Why this signal fired. Only screens that actually passed.

        This used to concatenate every screen's reasons regardless of outcome,
        which read badly on a real digest: because the scoring screens are
        alternatives rather than requirements, a ticker firing on trend alone
        dragged the breakout screen's four rejection notes along with it. NVDA
        appeared as a ranked signal underneath "volume too low", "ignition bar
        too small", "wick disqualifier" and "closed red". Half the digest was
        explaining things that had not happened.

        The failures are still available on `not_firing` for anyone who wants
        them, they just no longer masquerade as the reasoning behind a pass.
        """
        out: list[str] = []
        for r in self.results:
            if r.passed:
                out.extend(r.reasons)
        return out

    @property
    def not_firing(self) -> list[str]:
        """Names of the scoring screens this ticker did not clear.

        Worth keeping and worth keeping short. "This is a trend setup, not a
        breakout" is useful context for a human deciding what to do. The full
        paragraph of why the breakout failed is not.
        """
        return [r.name for r in self.results if not r.passed]

    @property
    def passed_screens(self) -> list[str]:
        return [r.name for r in self.results if r.passed]
