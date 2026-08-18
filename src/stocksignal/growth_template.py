"""The ZipTraderU Growth Template, as code.

READ THIS BEFORE TRUSTING ANY NUMBER THIS MODULE PRODUCES.

**None of this is in the course.** All 256 pages were searched. The words "fair
value multiple", "price to sales", "anticipated growth rate", "scalability",
"certainty factor", "addressable market" and the numbers 0.035 and 1.5 appear
nowhere in them, and neither does any of the twelve scorecard categories. The
course's only pointer is page 6, which lists a Discord channel holding "spread
sheets, trading journals etc". So the template is a handout, not curriculum, and
it has no worked example, no derivation and no explanation attached anywhere.

That matters because the course's OWN price-target method (pages 219 to 232,
implemented in `opportunity.py`) is completely different: it draws targets off
the median, resistance levels and historical run-ups, and its growth step
outputs a bare POSITIVE or NEGATIVE with no rate at all. This module is a
second, independent opinion with different assumptions. It is not the course's
method restated, and the two disagreeing is normal rather than a bug.

WHY IT IS WORTH IMPLEMENTING ANYWAY. It is an axis the technical screens do not
have. Session 4 found the trend and RSI screens carried no incremental edge over
the universe filter, which is precisely the argument for adding a signal that
does not come from price at all. Two independent readings that agree mean
something; two readings from the same price series agreeing mean nothing.

WHERE THE JUDGEMENT LIVES, stated plainly because it is most of the model.
Nine of the twelve scorecard categories have no scoring rule whatsoever, just
a question and a cap. Only three carry numbers: cash runway (1yr=10, 2yr=15,
3yr=20, 5yr=25), market share (10%=2, 25%=5, 50%=10, 75%+=15) and track record
(1yr=5, 3yr=10, 5yr=15). The band the total lands in then multiplies the
historical growth rate by anything from 1.5 down to 0.25, so the fair multiple,
and therefore every price target, swings by a factor of six on judgement calls
with no rubric behind them. `Scorecard` records the reasoning per line for that
reason: an unexplained 20/25 is not a measurement.

THE ARITHMETIC IS LINEAR AND UNBOUNDED, which is the model's sharpest edge.
`fair_multiple = (growth / 0.035) * 1.5` puts no ceiling on anything. A company
growing revenue at 70% earns a 30x price-to-sales multiple, and one at 140%
earns 60x. Real markets do not pay that and never have for long. The template
has no cap, so this module does not silently add one, it flags the multiple as
implausible above a threshold and leaves the number visible. Quietly clamping it
would hide the model's central weakness behind a plausible-looking result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SP500_GROWTH = 0.035
"""Template cell B10, labelled "S&P 500 Average Last 10 Years". It sits in the
denominator under a revenue growth rate and produces a price-to-sales multiple,
so it has to mean the index's average SALES growth, not its price return. The
template never says, and the course never mentions the number at all."""

SP500_MULTIPLE = 1.5
"""Template cell B11, "Average S&P 500 Multiple (Last 10 Years)", the P/S a
company growing at exactly the index average is held to deserve."""

IMPLAUSIBLE_MULTIPLE = 25.0
"""Not from the template, which has no ceiling. A 25x price-to-sales is already
in the top fraction of a percent of public companies historically. Above it the
model has left the range where anything can be checked, so the output is
flagged. It is NOT clamped: see the module docstring."""

BANDS: tuple[tuple[int, int, float, str], ...] = (
    (190, 200, 0.50, "Launching Hyper Growth Rates"),
    (180, 189, 0.25, "New Company Scaling Growth Rates"),
    (170, 179, 0.10, "New Company Scaling Growth Rates"),
    (160, 169, 0.00, "Established Growing Company Rates"),
    (150, 159, -0.10, "First Stage Of Maturing & Slowing Growth Rates"),
    (140, 149, -0.25, "Becoming Maturely Profitable Stage Growth Stagnation Rates"),
    (130, 139, -0.50, "Late Stage Mature Growth Dramatic Drop Rates"),
    (120, 129, -0.75, "Ending Growth Stage Rates"),
)
"""Verbatim from the template's "Rating System For Anticipated Growth Rate
Change". Two things not to normalise away: the 170-179 and 180-189 bands share
a NAME but carry different adjustments, and the adjustment is RELATIVE, "+50%"
multiplies the historical growth rate by 1.5, it does not add 50 points. Cell
B6's `=B4+(B4*B5)` settles that."""

CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("company_health", "Company Health: Balance Sheet, cash runway", 25),
    ("growth_strategy", "Growth Strategy: R&D, marketing, client acquisition", 25),
    ("scalability", "Scalability: TAM over 5 years vs current market cap", 25),
    ("competitive_advantage", "Competitive Advantage vs competition", 25),
    ("new_revenue_streams", "New Revenue Streams: ability to add product lines", 20),
    ("market_share", "Market Share: how much of the market it controls", 15),
    ("market_share_growth", "Market Share Growth: can it dominate given time", 15),
    ("track_record", "Track Record: consecutive years of revenue growth", 15),
    ("leadership", "Leadership Advantage: experience and track record", 15),
    ("profit_margin", "Profit Margin prospects, per unit vs competitors", 10),
    ("certainty", "Certainty Factor: legal/technological/speculative risk", 10),
)
"""The eleven positive categories. They sum to exactly 200. Maturity is the
twelfth and is handled separately because it SUBTRACTS."""

MATURITY_MAX = 25
"""Cell B15 is `=SUM(B3:B13)-B14`, so maturity is a penalty of up to 25. The
real range of the total is therefore -25 to 200, not 0 to 200."""


class TemplateError(ValueError):
    """Raised when the model is being asked for a number it cannot honestly give."""


@dataclass(frozen=True)
class ScoreLine:
    """One scorecard category: the points, the cap, and why."""

    points: float
    maximum: int
    reasoning: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.points <= self.maximum:
            raise TemplateError(f"{self.points} is outside 0 to {self.maximum}")


@dataclass(frozen=True)
class Scorecard:
    """The twelve judgement calls, each with its working attached.

    `reasoning` is required in spirit and enforced by `unexplained`, which the
    report prints. Nine of these categories have no rubric at all, so the only
    thing separating a considered 20/25 from a number someone liked the look of
    is the sentence next to it.
    """

    lines: dict[str, ScoreLine] = field(default_factory=dict)
    maturity: ScoreLine = field(default_factory=lambda: ScoreLine(0, MATURITY_MAX))

    @property
    def total(self) -> float:
        """`=SUM(B3:B13)-B14`. Maturity subtracts."""
        return sum(line.points for line in self.lines.values()) - self.maturity.points

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(key for key, _, _ in CATEGORIES if key not in self.lines)

    @property
    def unexplained(self) -> tuple[str, ...]:
        """Categories scored above zero with no reasoning recorded."""
        return tuple(
            key
            for key, line in self.lines.items()
            if line.points > 0 and not line.reasoning.strip()
        )

    def band(self) -> tuple[float, str]:
        """The growth adjustment this total earns, and its label.

        Below 120 the template forks: "If Less Than 120 & Unprofitable, Avoid.
        If Profitable, Use Earnings Model For Mature Companies." The earnings
        model is supplied by neither the template nor the course, so this raises
        rather than inventing one.
        """
        total = self.total
        for low, high, adjustment, label in BANDS:
            if low <= total <= high:
                return adjustment, label
        if total < 120:
            raise TemplateError(
                f"total {total:.0f} is below 120. The template says avoid if unprofitable, "
                "and switch to an earnings model if profitable. That earnings model does not "
                "exist in the template or the course, so this model cannot value this company."
            )
        raise TemplateError(f"total {total:.0f} is above the 200 the scale allows")


@dataclass(frozen=True)
class Valuation:
    """The full chain, every intermediate kept so the result can be argued with."""

    ticker: str
    historical_growth: tuple[float, ...]
    average_growth: float
    band_adjustment: float
    band_label: str
    anticipated_growth: float
    fair_multiple: float
    projections: tuple[tuple[int, float, float, float], ...]
    """(year, revenue, shares, price target) per projected year."""
    scorecard_total: float
    warnings: tuple[str, ...] = ()

    @property
    def near_target(self) -> float | None:
        """The first projected year's target, the one worth quoting."""
        return self.projections[0][3] if self.projections else None

    def upside_pct(self, close: float) -> float | None:
        target = self.near_target
        if target is None or close <= 0:
            return None
        return (target - close) / close * 100.0


def yoy_growth(revenues: list[float]) -> tuple[float, ...]:
    """`=(B4-B3)/B3` down the column. n revenues give n-1 growth rates."""
    if len(revenues) < 2:
        raise TemplateError("need at least two years of revenue to compute a growth rate")
    out = []
    for previous, current in zip(revenues, revenues[1:]):  # noqa: B905
        if previous == 0:
            raise TemplateError("cannot compute growth from a zero base year")
        out.append((current - previous) / previous)
    return tuple(out)


def fair_multiple(anticipated_growth: float) -> float:
    """`=(B9/B10)*B11`, growth relative to the index, times the index multiple.

    Negative growth produces a negative multiple, which produces a negative
    price target. That is arithmetically correct and financially meaningless, so
    it raises. The template would happily print it.
    """
    if anticipated_growth <= 0:
        raise TemplateError(
            f"anticipated growth of {anticipated_growth:.1%} gives a non-positive multiple. "
            "A shrinking company cannot be valued by this model."
        )
    return (anticipated_growth / SP500_GROWTH) * SP500_MULTIPLE


