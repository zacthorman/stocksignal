"""Did passing the screens beat not passing them, on the same day, in the same universe?

THE QUESTION THE SPY COMPARISON CANNOT ANSWER. Every name in this watchlist
cleared a beta 2.0 floor, so on a day the market falls 1% the universe falls
two or three. Measuring the signals against SPY therefore measures beta first
and the screens second, and in a month like September 2026 the beta term is
most of the answer. The control for that is not an index: it is the rest of the
same watchlist on the same morning.

THREE COHORTS, TAKEN FROM WHAT THE DIGEST ALREADY COMMITTED.

  passed         the ledger. The tool published these.
  screened out   rejected with a reason beginning `trend:` or `breakout:`. These
                 cleared every hard gate (price, volume, beta, float) and failed
                 only the scoring screens. THIS IS THE CONTROL THAT MATTERS: it
                 is the same tradable universe minus the screens' opinion.
  gated out      rejected on a gate. Kept separate and reported, because a name
                 rejected for a 11m float is not evidence about the screens.

THE UNIT OF OBSERVATION IS THE DAY, NOT THE TRADE. Ninety names bought on one
morning and held twenty sessions share one market move; treating them as ninety
independent observations is how a five-week record turns into a fake sample of
360. So each day yields ONE number, the difference between the cohorts' medians.

AND CONSECUTIVE DAYS ARE NOT INDEPENDENT EITHER, WHICH IS THE SUBTLER HALF. Two
20-session windows starting a day apart share nineteen of their twenty sessions,
and the cohorts themselves barely change overnight: the same names are screened
out on Tuesday as on Monday. Counting both days as separate evidence is the same
error one level up. So the sign test runs ONLY over non-overlapping days, taken
by `independent_days`: the first day, then the next day at least `horizon`
scans later, and so on. That is a deterministic rule fixed in advance rather
than the subset that looks best, and on a five-week ledger it leaves very few
blocks, which is the honest answer about how much this data can support.

The full day-by-day table is still reported, because seeing every day is how you
notice a regime rather than a result. It carries no p-value.

THE STATISTIC, FIXED HERE BEFORE THE FIRST RUN. Median of the per-day
differences in median return, and a two-sided sign test on how many days favour
the passed cohort. Medians rather than means throughout, because this project
has twice now been handed a positive mean that seven trades supplied.

WHAT THIS STILL IS NOT. The window already existed when the statistic was
chosen, so the first run is exploratory however clean the arithmetic. It becomes
a real test only as new days arrive that nobody has seen. Costs are not deducted
anywhere here: both cohorts pay the same round trip, so it cancels, and
subtracting it twice would only flatter neither side.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

MIN_BLOCKS = 5
"""Fewer non-overlapping days than this and no p-value is reported at all.

