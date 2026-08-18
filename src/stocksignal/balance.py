"""The balance sheet reading. Michael's four spot checks, plus the red flags.

WHERE THIS COMES FROM.

`Eagle Eye Interview Notes - Michael.md` gave the principle: cash flow first,
then work upward through the accounts. `cashflow.py` implements that. But the
interview left the middle step vague, and a longer talk from the same source
fills it in. He states four spot checks explicitly:

    1. Does the company have enough cash to conduct its normal operations?
    2. How much of the company's assets are current and tangible?
    3. Does the company have debt, and if so how much?
    4. Are trade receivables growing faster than trade payables? Because that
       means cash is leaving the business faster than it is coming in.

Those four are the primary API here. Everything else is a red flag he names
along the way.

WHY THIS MATTERS TO THIS PROJECT SPECIFICALLY.

The growth template is a price-to-sales model. It is blind to costs, margins,
debt and cash by construction, which is a limitation already printed at the
bottom of every card it produces. This module is the answer to that limitation
rather than another restatement of it.

His framing is worth keeping in the code, because it is the whole argument:

    "I've seen more investors do their dough buying cheap stocks without
    checking the balance sheet than any other mistake."

    "If you were only to take a quick look at the balance sheet, you'd think
    that this company trades way below its NAV. The company was worth around
    3 million and the NAV was around 30 million." (A mining company that had
    spent 30 million drilling holes and capitalised it as an asset.)

    "Beware of companies with growing trade receivables, because this just
    means money owed. Even though the business might be profitable, if it has
    problems collecting its cash then it's going to run into trouble."

THE RULE THAT GOVERNS EVERY READING HERE. Missing is not zero, and it is not a
pass. A company that does not report a current-asset split has not passed the
current ratio test, it has declined to answer it, and the two must never look
alike. Every check returns None when it cannot be computed and says so.

NOT SCORED, AND DELIBERATELY. These are checks, not a rating. A single
disqualifying red flag should stop you regardless of how the other eleven read,
which is exactly the argument page 131 makes about the elevating and
deprecating ledger. The output is a list of flags with severities and the
numbers behind them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Thresholds, all from the source rather than invented here.
CURRENT_RATIO_FLOOR = 1.0
"""Below 1.0 "the company may struggle to meet its short-term financial
commitments". His words, and the only threshold he states numerically."""

INTANGIBLE_HEAVY_PCT = 50.0
"""Not his number. Where more than half of total assets are goodwill and
intangibles, the NAV is mostly management's opinion rather than something a
creditor could sell, so NTAV is the figure that matters. Flagged as a prompt to
look, never as a verdict."""

RECEIVABLE_GROWTH_GAP_PTS = 15.0
"""Not his number either. He gives the direction ("growing a lot faster") and
no threshold, so this is a reporting trigger rather than a rule. 15 points of
divergence over a year is enough to be worth reading, and the raw figures are
always printed so the trigger can be disagreed with."""

CRITICAL, SERIOUS, WATCH = "critical", "serious", "watch"


@dataclass(frozen=True)
class Flag:
    severity: str
    check: str
    message: str


