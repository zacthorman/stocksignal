"""SEC EDGAR: the fundamentals, the dilution flags and the catalyst dates.

WHY EDGAR AND NOT A SCRAPER.

The rulebook's research stack names TipRanks, Finviz and the Nasdaq insider
page. Two of those would have to be scraped, and scraping them would be the
wrong call here for reasons that are practical rather than squeamish: an HTML
scrape breaks silently on a layout change, and silent breakage is the failure
mode this vault complains about more than any other. EDGAR is a documented JSON
API, it is free, it needs no key, and it is the primary source those sites are
themselves reporting. Where a fact exists in a filing, this module reads the
filing.

The one thing EDGAR cannot give is analyst opinion, so the journal's "Monkey
Downgrade?" column is served from a market data provider instead, in
`sources/market.py`. That split is the honest one: facts from filings,
opinions from somewhere that collects opinions.

THREE THINGS THIS FEEDS.

1. The growth template's Company sheet, and two of the three categories in the
   200-point scorecard that carry an actual rule: cash runway and track record.
   The third rule-bearing category, market share, needs a market size figure
   that is not in anyone's filing, so it stays manual.
2. The cash reading in `cashflow.py`, which wants the cash flow statement, the
   balance sheet and the income statement in that order.
3. Two factors that currently abstain on the chart scorecard: "Clear catalyst"
   becomes a recent 8-K, and the dilution check the strategy note has been
   asking for since screen 5 becomes a recent 424B5 or S-3.

FAIR ACCESS. The SEC requires a User-Agent that identifies you with a real
contact address, and rate limits to 10 requests a second. `EdgarClient` refuses
to start without a contact string rather than sending a fake one, and it paces
itself well under the limit. Getting this wrong gets an IP blocked, and it
would be your IP.

PARSING IS SEPARATE FROM FETCHING, on purpose. Every function that interprets
EDGAR's JSON is pure and takes the already-decoded payload, so the whole of the
interesting logic is testable with no network and the offline path the repo
insists on stays intact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

# --------------------------------------------------------------------------
# Which XBRL tags to look for, in order of preference.
#
# Small caps are the reason each of these is a list rather than a string. A
# company that has never had a contract-with-customer disclosure reports plain
# `Revenues`; one that adopted ASC 606 reports the long name; a few report both
# and disagree. First tag that yields annual data wins, and which one won is
# recorded on the record so a surprising number can be traced back.
# --------------------------------------------------------------------------
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)
SHARES_TAGS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "CommonStockSharesOutstanding",
)
OCF_TAGS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)
CASH_TAGS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
DEBT_TAGS = (
    "DebtLongtermAndShorttermCombinedAmount",
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    # A drawn revolving facility is debt, and a lender that reports it under
    # LongTermLineOfCredit files none of the three tags above. Sezzle is the
    # case that put this here: it reports 139,991,000 drawn at 2025 year end
    # and nothing under any LongTermDebt tag, so without this line the balance
    # reading abstained on check 3 for a company carrying real borrowings.
    # Abstaining was at least not wrong, `total_debt` returns None rather than
    # zero, but abstaining on a number the filing states is a poor result.
    "LongTermLineOfCredit",
)
NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss")
RD_TAGS = (
    "ResearchAndDevelopmentExpense",
    "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
)
GROSS_PROFIT_TAGS = ("GrossProfit",)
COST_OF_REVENUE_TAGS = ("CostOfRevenue", "CostOfGoodsAndServicesSold")

# The balance sheet, for `balance.py`. These are the lines Michael's four spot
# checks need: the current/non-current split, the intangibles that separate NAV
# from NTAV, and the receivables and payables whose relative growth is check 4.
ASSETS_TAGS = ("Assets",)
ASSETS_CURRENT_TAGS = ("AssetsCurrent",)
LIABILITIES_TAGS = ("Liabilities",)
LIABILITIES_CURRENT_TAGS = ("LiabilitiesCurrent",)
EQUITY_TAGS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
INVENTORY_TAGS = ("InventoryNet",)
RECEIVABLES_TAGS = (
    "AccountsReceivableNetCurrent",
    "ReceivablesNetCurrent",
    "AccountsAndOtherReceivablesNetCurrent",
)
PAYABLES_TAGS = ("AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent")
GOODWILL_TAGS = ("Goodwill",)
INTANGIBLE_TAGS = (
    "IntangibleAssetsNetExcludingGoodwill",
    "FiniteLivedIntangibleAssetsNet",
)
DEBT_CURRENT_TAGS = (
    "DebtCurrent",
    "LongTermDebtCurrent",
    "ShortTermBorrowings",
    "LinesOfCreditCurrent",
)

# Forms that matter, and what each one means to the rulebook.
DILUTION_FORMS = ("424B5", "424B3", "S-3", "S-3ASR", "S-1")
"""Share offerings. The strategy note is unambiguous: "Share offerings =
dilution risk, check before entry", and the 424B5 checklist on the same page
asks for five specific things from the document."""

INSIDER_FORM = "4"
"""Insider transactions. The rulebook reads these off the Nasdaq insider page,
which is itself reporting Form 4."""

CATALYST_FORMS = ("8-K",)
"""An 8-K is by definition a material event the company had to disclose. That
is a tighter definition of "clear catalyst" than a news feed gives, because a
news feed also carries commentary, and page 133 asks for catalysts rather than
for coverage."""


class EdgarError(RuntimeError):
    """Raised when EDGAR cannot be used safely, rather than used badly."""


@dataclass(frozen=True)
class AnnualSeries:
    """One financial line, by fiscal year, plus which tag produced it."""

    tag: str | None
    values: dict[int, float] = field(default_factory=dict)

    def year_list(self, years: list[int]) -> list[float | None]:
        return [self.values.get(y) for y in years]


@dataclass(frozen=True)
class FilingFlags:
    """What the company has filed recently, read as the rulebook reads it."""

    dilution_filings: tuple[tuple[str, str], ...] = ()
    """(form, date) for offerings inside the window."""
    insider_filings: int = 0
    latest_catalyst: str | None = None
    catalyst_days_ago: int | None = None

    @property
    def dilution_risk(self) -> bool:
        return bool(self.dilution_filings)


# --------------------------------------------------------------------------
# Pure parsing. Everything below takes decoded JSON and returns plain data.
# --------------------------------------------------------------------------


ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 400
"""A duration fact counts as annual only if it spans roughly a year.