Five one-sided blocks give 0.0625, the first count that can even approach a
conventional threshold. Four give 0.125, which cannot."""

PASSED = "passed"
SCREENED_OUT = "screened out"
GATED_OUT = "gated out"

REJECTION = re.compile(r"^- \*\*([A-Z][A-Z.\-]*)\*\*: (.+)$")
SCREEN_REASON = re.compile(r"^(trend|breakout)\s*:")


def parse_rejections(text: str) -> dict[str, str]:
    """Split a digest's rejected section into `screened out` and `gated out`.

    The reason text is the classifier, and it is the digest's own words rather
    than a re-derivation: a line whose reason starts `trend:` or `breakout:`
    reached the scoring screens, which means every hard gate already passed.
    """
    out: dict[str, str] = {}
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower().startswith("## rejected")
            continue
        if not in_section:
            continue
        match = REJECTION.match(line.strip())
        if not match:
            continue
        ticker, reason = match.group(1), match.group(2)
        out[ticker.upper()] = SCREENED_OUT if SCREEN_REASON.match(reason) else GATED_OUT
    return out


def sign_test(wins: int, losses: int) -> float:
    """Two-sided sign test. Ties are excluded by the caller, as convention has it.

    Written out rather than imported so the scoring job needs no scipy, and
    because a p-value whose derivation you cannot read is a p-value you cannot
    argue with.
    """
    n = wins + losses
    if n == 0:
        return float("nan")
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


@dataclass(frozen=True)
class DayComparison:
    """One morning: the passed names against the ones the screens turned down."""

    day: date
    horizon: int
    n_passed: int
    n_control: int
    passed_median: float
    control_median: float
    passed_mean: float
    control_mean: float

    @property
    def difference(self) -> float:
        return self.passed_median - self.control_median

    @property
    def favours_screens(self) -> bool:
        return self.difference > 0


def independent_days(days: list[DayComparison], horizon: int) -> list[DayComparison]:
    """Days far enough apart that their holding periods do not overlap.

    Greedy from the earliest, which is arbitrary but fixed: picking the subset
    after seeing the numbers would be choosing the answer. Spacing is counted in
    scans rather than calendar days, since a scan is what produces a cohort.
    """
    kept: list[DayComparison] = []
    last = -(10**6)
    # HORIZON + 1, NOT HORIZON. A block entered on scan e sells at the close of
    # e + h, and the next block entered on e + h buys at the open of that same
    # bar. One shared session is still a shared session, and "non-overlapping"
    # has to mean it.
    for i, day in enumerate(sorted(days, key=lambda d: d.day)):
        if i - last >= horizon + 1:
            kept.append(day)
            last = i
    return kept


@dataclass(frozen=True)
class ControlResult:
    horizon: int
    days: list[DayComparison]

    @property
    def usable(self) -> list[DayComparison]:
        """Non-overlapping days with a non-zero difference. The test's sample."""
        return [d for d in independent_days(self.days, self.horizon) if d.difference != 0]

    @property
    def wins(self) -> int:
        return sum(1 for d in self.usable if d.favours_screens)

    @property
    def losses(self) -> int:
        return len(self.usable) - self.wins

    @property
    def days_favouring(self) -> int:
        """Across every day, overlapping or not. Descriptive, not the test."""
        return sum(1 for d in self.days if d.favours_screens)

    @property
    def median_difference(self) -> float:
        if not self.days:
            return float("nan")
        return float(pd.Series([d.difference for d in self.days]).median())

    @property
    def p_value(self) -> float:
        """From the non-overlapping days alone, and NaN below MIN_BLOCKS.

        WITHHELD RATHER THAN PRINTED SMALL, which is the opposite of the usual
        mistake. With one block `sign_test(1, 0)` is 1.000, and a reader sees
        "p = 1.000" as "measured, and no effect" when what happened is "one
        observation, no test was possible". Four blocks cannot go below 0.125
        however one-sided they are, so a p from them cannot reach a
        conventional threshold and printing one invites a comparison that
        cannot happen. Below the floor there is no number.
        """
        if len(self.usable) < MIN_BLOCKS:
            return float("nan")
        return sign_test(self.wins, self.losses)

    @property
    def floor_p(self) -> float:
        """The smallest p these blocks could produce even if every one agreed."""
        return sign_test(len(self.usable), 0)


def compare_day(
    day: date,
    horizon: int,
    passed: dict[str, float],
    control: dict[str, float],
) -> DayComparison | None:
    """One day's cohorts, already reduced to {ticker: return}. None if either is empty."""
    if not passed or not control:
        return None
    a, b = pd.Series(list(passed.values())), pd.Series(list(control.values()))
    return DayComparison(
        day=day,
        horizon=horizon,
        n_passed=len(a),
        n_control=len(b),
        passed_median=float(a.median()),
        control_median=float(b.median()),
        passed_mean=float(a.mean()),
        control_mean=float(b.mean()),
    )


def read_digest_cohorts(digest_dir: Path | str) -> dict[date, dict[str, str]]:
    """Every digest's rejection split, keyed by the digest's own as-of date."""
    out: dict[date, dict[str, str]] = {}
    for path in sorted(Path(digest_dir).glob("digest-*.md")):
        try:
            day = date.fromisoformat(path.stem.removeprefix("digest-"))
        except ValueError:
            continue
        out[day] = parse_rejections(path.read_text())
    return out