@dataclass(frozen=True)
class BalanceSheet:
    """One company's balance sheet, latest year and the year before.

    Every field is optional. Small caps report patchily and a missing line must
    read as unknown rather than as zero, because zero is a much stronger claim.
    """

    ticker: str
    assets: float | None = None
    assets_current: float | None = None
    liabilities: float | None = None
    liabilities_current: float | None = None
    equity: float | None = None
    cash: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    payables: float | None = None
    goodwill: float | None = None
    intangibles: float | None = None
    debt_long: float | None = None
    debt_current: float | None = None
    revenue: float | None = None

    # Prior year, for the year-on-year checks he insists on.
    prev_receivables: float | None = None
    prev_payables: float | None = None
    prev_revenue: float | None = None
    prev_intangibles: float | None = None

    fiscal_years: tuple[int, ...] = ()

    # ------------------------------------------------------------ check 1
    @property
    def current_ratio(self) -> float | None:
        """Current assets over current liabilities. His only stated threshold."""
        if self.assets_current is None or not self.liabilities_current:
            return None
        return self.assets_current / self.liabilities_current

    @property
    def net_current_assets(self) -> float | None:
        """Working capital. Negative is the "potential cash call" he warns about."""
        if self.assets_current is None or self.liabilities_current is None:
            return None
        return self.assets_current - self.liabilities_current

    # ------------------------------------------------------------ check 2
    @property
    def soft_assets(self) -> float | None:
        """Goodwill plus intangibles. Treated as one number because the
        distinction rarely survives contact with a small-cap balance sheet."""
        parts = [v for v in (self.goodwill, self.intangibles) if v is not None]
        return sum(parts) if parts else None

    @property
    def intangible_pct(self) -> float | None:
        if not self.assets or self.soft_assets is None:
            return None
        return 100.0 * self.soft_assets / self.assets

    @property
    def current_pct(self) -> float | None:
        if not self.assets or self.assets_current is None:
            return None
        return 100.0 * self.assets_current / self.assets

    @property
    def nav(self) -> float | None:
        """Net asset value: total assets minus total liabilities.

        Falls back to reported equity, because the two are the same thing by the
        accounting equation and small caps sometimes tag one and not the other.
        """
        if self.assets is not None and self.liabilities is not None:
            return self.assets - self.liabilities
        return self.equity

    @property
    def ntav(self) -> float | None:
        """Net TANGIBLE asset value. NAV with the intangibles stripped out.

        This is the number the mining example turns on. NAV said 30 million,
        the market said 3 million, and the gap was capitalised drilling.
        """
        nav = self.nav
        if nav is None:
            return None
        return nav - (self.soft_assets or 0.0)

    # ------------------------------------------------------------ check 3
    @property
    def total_debt(self) -> float | None:
        parts = [v for v in (self.debt_long, self.debt_current) if v is not None]
        return sum(parts) if parts else None

    @property
    def net_debt(self) -> float | None:
        """Debt minus cash. Negative means net cash, which is the good case."""
        if self.total_debt is None or self.cash is None:
            return None
        return self.total_debt - self.cash

    @property
    def debt_free(self) -> bool | None:
        """ "Companies with zero debt cannot go bankrupt." His words, and while
        that is a simplification, the state is worth reporting on its own."""
        if self.total_debt is None:
            return None
        return self.total_debt == 0

    # ------------------------------------------------------------ check 4
    @property
    def receivable_days(self) -> float | None:
        """Days of revenue sitting in receivables. The cash-collection lag."""
        if self.receivables is None or not self.revenue:
            return None
        return 365.0 * self.receivables / self.revenue

    @property
    def prev_receivable_days(self) -> float | None:
        if self.prev_receivables is None or not self.prev_revenue:
            return None
        return 365.0 * self.prev_receivables / self.prev_revenue

    @staticmethod
    def _growth(now: float | None, before: float | None) -> float | None:
        if now is None or not before:
            return None
        return 100.0 * (now - before) / before

    @property
    def receivable_growth(self) -> float | None:
        return self._growth(self.receivables, self.prev_receivables)

    @property
    def payable_growth(self) -> float | None:
        return self._growth(self.payables, self.prev_payables)

    @property
    def revenue_growth(self) -> float | None:
        return self._growth(self.revenue, self.prev_revenue)

    @property
    def receivable_gap(self) -> float | None:
        """Receivable growth minus payable growth, in percentage points.

        His check 4 exactly. Positive and large means money owed to the company
        is growing faster than money the company owes, so cash leaves before it
        arrives.
        """
        r, p = self.receivable_growth, self.payable_growth
        if r is None or p is None:
            return None
        return r - p

    @property
    def receivables_outrunning_revenue(self) -> float | None:
        """Receivable growth minus revenue growth.

        The MPM tell, and the sharper of the two. Revenue can be booked without
        the cash arriving; if receivables grow faster than the sales that
        created them, the gap is the part that has not been collected.
        """
        r, s = self.receivable_growth, self.revenue_growth
        if r is None or s is None:
            return None
        return r - s

    # ------------------------------------------------------------ verdict
    @property
    def flags(self) -> tuple[Flag, ...]:
        out: list[Flag] = []

        cr = self.current_ratio
        if cr is not None and cr < CURRENT_RATIO_FLOOR:
            out.append(
                Flag(
                    SERIOUS,
                    "current ratio",
                    f"Current ratio {cr:.2f}, below 1.0. Current liabilities exceed current "
                    f"assets by {abs(self.net_current_assets or 0) / 1e6:,.0f}m, which is the "
                    f"shape that precedes a cash call.",
                )
            )

        pct = self.intangible_pct
        if pct is not None and pct > INTANGIBLE_HEAVY_PCT:
            out.append(
                Flag(
                    SERIOUS,
                    "intangibles",
                    f"{pct:.0f}% of total assets are goodwill and intangibles. NAV is "
                    f"{(self.nav or 0) / 1e6:,.0f}m but NTAV is {(self.ntav or 0) / 1e6:,.0f}m. "
                    f"Read the NTAV, because a creditor cannot sell a brand valuation.",
                )
            )

        if self.ntav is not None and self.ntav < 0:
            # NEGATIVE NTAV IS TWO DIFFERENT SIGNALS AND THE FIRST VERSION
            # CONFLATED THEM. Tested against Tempus, which carries 825m of
            # goodwill and intangibles from buying Ambry and Paige, it fired
            # CRITICAL and returned AVOID on a company that had just posted its
            # first profitable quarter. That is the rule misfiring rather than a
            # finding, and the real data caught it.
            #
            # The distinction is where the intangible came from. Goodwill from
            # BUYING a going concern is a business someone paid cash for, and
            # negative NTAV is the ordinary arithmetic of an acquisitive
            # company. Intangibles created by CAPITALISING THE COMPANY'S OWN
            # COSTS are the trap the source describes: the miner who spent 30m
            # drilling holes and booked it as an asset.
            #
            # `intangible_pct` cannot tell them apart, but goodwill can, because
            # goodwill only arises on acquisition. Mostly goodwill gets SERIOUS
            # and an explanation; mostly self-generated gets CRITICAL.
            acquisitive = (
                self.goodwill is not None
                and self.soft_assets
                and self.goodwill / self.soft_assets > 0.5
            )
            if acquisitive:
                out.append(
                    Flag(
                        SERIOUS,
                        "negative NTAV",
                        f"Net tangible assets are NEGATIVE at {self.ntav / 1e6:,.0f}m, because "
                        f"{(self.soft_assets or 0) / 1e6:,.0f}m of the balance sheet is goodwill "
                        f"and intangibles. Most of that is GOODWILL, so it came from buying "
                        f"businesses rather than from capitalising the company's own costs. "
                        f"Ordinary for an acquirer and not the mining-company trap, but it does "
                        f"mean there is no tangible asset backing behind the equity.",
                    )
                )
            else:
                out.append(
                    Flag(
                        CRITICAL,
                        "negative NTAV",
                        f"Net tangible assets are NEGATIVE at {self.ntav / 1e6:,.0f}m and the "
                        f"intangibles are NOT mostly goodwill, so they were largely "
                        f"self-generated. Strip them and the equity is worth less than nothing. "
                        f"This is the shape of a company capitalising its own costs onto the "
                        f"balance sheet.",
                    )
                )

        gap = self.receivable_gap
        if gap is not None and gap > RECEIVABLE_GROWTH_GAP_PTS:
            out.append(
                Flag(
                    SERIOUS,
                    "receivables vs payables",
                    f"Receivables grew {self.receivable_growth:+.0f}% against payables at "
                    f"{self.payable_growth:+.0f}%, a {gap:.0f} point gap. Cash is leaving faster "
                    f"than it arrives.",
                )
            )

        outrun = self.receivables_outrunning_revenue
        if outrun is not None and outrun > RECEIVABLE_GROWTH_GAP_PTS:
            out.append(
                Flag(
                    SERIOUS,
                    "receivables vs revenue",
                    f"Receivables grew {self.receivable_growth:+.0f}% while revenue grew "
                    f"{self.revenue_growth:+.0f}%, a {outrun:.0f} point gap. Sales are being "
                    f"booked faster than they are being collected. This is the pattern that "
                    f"precedes a profitable company running out of money.",
                )
            )

        days, prev_days = self.receivable_days, self.prev_receivable_days
        if days is not None and prev_days is not None and days - prev_days > 20:
            out.append(
                Flag(
                    WATCH,
                    "collection period",
                    f"Receivable days went from {prev_days:.0f} to {days:.0f}. It is taking "
                    f"{days - prev_days:.0f} days longer to get paid than a year ago.",
                )
            )

        nd = self.net_debt
        if nd is not None and self.equity and nd > self.equity:
            out.append(
                Flag(
                    SERIOUS,
                    "leverage",
                    f"Net debt of {nd / 1e6:,.0f}m exceeds equity of {self.equity / 1e6:,.0f}m. "
                    f"Creditors have priority and there is more owed than owned.",
                )
            )

        soft_growth = self._growth(self.intangibles, self.prev_intangibles)
        if soft_growth is not None and soft_growth > 50 and (self.revenue_growth or 0) < 20:
            out.append(
                Flag(
                    WATCH,
                    "capitalised costs",
                    f"Intangibles grew {soft_growth:+.0f}% while revenue grew "
                    f"{self.revenue_growth:+.0f}%. Check whether development costs are being "
                    f"capitalised onto the balance sheet rather than expensed.",
                )
            )

        return tuple(out)

    @property
    def coverage(self) -> tuple[bool, bool, bool, bool]:
        """Which of the four spot checks could actually be answered.

        WHY THIS EXISTS. Every flag above needs a number to fire, so a company
        that reports almost nothing collects no flags and, without this, walks
        away with SOLID. That is the missing-is-not-zero rule failing at the one
        place it matters most, the headline. Sezzle is the live case: it files
        no trade receivable line at all, so check 4 cannot run on it. It still
        answers the other three, which is why it keeps its verdict, but the
        abstention has to be visible rather than absorbed.
        """
        return (
            self.cash is not None,
            self.current_ratio is not None or self.current_pct is not None,
            self.total_debt is not None,
            self.receivable_growth is not None,
        )

    @property
    def verdict(self) -> str:
        """SOLID, WATCH, CONCERN, AVOID or UNKNOWN. A state, not a score."""
        if self.current_ratio is None and self.nav is None:
            return "UNKNOWN"
        # A clean sheet only means something if the sheet was legible. Under
        # half the checks answered is not a pass, it is silence.
        if sum(self.coverage) < 3 and not self.flags:
            return "UNKNOWN"
        sev = {f.severity for f in self.flags}
        if CRITICAL in sev:
            return "AVOID"
        serious = sum(1 for f in self.flags if f.severity == SERIOUS)
        if serious >= 2:
            return "CONCERN"
        if serious == 1:
            return "WATCH"
        if self.flags:
            return "WATCH"
        return "SOLID"

    @property
    def notes(self) -> tuple[str, ...]:
        """The four spot checks, answered in his order."""
        out: list[str] = []

        if self.cash is None:
            out.append("1. Enough cash for normal operations: cash not reported.")
        else:
            cover = ""
            if self.liabilities_current:
                cover = (
                    f", covering {100 * self.cash / self.liabilities_current:.0f}% of "
                    f"current liabilities"
                )
            out.append(f"1. Cash of {self.cash / 1e6:,.0f}m{cover}.")

        cr, cp, ip = self.current_ratio, self.current_pct, self.intangible_pct
        if cr is None and cp is None:
            out.append("2. Current and tangible assets: the split is not reported.")
        else:
            bits = []
            if cp is not None:
                bits.append(f"{cp:.0f}% of assets are current")
            if ip is not None:
                bits.append(f"{ip:.0f}% are goodwill and intangibles")
            if cr is not None:
                bits.append(f"current ratio {cr:.2f}")
            out.append("2. " + ", ".join(bits) + ".")

        if self.total_debt is None:
            out.append("3. Debt: not reported separately.")
        elif self.total_debt == 0:
            out.append("3. No debt at all. A company with no debt cannot be forced under.")
        else:
            nd = self.net_debt
            state = ""
            if nd is not None:
                state = f", so {'net debt' if nd > 0 else 'net CASH'} of {abs(nd) / 1e6:,.0f}m"
            out.append(f"3. Debt of {self.total_debt / 1e6:,.0f}m against cash{state}.")

        r, p = self.receivable_growth, self.payable_growth
        if r is None and self.receivables is None:
            # Sezzle files no trade receivable tag at all. Reporting that as a
            # missing prior year would imply the line exists, and it does not.
            out.append(
                "4. Receivables against payables: no trade receivable line is reported. "
                "For a lender the equivalent sits in the loan book, which is a different "
                "thing and is deliberately not substituted here."
            )
        elif r is None:
            out.append("4. Receivables against payables: prior-year figures not available.")
        else:
            days = self.receivable_days
            tail = f", {days:.0f} days of revenue outstanding" if days is not None else ""
            pay = f" against payables at {p:+.0f}%" if p is not None else ""
            out.append(f"4. Receivables {r:+.0f}%{pay}{tail}.")

        return tuple(out)


def to_dict(b: BalanceSheet) -> dict:
    def r(v, n=2):
        return None if v is None else round(v, n)

    return {
        "ticker": b.ticker,
        "verdict": b.verdict,
        "current_ratio": r(b.current_ratio),
        "net_current_assets": r(b.net_current_assets, 0),
        "current_pct": r(b.current_pct, 1),
        "intangible_pct": r(b.intangible_pct, 1),
        "nav": r(b.nav, 0),
        "ntav": r(b.ntav, 0),
        "total_debt": r(b.total_debt, 0),
        "net_debt": r(b.net_debt, 0),
        "debt_free": b.debt_free,
        "receivable_days": r(b.receivable_days, 1),
        "receivable_growth": r(b.receivable_growth, 1),
        "payable_growth": r(b.payable_growth, 1),
        "revenue_growth": r(b.revenue_growth, 1),
        "receivable_gap": r(b.receivable_gap, 1),
        "receivables_outrunning_revenue": r(b.receivables_outrunning_revenue, 1),
        "flags": [
            {"severity": f.severity, "check": f.check, "message": f.message} for f in b.flags
        ],
        "notes": list(b.notes),
        "fiscal_years": list(b.fiscal_years),
    }
