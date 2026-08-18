"""The cash reading. Deliberately the opposite end of the accounts from the growth template.

WHY THIS EXISTS, in the words it came from.

`Eagle Eye Interview Notes - Michael.md`, sitting at the vault root:

    "Don't look at revenue. Don't look at profit. Look at cash. A lot of people
    say revenue is vanity, profit is sanity, but cash is reality. And that
    absolutely matters. Cash is the lifeblood of a business, everything."

    Interviewer: "So is that the main thing you look at... Cash flow, and then
    work your way up through the statements?"  Michael: "Yeah."

That is a direct rebuttal of the ZipTraderU growth template, and the growth
template's own handover already concedes the point: it is a price-to-sales
model, so two companies with identical revenue value identically whether one is
profitable and the other is burning cash. The template cannot see the thing
Michael says is the only thing worth seeing.

So this module reads the accounts in HIS order, which is the reverse of normal:

    1. Cash flow statement.   Is cash actually being generated?
    2. Balance sheet.         If not, how long before it runs out?
    3. Income statement.      Only now, and only to check the other two.

Revenue is read last and on purpose. In the growth template it is the only
input. Putting it last here is the whole argument.

WHAT THIS IS NOT. It is not a third number to average with the other two. The
opportunity card's rule against summing the elevating and deprecating ledger
applies with more force here, because these three readings are supposed to be
able to contradict each other. A name that scores well on the chart, well on
the growth template and badly on cash is telling you something specific, and an
average would erase exactly that.

The notes leave one question open, and it is not answered here because Michael
never answered it: whether the metric is operating cash flow, free cash flow or
cash conversion. All three are computed and reported separately rather than
picked between.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# The template's own scoring rule for cash runway, which is one of only three
# categories in the whole 200-point sheet that carries a number:
#   1 year of cash = 10, 2 years = 15, 3 years = 20, 5 years = 25.
# Reproduced here rather than referenced, because this module is what can
# actually compute it, and a rule split across two files drifts.
RUNWAY_POINTS: tuple[tuple[float, int], ...] = (
    (5.0, 25),
    (3.0, 20),
    (2.0, 15),
    (1.0, 10),
)

# Cash conversion is operating cash flow over net income. At 1.0 every pound of
# reported profit arrived as cash. Below it, profit is running ahead of cash,
# which is the accrual gap the saying is about. 0.8 is the conventional line
# where the gap stops being timing and starts being a question.
CONVERSION_GOOD = 1.0
CONVERSION_WEAK = 0.8


@dataclass(frozen=True)
class CashReading:
    """One company's accounts read from the bottom up.

    Every field is optional because the data source is patchy on small caps and
    a missing figure must never be read as a zero. `notes` carries the reasoning
    in the order the statements were read.
    """

    ticker: str
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    capex: float | None = None
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    net_income: float | None = None
    revenue: float | None = None
    ocf_history: tuple[float, ...] = ()
    fiscal_years: tuple[int, ...] = ()

    # ---------------------------------------------------------------- step 1
    @property
    def generates_cash(self) -> bool | None:
        """Cash flow statement, read first. The survival test."""
        if self.operating_cash_flow is None:
            return None
        return self.operating_cash_flow > 0

    @property
    def ocf_trend(self) -> str | None:
        """Direction of operating cash flow across the reported years.

        Three readings minimum. Two points is a line through anything.

        MONOTONIC OR ERRATIC, with nothing in between, and the strictness is
        deliberate. The first version allowed one violation, which called
        (1, 9, 2, 3) improving because the ends happened to point up and only
        one step fell. That is not what anyone means by improving cash flow, it
        is a spike followed by a collapse, and a name whose cash flow whipsaws
        is exactly the one this reading exists to catch.

        The strict version also has no threshold in it to argue about, which
        matters here: the repo's first rule is that a bare number inside a
        module is a bug, and "allow one violation" was a bare number wearing a
        comparison.

        Most small caps will read erratic. That is the honest answer for them.
        """
        if len(self.ocf_history) < 3:
            return None
        pairs = list(zip(self.ocf_history, self.ocf_history[1:], strict=False))
        if all(b > a for a, b in pairs):
            return "improving"
        if all(b < a for a, b in pairs):
            return "deteriorating"
        return "erratic"

    # ---------------------------------------------------------------- step 2
    @property
    def burn(self) -> float | None:
        """Annual cash burn. None when the company funds itself.

        Free cash flow rather than operating, because capex a business cannot
        skip is as real a call on the bank balance as wages are.
        """
        if self.free_cash_flow is None:
            return None
        return -self.free_cash_flow if self.free_cash_flow < 0 else None

    @property
    def runway_years(self) -> float | None:
        """Balance sheet, read second. How long the cash lasts at the current burn.

        Returns math.inf when the company is free-cash-flow positive, which is
        not the same as unknown and must not be collapsed into None.
        """
        if self.cash_and_equivalents is None or self.free_cash_flow is None:
            return None
        burn = self.burn
        if burn is None:
            return math.inf
        if burn <= 0:
            return math.inf
        return self.cash_and_equivalents / burn

    @property
    def company_health_points(self) -> int | None:
        """The template's `company_health` category, computed instead of guessed.

        This is the single place where the cash reading feeds the growth
        template rather than merely sitting beside it, and it is legitimate
        precisely because the template states a rule here. The other eight
        unguided categories are left alone.
        """
        years = self.runway_years
        if years is None:
            return None
        if years == math.inf:
            return 25
        for floor, points in RUNWAY_POINTS:
            if years >= floor:
                return points
        return 0

    # ---------------------------------------------------------------- step 3
    @property
    def cash_conversion(self) -> float | None:
        """Income statement, read last. Did the reported profit arrive as cash?

        "Profit is sanity, cash is reality." This is the number that says how
        far apart the two were. Undefined when net income is not positive,
        because a ratio against a loss is not interpretable, and returning a
        number there would be worse than returning nothing.
        """
        if self.operating_cash_flow is None or self.net_income is None:
            return None
        if self.net_income <= 0:
            return None
        return self.operating_cash_flow / self.net_income

    @property
    def net_cash(self) -> float | None:
        """Cash minus debt. Negative means the balance sheet is levered."""
        if self.cash_and_equivalents is None or self.total_debt is None:
            return None
        return self.cash_and_equivalents - self.total_debt

    # ---------------------------------------------------------------- verdict
    @property
    def verdict(self) -> str:
        """One of SELF-FUNDING, FUNDED, TIGHT, BURNING, UNKNOWN.

        Not a score. A state, because the runway question has genuine
        thresholds in the template and a continuous number would hide them.
        """
        years = self.runway_years
        if years is None:
            return "UNKNOWN"
        if years == math.inf:
            return "SELF-FUNDING"
        if years >= 3.0:
            return "FUNDED"
        if years >= 1.0:
            return "TIGHT"
        return "BURNING"

    @property
    def notes(self) -> tuple[str, ...]:
        """The reading, in the order the statements were opened."""
        out: list[str] = []

        if self.operating_cash_flow is None:
            out.append("Cash flow statement: not available.")
        else:
            word = "generated" if self.operating_cash_flow > 0 else "consumed"
            out.append(
                f"Cash flow statement: {word} "
                f"{abs(self.operating_cash_flow) / 1e6:,.0f}M from operations."
            )
            trend = self.ocf_trend
            if trend:
                out.append(f"Operating cash flow is {trend} across {len(self.ocf_history)} years.")
        if self.free_cash_flow is not None:
            sign = "+" if self.free_cash_flow >= 0 else "-"
            out.append(f"Free cash flow {sign}{abs(self.free_cash_flow) / 1e6:,.0f}M after capex.")

        years = self.runway_years
        if years is None:
            out.append("Balance sheet: cash position not available, so runway cannot be computed.")
        elif years == math.inf:
            out.append("Balance sheet: free cash flow is positive, so there is no burn to survive.")
        else:
            out.append(
                f"Balance sheet: {self.cash_and_equivalents / 1e6:,.0f}M of cash against a "
                f"{self.burn / 1e6:,.0f}M burn, which is {years:.1f} years of runway."
            )
        if self.net_cash is not None:
            state = "net cash" if self.net_cash >= 0 else "net debt"
            out.append(f"{abs(self.net_cash) / 1e6:,.0f}M {state}.")

        conv = self.cash_conversion
        if conv is None:
            out.append(
                "Income statement: no positive net income to convert, so the "
                "cash conversion test does not apply."
            )
        elif conv >= CONVERSION_GOOD:
            out.append(
                f"Income statement: cash conversion {conv:.2f}, so the reported profit "
                "arrived as cash."
            )
        elif conv >= CONVERSION_WEAK:
            out.append(f"Income statement: cash conversion {conv:.2f}, slightly behind the profit.")
        else:
            out.append(
                f"Income statement: cash conversion {conv:.2f}. Profit is running well "
                "ahead of the cash, which is the gap the saying is about."
            )
        return tuple(out)


def to_dict(reading: CashReading) -> dict:
    """Plain data for the dashboard. inf becomes None on the wire, with a flag."""
    years = reading.runway_years
    return {
        "ticker": reading.ticker,
        "verdict": reading.verdict,
        "operating_cash_flow": reading.operating_cash_flow,
        "free_cash_flow": reading.free_cash_flow,
        "cash_and_equivalents": reading.cash_and_equivalents,
        "total_debt": reading.total_debt,
        "net_cash": reading.net_cash,
        "net_income": reading.net_income,
        "revenue": reading.revenue,
        "cash_conversion": reading.cash_conversion,
        "ocf_trend": reading.ocf_trend,
        "ocf_history": list(reading.ocf_history),
        "fiscal_years": list(reading.fiscal_years),
        "runway_years": None if years in (None, math.inf) else round(years, 2),
        "self_funding": years == math.inf,
        "company_health_points": reading.company_health_points,
        "notes": list(reading.notes),
    }