This is what keeps quarterly and year-to-date figures out. A 52/53-week retail
calendar runs to 371 days and a stub year can be short, so the band is wide;
anything inside it is a year and anything outside it is not.
"""


def _period_year(row: dict) -> int | None:
    """The year a fact actually belongs to, read off the period, not off `fy`.

    THIS IS THE ONE THING EDGAR WILL CATCH YOU OUT ON, and it did. The `fy` and
    `fp` fields identify the FILING the fact appeared in, not the period the
    fact covers. Every 10-K restates two or three prior years as comparatives,
    and all of them carry the current filing's `fy`.

    Real example, Rocket Lab, fetched 2026-08-17:

        fy=2026  val 601,799,000  period 2025-01-01 to 2025-12-31
        fy=2025  val 244,592,000  period 2023-01-01 to 2023-12-31   <-- comparative

    Keying on `fy` records RKLB's 2025 revenue as 244.6M when it is 601.8M, and
    shifts the whole series a year out. That number feeds the average growth
    rate, which sets the fair multiple, which sets the price target, so the
    error does not stay small. It also breaks the track record streak by
    inventing a fall.

    So the year comes from `end`. For a duration fact (income statement, cash
    flow) `end` is the period end; for an instantaneous fact (balance sheet)
    it is the snapshot date. Using `end` for both is what keeps the statements
    aligned on a company whose fiscal year does not end in December: a June
    year-end reports its FY2025 income for 2024-07-01 to 2025-06-30 and its
    FY2025 balance at 2025-06-30, and both land on 2025.

    Known edge, accepted rather than fudged: a 52/53-week year ending in the
    first days of January lands on the following year. Correcting it would mean
    a threshold on the day of the month, which is the kind of magic number this
    repo treats as a bug.
    """
    end = row.get("end")
    if not end:
        return None
    try:
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    start = row.get("start")
    if start:
        try:
            span = (end_date - date.fromisoformat(start)).days
        except (TypeError, ValueError):
            return None
        if not (ANNUAL_MIN_DAYS <= span <= ANNUAL_MAX_DAYS):
            return None
    return end_date.year


def annual_series(facts: dict, tags: tuple[str, ...]) -> AnnualSeries:
    """Pull one line item as {fiscal_year: value} from a companyfacts payload.

    THE YEAR COMES FROM THE PERIOD, NOT FROM `fy`. See `_period_year`, which is
    where the reasoning and the real counterexample live.

    ONLY 10-K FILINGS, AND THE LATEST ONE WINS. EDGAR returns every context a
    number ever appeared in, so the same period shows up from the original
    10-K, from later comparatives, and from amendments, sometimes with
    different values after a restatement. Taking them in filing order and
    letting the last one win means the record carries the company's current
    view of its own history rather than whichever row happened to be parsed
    last.

    The 10-K filter is on the FORM rather than on `fp`, because a 10-Q carries
    FY-tagged year-to-date figures and would otherwise walk straight in.
    """
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        entry = us_gaap.get(tag)
        if not entry:
            continue
        out: dict[int, tuple[str, float]] = {}
        for unit_rows in (entry.get("units") or {}).values():
            for row in unit_rows:
                if not str(row.get("form", "")).startswith("10-K"):
                    continue
                year = _period_year(row)
                if year is None:
                    continue
                val, filed = row.get("val"), row.get("filed", "")
                if val is None:
                    continue
                try:
                    value = float(val)
                except (TypeError, ValueError):
                    continue
                previous = out.get(year)
                if previous is None or filed >= previous[0]:
                    out[year] = (filed, value)
        if out:
            return AnnualSeries(tag=tag, values={y: v for y, (_, v) in out.items()})
    return AnnualSeries(tag=None)


def filing_flags(
    submissions: dict,
    as_of: date,
    dilution_window_days: int = 180,
    insider_window_days: int = 90,
    catalyst_window_days: int = 30,
) -> FilingFlags:
    """Read the recent filing list into the three things the rulebook asks about.

    Windows differ because the questions differ. A share offering six months old
    is still dilution you are holding through; an 8-K from six months ago is not
    a catalyst for a trade today. The insider window sits between them.
    """
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []

    dilution: list[tuple[str, str]] = []
    insiders = 0
    catalyst: tuple[str, int] | None = None

    for form, filed in zip(forms, dates, strict=False):
        try:
            when = date.fromisoformat(filed)
        except (TypeError, ValueError):
            continue
        age = (as_of - when).days
        if age < 0:
            continue
        if form in DILUTION_FORMS and age <= dilution_window_days:
            dilution.append((form, filed))
        elif form == INSIDER_FORM and age <= insider_window_days:
            insiders += 1
        elif form in CATALYST_FORMS and age <= catalyst_window_days:
            if catalyst is None or age < catalyst[1]:
                catalyst = (filed, age)

    return FilingFlags(
        dilution_filings=tuple(dilution),
        insider_filings=insiders,
        latest_catalyst=None if catalyst is None else catalyst[0],
        catalyst_days_ago=None if catalyst is None else catalyst[1],
    )


def track_record_points(revenue_by_year: dict[int, float]) -> int | None:
    """The template's `track_record` category, computed rather than guessed.

    Its rule, verbatim from the sheet: 1 year of consistent revenue growth = 5,
    3 years = 10, 5 years = 15. "Consistent" is read as consecutive years of
    growth counted back from the most recent, which is the only reading that
    makes the three thresholds mean anything.

    This and `company_health` are the only two of the twelve categories that can
    honestly be automated. Market share has a rule but needs a market size
    figure that no filing carries, and the other nine have no rule at all.
    """
    years = sorted(revenue_by_year)
    if len(years) < 2:
        return None
    streak = 0
    for earlier, later in reversed(list(zip(years, years[1:], strict=False))):
        if revenue_by_year[later] > revenue_by_year[earlier]:
            streak += 1
        else:
            break
    if streak >= 5:
        return 15
    if streak >= 3:
        return 10
    if streak >= 1:
        return 5
    return 0


# --------------------------------------------------------------------------
# The client. The only part that touches the network.
# --------------------------------------------------------------------------


class EdgarClient:
    """Minimal EDGAR client that respects the SEC's fair access policy.

    `contact` must be a real address. The SEC asks for one so they can get in
    touch before blocking an IP, and sending a fake one is how you lose access
    for the whole household rather than for one script.
    """

    BASE_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
    BASE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    TICKERS = "https://www.sec.gov/files/company_tickers.json"

    # The SEC's published ceiling is 10 requests a second. Sitting well under it
    # costs a few minutes across 255 names and removes the whole category of
    # problem, which is the right trade for something that runs weekly.
    MIN_INTERVAL = 0.25

    def __init__(self, contact: str, session=None) -> None:
        if not contact or "@" not in contact:
            raise EdgarError(
                "EDGAR requires a User-Agent with a real contact email. "
                "Pass contact='Your Name your@email.com'."
            )
        import requests  # imported here so the module can be read without it

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": contact, "Accept-Encoding": "gzip, deflate"})
        self._last = 0.0

    def _get(self, url: str) -> dict:
        wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=30)
        self._last = time.monotonic()
        if response.status_code == 404:
            raise EdgarError(f"not found: {url}")
        response.raise_for_status()
        return response.json()

    def cik_map(self) -> dict[str, int]:
        """Ticker to CIK. The payload is an object keyed by index, not a list."""
        raw = self._get(self.TICKERS)
        return {
            str(row["ticker"]).upper(): int(row["cik_str"])
            for row in raw.values()
            if row.get("ticker")
        }

    def company_facts(self, cik: int) -> dict:
        return self._get(self.BASE_FACTS.format(cik=cik))

    def submissions(self, cik: int) -> dict:
        return self._get(self.BASE_SUBMISSIONS.format(cik=cik))


def extract(facts: dict, submissions: dict, as_of: date | None = None) -> dict:
    """Everything the three readings need, from one company's two payloads."""
    as_of = as_of or date.today()
    series = {
        "revenue": annual_series(facts, REVENUE_TAGS),
        "shares": annual_series(facts, SHARES_TAGS),
        "operating_cash_flow": annual_series(facts, OCF_TAGS),
        "capex": annual_series(facts, CAPEX_TAGS),
        "cash_and_equivalents": annual_series(facts, CASH_TAGS),
        "total_debt": annual_series(facts, DEBT_TAGS),
        "net_income": annual_series(facts, NET_INCOME_TAGS),
        # These three do not feed the cash reading. They exist so the growth
        # template's judgement categories arrive with a measurement attached
        # rather than blank: R&D intensity for Growth Strategy, gross margin
        # for Profit Margin. Neither is scored here, because the template
        # states no rule for either.
        "research_and_development": annual_series(facts, RD_TAGS),
        "gross_profit": annual_series(facts, GROSS_PROFIT_TAGS),
        "cost_of_revenue": annual_series(facts, COST_OF_REVENUE_TAGS),
        # Balance sheet. All instantaneous facts, so `_period_year` takes the
        # snapshot date and the duration check does not apply to them.
        "assets": annual_series(facts, ASSETS_TAGS),
        "assets_current": annual_series(facts, ASSETS_CURRENT_TAGS),
        "liabilities": annual_series(facts, LIABILITIES_TAGS),
        "liabilities_current": annual_series(facts, LIABILITIES_CURRENT_TAGS),
        "equity": annual_series(facts, EQUITY_TAGS),
        "inventory": annual_series(facts, INVENTORY_TAGS),
        "receivables": annual_series(facts, RECEIVABLES_TAGS),
        "payables": annual_series(facts, PAYABLES_TAGS),
        "goodwill": annual_series(facts, GOODWILL_TAGS),
        "intangibles": annual_series(facts, INTANGIBLE_TAGS),
        "debt_current": annual_series(facts, DEBT_CURRENT_TAGS),
    }
    years = sorted({y for s in series.values() for y in s.values})[-5:]
    flags = filing_flags(submissions, as_of)

    out: dict = {
        "fiscal_years": years,
        "tags_used": {k: s.tag for k, s in series.items()},
        "dilution_filings": [list(f) for f in flags.dilution_filings],
        "dilution_risk": flags.dilution_risk,
        "insider_filings": flags.insider_filings,
        "latest_catalyst": flags.latest_catalyst,
        "catalyst_days_ago": flags.catalyst_days_ago,
        "track_record_points": track_record_points(series["revenue"].values),
        "growth_deceleration": growth_deceleration(series["revenue"].values),
    }
    for key, s in series.items():
        out[key] = s.year_list(years)
    # EDGAR reports capex as a positive outflow; the cash reading expects the
    # sign convention where it adds to operating cash flow, so it is flipped
    # once here rather than in three places downstream.
    out["capex"] = [None if v is None else -abs(v) for v in out["capex"]]
    return out