def value(
    ticker: str,
    years: list[int],
    revenues: list[float],
    shares: list[float],
    scorecard: Scorecard,
    projection_years: int = 4,
) -> Valuation:
    """The whole template, end to end.

        avg_growth        = mean of the historical YoY growth rates
        anticipated       = avg_growth * (1 + band_adjustment)
        fair_multiple     = (anticipated / 0.035) * 1.5
        revenue[y+1]      = revenue[y] * (1 + anticipated)
        price_target[y]   = (revenue[y] / shares[y]) * fair_multiple

    One deliberate departure from the spreadsheet. In the file, the projected
    per-year growth rates in C8:C11 are typed in by hand and are NOT wired to
    the Calculation Center's anticipated rate, a user could compute 40% there
    and type 5% here with nothing objecting. This applies the anticipated rate
    to every projected year, which is what the layout plainly intends, and
    removes a step where the model can silently disagree with itself.

    Share count is held flat at the last known value unless more are supplied.
    The column header says "Include Dilution" and dilution is a real risk on the
    kind of names this scans (the rulebook's own red-flag screen looks for 424B5
    filings), so a flat share count is optimistic and gets a warning.
    """
    if not (len(years) == len(revenues) == len(shares)):
        raise TemplateError("years, revenues and shares must be the same length")
    if any(s <= 0 for s in shares):
        raise TemplateError("share counts must be positive")

    growth = yoy_growth(revenues)
    average = sum(growth) / len(growth)
    adjustment, label = scorecard.band()
    anticipated = average + (average * adjustment)
    multiple = fair_multiple(anticipated)

    warnings: list[str] = []
    if len(growth) < 4:
        warnings.append(
            f"only {len(growth)} growth rate(s) available; the template averages 4. "
            "A short history makes the average unstable."
        )
    if multiple > IMPLAUSIBLE_MULTIPLE:
        warnings.append(
            f"fair multiple of {multiple:.1f}x price-to-sales is beyond anything markets "
            "sustain. The model is linear and uncapped, so a high growth rate runs away. "
            "Treat the target as an upper bound of the model, not of the stock."
        )
    if scorecard.missing:
        warnings.append(f"scored 0 by default: {', '.join(scorecard.missing)}")
    if scorecard.unexplained:
        warnings.append(f"points with no reasoning recorded: {', '.join(scorecard.unexplained)}")
    if len(set(shares)) == 1:
        warnings.append(
            "share count held flat, so dilution is modelled as zero. The column asks for "
            "dilution to be included; check recent 424B5 and S-3 filings."
        )

    last_year, last_revenue, last_shares = years[-1], revenues[-1], shares[-1]
    projections = []
    revenue = last_revenue
    for step in range(1, projection_years + 1):
        revenue = revenue * (1 + anticipated)
        target = (revenue / last_shares) * multiple
        projections.append((last_year + step, revenue, last_shares, target))

    return Valuation(
        ticker=ticker,
        historical_growth=growth,
        average_growth=average,
        band_adjustment=adjustment,
        band_label=label,
        anticipated_growth=anticipated,
        fair_multiple=multiple,
        projections=tuple(projections),
        scorecard_total=scorecard.total,
        warnings=tuple(warnings),
    )


def render_valuation(valuation: Valuation, close: float | None = None) -> str:
    """The working, in markdown, so the result can be disagreed with line by line."""
    out = [
        f"# {valuation.ticker}, Growth Template valuation",
        "",
        "> Not a course method. This template is a Discord handout with no worked example,",
        "> no derivation and nine of its twelve inputs unguided. Treat it as a second",
        "> opinion built on different assumptions, never as confirmation of the chart.",
        "",
        "## The chain",
        "",
        f"- Historical YoY growth: {', '.join(f'{g:.1%}' for g in valuation.historical_growth)}",
        f"- Average: **{valuation.average_growth:.1%}**",
        f"- Scorecard: **{valuation.scorecard_total:.0f}/200** → {valuation.band_label} "
        f"({valuation.band_adjustment:+.0%})",
        f"- Anticipated growth: **{valuation.anticipated_growth:.1%}**",
        f"- Fair multiple: ({valuation.anticipated_growth:.3f} / {SP500_GROWTH}) × "
        f"{SP500_MULTIPLE} = **{valuation.fair_multiple:.1f}x** price-to-sales",
        "",
        "## Projected targets",
        "",
        "| Year | Revenue | Shares | Price target |",
        "| --- | --- | --- | --- |",
    ]
    for year, revenue, shares, target in valuation.projections:
        out.append(f"| {year} | {revenue:,.0f} | {shares:,.0f} | {target:,.2f} |")

    if close is not None:
        upside = valuation.upside_pct(close)
        out += ["", f"Against a {close:,.2f} price, the first projected year is {upside:+.0f}%."]

    if valuation.warnings:
        out += ["", "## Warnings", ""]
        out += [f"- {w}" for w in valuation.warnings]
    return "\n".join(out)