def growth_deceleration(revenue_by_year: dict[int, float]) -> float | None:
    """Is accelerated revenue growth starting to slow? Pure arithmetic.

    This answers the template's Maturity row, which is the only one of its
    unguided categories whose QUESTION is fully computable even though its
    SCORING is not. The row asks, verbatim: "Has The Business Reached A Level
    Where Accelerated Revenue Growth Should Start Slowing?" That is the second
    difference of the revenue series and nothing else.

    Returns the change in growth rate in percentage points: the most recent
    year-on-year growth minus the MEDIAN of the years before it. Negative means
    decelerating, which is what the penalty is for. None when there are fewer
    than three growth rates to compare, because two points cannot show a change
    in a trend.

    MEDIAN RATHER THAN MEAN, and the first version got this wrong. Rocket Lab's
    growth rates are 239%, 16%, 78%, 38%: the 239% is a company going from
    almost no revenue to some, which is a base effect rather than a growth rate.
    Against the mean of the prior three (111%) the latest 38% reads as a 73
    point deceleration, which says more about 2022 than about the business. The
    median of the prior three is 78%, so the reading becomes -40 points, which
    is the honest one. Any company that has ever had a near-zero base year has
    this problem, and this universe is full of them.

    Deliberately NOT converted into a penalty score here. The template gives no
    mapping from "growth slowed by 12 points" to a number out of 25, and
    inventing one would be exactly the false precision the handover warns about.
    The number is shown; the points stay a human decision.
    """
    years = sorted(revenue_by_year)
    if len(years) < 4:
        return None
    rates = []
    for earlier, later in zip(years, years[1:], strict=False):
        base = revenue_by_year[earlier]
        if base <= 0:
            return None
        rates.append((revenue_by_year[later] - base) / base)
    if len(rates) < 3:
        return None
    latest, prior = rates[-1], sorted(rates[:-1])
    middle = len(prior) // 2
    median = prior[middle] if len(prior) % 2 else (prior[middle - 1] + prior[middle]) / 2
    return 100.0 * (latest - median)


def window(days: int) -> timedelta:
    """Kept so callers can express a window without importing timedelta."""
    return timedelta(days=days)
