"""The 0-100 scorecard: twelve factors, weighted, with the evidence attached.

PROVENANCE, because this is the one thing a reader must not get wrong.

There is no 0-100 scorecard in the course. Page 115 is section 5.13.1, four
yes/no questions and four unnumbered "Potential Boosts", and it carries no
numbers, no weights and no scale. The vault records "the 0-100 scorecard from
page 115" as a build item in five separate places. That citation is wrong. It
propagated from a note rather than from the source, and anyone implementing it
is inventing a model, not transcribing one.

What DOES exist, and what this module implements, is the twelve-factor
checklist in `ZTU Trading Journal 2022.xlsx`, which is ZipTrader's own example
journal. Its columns are:

    RSI oversold (below 30)?      Heightened volume?
    Upward direction?             Showing signs of recovery?
    Oversold and increasing?      Favourable upward potential?
    Previous pattern confirmation?    Upward potential long term?
    Clear catalyst?               Monkey downgrade?
    Top loser?                    Entry - Exit = Profit/Loss

That is page 115's four gates plus its four boosts, extended, and recorded as
yes/no. The contribution here is turning eleven of those binaries into graded
readings so that names can be RANKED rather than merely sorted into two piles,
which is the whole point of asking for a score.

THREE RULES INHERITED FROM DECISIONS ALREADY MADE IN THIS VAULT.

1. Gates stay gates. The page 142 universe filter (price, volume, beta) and the
   float floor are pass/fail and are not scored. Page 23 treats a poor
   reward:risk as disqualifying rather than as a low score, and the opportunity
   card already ranks on "has a target, then no big deprecating factor, then
   reward:risk". A score that lets a name buy its way past a gate with points
   elsewhere is not this project's model. `Dropshipping/Product Scoring
   Rubric.md` made the opposite choice for products, deliberately, because "a
   gate hides how close a product actually was" - and it still kept a hard floor
   underneath the score. Both coexist here for the same reason.

2. Unmeasurable is not zero. `growth_template.py` already refuses to let a
   category "scored 0 by default" masquerade as a genuine zero, and the same
   trap is worse here: two of the twelve factors cannot be read off price bars
   at all. A factor that cannot be measured is recorded as None, dropped from
   both the numerator and the denominator, and the resulting COVERAGE is
   reported next to the score. A 71 from nine of twelve factors is a different
   claim from a 71 from twelve, and the card must not let those two look alike.

3. The elevating/deprecating ledger is not summed into this. Page 131: a big
   elevating factor can counter a deprecating one. That is not arithmetic, the
   course never scores it, and `opportunity.py` refuses to. This module scores
   the CHECKLIST. The ledger stays beside it, unsummed, exactly as it is now.

WHAT THIS SCORE IS NOT. It makes no claim that a high number outperforms a low
one. Nothing in this repo has established that, the breakout result was
underpowered and concentrated in a single quarter, and `PRE-REGISTRATION.md`
explicitly closes score cut-offs against the current snapshot. This is a
ranking and triage aid whose product is the reasoning, not the number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.indicators import rsi, sma
from stocksignal.levels import nearest_levels
from stocksignal.models import Quote

# --------------------------------------------------------------------------
# The factor table.
#
# `weight` is the share of the 100 this factor can contribute. Every weight
# below is 1/12 of 100, equal, and that is not a considered judgement: it is the
# same admission `config.py` already makes about the three breakout weights,
# which have been equal and unearned since the day they were written. There is
# no evidence that RSI deserves more or less than volume. Equal weights are the
# honest prior, and the dashboard exists so the user can disagree in public
# rather than have a preference baked in silently here.
# --------------------------------------------------------------------------

GATE = "gate"  # one of the four page 115 entry checks
BOOST = "boost"  # one of the four page 115 potential boosts
JOURNAL = "journal"  # a column in the ZTU journal that is neither of the above


@dataclass(frozen=True)
class FactorSpec:
    key: str
    label: str
    kind: str
    source: str
    weight: float
    question: str
    """The journal's own wording, kept verbatim so the mapping stays auditable."""


FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec(
        "upward_potential",
        "Favourable upward potential",
        GATE,
        "p115 gate 1, p23",
        100 / 12,
        "Favorable Upward Potential?",
    ),
    FactorSpec(
        "confirmation",
        "Confirmation above the 9 SMA",
        GATE,
        "p115 gate 2, p107",
        100 / 12,
        "Do you have a confirmation?",
    ),
    FactorSpec(
        "deal_quality",
        "Good deal on RSI",
        GATE,
        "p115 gate 3",
        100 / 12,
        "RSI OVERSOLD (BELOW 30)?",
    ),
    FactorSpec(
        "directional_strength",
        "Directional strength above the 180 SMA",
        GATE,
        "p115 gate 4, p44",
        100 / 12,
        "Upward Direction?",
    ),
    FactorSpec(
        "pattern_confirmation",
        "Previous pattern confirmation",
        BOOST,
        "p115 boost 5, p75-76",
        100 / 12,
        "Previous Pattern Confirmation?",
    ),
    FactorSpec(
        "catalyst",
        "Clear catalyst",
        BOOST,
        "p115 boost 6, p133",
        100 / 12,
        "Clear Catayst?",
    ),
    FactorSpec(
        "long_term",
        "Upward potential long term",
        BOOST,
        "p115 boost 7, p88-90",
        100 / 12,
        "Upward Potential Long Term?",
    ),
    FactorSpec(
        "recovery",
        "Showing signs of recovery",
        BOOST,
        "p115 boost 8",
        100 / 12,
        "Showing Signs of Recovery?",
    ),
    FactorSpec(
        "volume",
        "Heightened volume",
        JOURNAL,
        "journal, p119",
        100 / 12,
        "Heightened  Volume?",
    ),
    FactorSpec(
        "oversold_rising",
        "Oversold and increasing",
        JOURNAL,
        "journal, p50-59",
        100 / 12,
        "Oversold & Increasing?",
    ),
    FactorSpec(
        "top_loser",
        "Top loser, the overreaction play",
        JOURNAL,
        "journal, p142",
        100 / 12,
        "Top Loser?",
    ),
    FactorSpec(
        "analyst",
        "No analyst downgrade",
        JOURNAL,
        "journal, p145-150",
        100 / 12,
        "Monkey Downgrade?",
    ),
)

SPEC_BY_KEY = {spec.key: spec for spec in FACTORS}

# Bands follow the shape of `Dropshipping/Product Scoring Rubric.md`, which is
# the user's own working rubric in another domain, rather than being invented
# fresh. Wording is deliberately weaker here because that rubric's bands were
# calibrated against an outcome and these have not been.
BANDS: tuple[tuple[float, str, str], ...] = (
    (80.0, "STRONG", "Reads well on nearly every factor. Still your call."),
    (60.0, "WORTH A LOOK", "Enough going for it to be worth opening the chart."),
    (40.0, "WATCH", "Mixed. Nothing here says act today."),
    (0.0, "SKIP", "Fails more of the checklist than it passes."),
)


@dataclass(frozen=True)
class Factor:
    """One factor's reading, its contribution, and why.

    `points` is None when the factor could not be measured. That is the whole
    reason this is not a plain float: a factor that cannot be read must not be
    silently worth zero, because zero is a real and much worse verdict.
    """

    key: str
    label: str
    kind: str
    source: str
    weight: float
    points: float | None
    value: float | None
    detail: str

    @property
    def measured(self) -> bool:
        return self.points is not None

    @property
    def fraction(self) -> float | None:
        """0 to 1 within this factor, independent of its weight.

        The dashboard re-weights client-side, so it needs the reading separated
        from the weighting. Keeping both here means the two can never drift.
        """
        if self.points is None or self.weight <= 0:
            return None
        return self.points / self.weight


@dataclass(frozen=True)
class Scorecard:
    ticker: str
    as_of: date
    close: float
    factors: tuple[Factor, ...] = field(default=())

    dilution_filings: tuple[tuple[str, str], ...] = ()
    """Recent 424B5, S-3 or S-1 filings. CARRIED, NOT SCORED.

    The strategy note asks for this ("share offerings = dilution risk, check
    before entry") and it is now fetched, but it deliberately does not enter the
    score. It belongs to the elevating and deprecating ledger, and page 131 is
    explicit that the ledger is weighed rather than summed. A name with a fresh
    offering should be read as having a fresh offering, not as being 4% worse.
    """

    insider_filings: int | None = None
    """Count of Form 4s in the last 90 days. Also carried, also not scored: the
    rulebook lists insider selling as a factor to weigh, and a raw count cannot
    tell a planned 10b5-1 sale from a signal."""

    @property
    def warnings(self) -> tuple[str, ...]:
        out = []
        if self.dilution_filings:
            forms = ", ".join(f"{form} on {when}" for form, when in self.dilution_filings)
            out.append(
                f"DILUTION RISK: {len(self.dilution_filings)} offering filing(s) in the "
                f"last 180 days ({forms}). The rulebook says check this before entry, "
                f"and the 424B5 checklist wants the address, risk factors, operating "
                f"expenses, cash on hand and dilution chance."
            )
        if self.insider_filings:
            out.append(
                f"{self.insider_filings} Form 4 insider filings in the last 90 days. "
                f"A count cannot tell a scheduled 10b5-1 sale from a signal, so this "
                f"is here to be looked at rather than to be scored."
            )
        return tuple(out)

    @property
    def measured_factors(self) -> tuple[Factor, ...]:
        return tuple(f for f in self.factors if f.measured)

    @property
    def unmeasured(self) -> tuple[str, ...]:
        """Factors that could not be read, named rather than counted.

        Same contract as `Scorecard.missing` in `growth_template.py`. A caller
        that prints the score without printing these is misreporting it.
        """
        return tuple(f.label for f in self.factors if not f.measured)

    @property
    def coverage(self) -> float:
        """Share of the total weight that was actually measurable, 0 to 1."""
        total = sum(f.weight for f in self.factors)
        if total <= 0:
            return 0.0
        return sum(f.weight for f in self.measured_factors) / total

    @property
    def score(self) -> float:
        """0 to 100, renormalised over the weight that could be measured.

        Renormalising rather than dividing by a fixed 100 is what stops an
        unmeasurable factor from acting as a penalty. The price of it is that a
        score from nine factors is a weaker claim than the same score from
        twelve, which is exactly what `coverage` is for.
        """
        measured = self.measured_factors
        if not measured:
            return 0.0
        earned = sum(f.points or 0.0 for f in measured)
        available = sum(f.weight for f in measured)
        if available <= 0:
            return 0.0
        return 100.0 * earned / available

    @property
    def band(self) -> tuple[str, str]:
        for floor, name, note in BANDS:
            if self.score >= floor:
                return name, note
        return BANDS[-1][1], BANDS[-1][2]

    def rescore(self, weights: dict[str, float]) -> float:
        """The same readings under different weights.

        The dashboard does this in the browser. Having it here as well means the
        two can be checked against each other, which is the only way to know the
        slider is showing the truth.
        """
        earned = 0.0
        available = 0.0
        for f in self.measured_factors:
            w = weights.get(f.key, f.weight)
            frac = f.fraction
            if frac is None or w <= 0:
                continue
            earned += frac * w
            available += w
        if available <= 0:
            return 0.0
        return 100.0 * earned / available


# --------------------------------------------------------------------------
# Reading the factors.
#
# Each helper returns (points, raw value, detail). Points None means the factor
# could not be measured. Every detail string is written to be readable on a
# phone, because that is where these are read.
# --------------------------------------------------------------------------


def _ramp(value: float, floor: float, ceiling: float) -> float:
    """0 at the floor, 1 at the ceiling, linear between, clamped outside.

    Same shape `breakout._normalise` and `trend._score_gap` already use, so a
    strong reading on one factor can offset a merely adequate one on another in
    the way the rest of the repo already means by that phrase.
    """
    if ceiling <= floor:
        return 0.0
    return float(min(1.0, max(0.0, (value - floor) / (ceiling - floor))))


def _f(spec: FactorSpec, fraction: float | None, value: float | None, detail: str) -> Factor:
    return Factor(
        key=spec.key,
        label=spec.label,
        kind=spec.kind,
        source=spec.source,
        weight=spec.weight,
        points=None if fraction is None else spec.weight * fraction,
        value=value,
        detail=detail,
    )


def _upward_potential(df: pd.DataFrame, cfg: Config) -> Factor:
    """Gate 1: more room up than down.

    This is the factor that abstains most, and the project already knows why.
    Of 2,636 completed setups only 212 had a measurable reward:risk, because
    92% had no three-touch level above or below. That is a property of the level
    definition, not of the market, and loosening it here to make the number
    appear would be exactly the tuning the pre-registration forbids. So it
    abstains honestly and the coverage figure carries the cost.
    """
    spec = SPEC_BY_KEY["upward_potential"]
    frame = nearest_levels(df, cfg)
    if frame.empty:
        return _f(spec, None, None, "no level history")
    row = frame.iloc[-1]
    rr = float(row.get("reward_risk", np.nan))
    if not math.isfinite(rr):
        up = row.get("resistance", np.nan)
        down = row.get("support", np.nan)
        no_up = not math.isfinite(float(up))
        no_down = not math.isfinite(float(down))
        if no_up and no_down:
            which = "no three-touch level above, and none below"
        elif no_up:
            which = "no three-touch level above"
        else:
            which = "no three-touch level below"
        return _f(spec, None, None, f"cannot be measured: {which}")
    # 1:1 is the point at which the trade stops being a coin flip you pay
    # spread on. 2:1 is the course's own bar (p115), so it earns full marks and
    # anything beyond is not rewarded further: the course does not ask for more.
    frac = _ramp(rr, 1.0, 2.0)
    return _f(spec, frac, rr, f"reward:risk {rr:.2f}:1 against the 2:1 the course asks for")


def _confirmation(df: pd.DataFrame, cfg: Config) -> Factor:
    """Gate 2: the first candle holding above the blue 9 SMA.

    The course defines this as an EVENT, the bar that crosses, and the repo
    already carries the open note that `trend.py` implements it as a STATE which
    stays true for the whole run. Both readings are here: full marks on the
    cross itself, decaying over the following bars, so a name that crossed
    yesterday outranks one that crossed four months ago. That is the difference
    the note is about, expressed as a gradient instead of an argument.
    """
    spec = SPEC_BY_KEY["confirmation"]
    close = df["close"]
    fast = sma(close, cfg.sma_fast)
    above = (close > fast).to_numpy()
    if len(above) < 2 or not np.isfinite(fast.to_numpy()[-1]):
        return _f(spec, None, None, "not enough history for the 9 SMA")
    if not above[-1]:
        return _f(spec, 0.0, 0.0, f"below the {cfg.sma_fast} SMA, no confirmation")
    # Walk back to the bar that crossed.
    bars = 0
    for i in range(len(above) - 1, 0, -1):
        if not above[i - 1]:
            break
        bars += 1
    window = float(cfg.rsi_lookback)  # same patience the RSI arm uses, 10 sessions
    frac = 1.0 - _ramp(float(bars), 0.0, window)
    if bars == 0:
        when = "the cross printed today"
    elif bars == 1:
        when = "crossed 1 session ago"
    else:
        when = f"crossed {bars} sessions ago"
    return _f(spec, frac, float(bars), f"above the {cfg.sma_fast} SMA, {when}")


def _deal_quality(df: pd.DataFrame, cfg: Config) -> Factor:
    """Gate 3: below fair value is an okay deal, oversold is a good deal.

    Graded exactly as page 115 words it, in three steps rather than two, because
    "okay deal" and "good deal" are different answers and the journal's single
    yes/no column loses that.
    """
    spec = SPEC_BY_KEY["deal_quality"]
    values = rsi(df["close"], cfg.rsi_period)
    latest = float(values.iloc[-1]) if len(values) else float("nan")
    if not math.isfinite(latest):
        return _f(spec, None, None, "RSI unavailable")
    if latest <= cfg.rsi_oversold:
        return _f(spec, 1.0, latest, f"RSI {latest:.1f}, oversold, a good deal")
    if latest >= cfg.rsi_overbought:
        return _f(spec, 0.0, latest, f"RSI {latest:.1f}, overbought, not a deal")
    midpoint = 50.0
    if latest <= midpoint:
        frac = 0.5 + 0.5 * (midpoint - latest) / max(midpoint - cfg.rsi_oversold, 1e-9)
        return _f(spec, frac, latest, f"RSI {latest:.1f}, below fair value, an okay deal")
    frac = 0.5 * (cfg.rsi_overbought - latest) / max(cfg.rsi_overbought - midpoint, 1e-9)
    return _f(spec, frac, latest, f"RSI {latest:.1f}, above fair value")


def _directional_strength(df: pd.DataFrame, cfg: Config) -> Factor:
    """Gate 4: trading above the red 180 SMA, the regime line.

    Graded by how far above, not merely whether, because the rulebook says the
    wider the gap the stronger the move. The ceiling is the config's own
    `sma_gap_strong_pct` so this factor cannot drift away from what the trend
    screen already calls strong.
    """
    spec = SPEC_BY_KEY["directional_strength"]
    close = df["close"]
    slow = sma(close, cfg.sma_slow)
    latest_slow = float(slow.iloc[-1]) if len(slow) else float("nan")
    if not math.isfinite(latest_slow) or latest_slow <= 0:
        return _f(spec, None, None, f"not enough history for the {cfg.sma_slow} SMA")
    price = float(close.iloc[-1])
    gap = 100.0 * (price - latest_slow) / latest_slow
    if gap <= 0:
        return _f(spec, 0.0, gap, f"below the {cfg.sma_slow} SMA by {abs(gap):.1f}%, downtrend")
    frac = _ramp(gap, 0.0, cfg.sma_gap_strong_pct)
    return _f(spec, frac, gap, f"{gap:.1f}% above the {cfg.sma_slow} SMA")


def _pattern_confirmation(df: pd.DataFrame, cfg: Config) -> Factor:
    """Boost 5, read as pages 75 and 76 read it: the retest is the tell.

    The course's quality breakout is part of a healthy uptrend that gets
    retested and holds, and it explicitly ranks the pushback holding above the
    ignition bar. `breakout.py` currently treats the retest as a flat bonus,
    which the session log already flags as ranked too low. Here it is the whole
    factor: count how many times in the lookback price broke a level and then
    came back to it and held.
    """
    spec = SPEC_BY_KEY["pattern_confirmation"]
    window = min(len(df), cfg.level_lookback_days)
    if window < cfg.sma_fast * 3:
        return _f(spec, None, None, "not enough history")
    recent = df.iloc[-window:]
    close = recent["close"].to_numpy(dtype=float)
    low = recent["low"].to_numpy(dtype=float)
    fast = sma(recent["close"], cfg.sma_fast).to_numpy(dtype=float)
    holds = 0
    i = cfg.sma_fast
    while i < len(close) - cfg.breakout_retest_window:
        if not (np.isfinite(fast[i]) and np.isfinite(fast[i - 1])):
            i += 1
            continue
        crossed_up = close[i] > fast[i] and close[i - 1] <= fast[i - 1]
        if not crossed_up:
            i += 1
            continue
        j = i + cfg.breakout_retest_window
        pulled_back = np.nanmin(low[i + 1 : j + 1]) <= fast[i] * (
            1 + cfg.breakout_dip_tolerance_pct / 100.0
        )
        held = close[j] > fast[i]
        if pulled_back and held:
            holds += 1
            i = j  # do not count the same episode twice
        i += 1
    # Three is the rulebook's own number for "this is a real thing and not a
    # coincidence". Borrowed deliberately rather than picked.
    frac = _ramp(float(holds), 0.0, float(cfg.level_min_touches))
    word = "pushback held" if holds == 1 else "pushbacks held"
    return _f(spec, frac, float(holds), f"{holds} {word} in the last {window} sessions")


def _catalyst(enrichment: dict | None, cfg: Config) -> Factor:
    """Boost 6, answered from filings rather than from a news feed.

    Page 133 step 5 asks for catalysts. An 8-K is a material event the company
    was legally required to disclose, which is a tighter definition than a news
    feed gives: a feed also carries commentary, and commentary is not a
    catalyst. So the question becomes "has this company filed an 8-K recently",
    which EDGAR answers exactly.

    Freshness is the whole reading. An 8-K from four weeks ago is not a
    catalyst for a trade today, so it decays across the window rather than
    being a flag.
    """
    spec = SPEC_BY_KEY["catalyst"]
    if not enrichment:
        return _f(spec, None, None, "no filings fetched, run scripts/fetch_all.py")
    days = enrichment.get("catalyst_days_ago")
    if days is None:
        return _f(spec, 0.0, None, f"no 8-K in the last {cfg.catalyst_window_days} days")
    frac = 1.0 - _ramp(float(days), 0.0, float(cfg.catalyst_window_days))
    when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return _f(spec, frac, float(days), f"8-K filed {when} ({enrichment.get('latest_catalyst')})")


def _analyst(enrichment: dict | None, _cfg: Config) -> Factor:
    """The journal's "Monkey Downgrade?" column, inverted so more is better.

    The column asks whether there HAS been a downgrade, so the factor is scored
    as the absence of one and named accordingly. Full marks for covered and not
    downgraded, nothing for repeatedly downgraded.

    A name with no analyst coverage abstains rather than scoring full marks.
    That distinction is the whole point: "nobody downgraded it" and "nobody
    follows it" are different facts, and treating the second as the first would
    hand every obscure micro cap a free twelfth of the score.
    """
    spec = SPEC_BY_KEY["analyst"]
    if not enrichment:
        return _f(spec, None, None, "no analyst data fetched, run scripts/fetch_all.py")
    analysts = enrichment.get("analysts") or {}
    if not analysts.get("covered"):
        return _f(spec, None, None, "no analyst coverage found")
    downs = int(analysts.get("downgrades", 0))
    ups = int(analysts.get("upgrades", 0))
    if downs == 0:
        detail = f"no downgrades in 6 months, {ups} upgrade{'s' if ups != 1 else ''}"
        return _f(spec, 1.0, 0.0, detail)
    # Upgrades offset downgrades one for one before the penalty bites, because
    # a name with three of each is contested rather than condemned.
    net = max(0.0, float(downs - ups))
    frac = 1.0 - _ramp(net, 0.0, 3.0)
    return _f(spec, frac, net, f"{downs} downgrade{'s' if downs != 1 else ''} against {ups} up")


def _long_term(df: pd.DataFrame, cfg: Config) -> Factor:
    """Boost 7: where the stock stands long term.

    Read as position inside the trailing range. Low in a range that still has a
    ceiling above it is room to run; pinned at the top of it is not. This is the
    one factor where a HIGH price scores badly, which is intentional and is the
    same logic as the course's overreaction sort on page 142.
    """
    spec = SPEC_BY_KEY["long_term"]
    window = min(len(df), cfg.level_lookback_days)
    if window < cfg.sma_slow // 2:
        return _f(spec, None, None, "not enough history")
    recent = df.iloc[-window:]
    high = float(recent["high"].max())
    low = float(recent["low"].min())
    price = float(recent["close"].iloc[-1])
    if high <= low:
        return _f(spec, None, None, "flat range")
    position = (price - low) / (high - low)
    frac = 1.0 - position
    return _f(
        spec,
        frac,
        100.0 * position,
        f"sits {100 * position:.0f}% up its {window}-session range, "
        f"the high is {100 * (high - price) / max(price, 1e-9):.0f}% above here",
    )


def _recovery(df: pd.DataFrame, cfg: Config) -> Factor:
    """Boost 8, read as the journal reads it: is it turning up.

    Rejection or acceptance of a new direction, measured as higher lows over the
    recent window. Not the same question as confirmation, which asks about one
    line: this asks whether the shape of the last few weeks is upward.
    """
    spec = SPEC_BY_KEY["recovery"]
    window = cfg.sma_fast * 3
    if len(df) < window + 1:
        return _f(spec, None, None, "not enough history")
    lows = df["low"].to_numpy(dtype=float)[-window:]
    third = max(3, window // 3)
    early = float(np.nanmin(lows[:third]))
    late = float(np.nanmin(lows[-third:]))
    if not (math.isfinite(early) and math.isfinite(late)) or early <= 0:
        return _f(spec, None, None, "lows unreadable")
    lift = 100.0 * (late - early) / early
    if lift <= 0:
        return _f(
            spec, 0.0, lift, f"lows still falling, {abs(lift):.1f}% lower over {window} sessions"
        )
    # 10% higher lows over about six weeks is a clear turn on a beta-2 name.
    frac = _ramp(lift, 0.0, 10.0)
    return _f(spec, frac, lift, f"lows {lift:.1f}% higher over the last {window} sessions")


def _volume(quote: Quote, cfg: Config) -> Factor:
    """Heightened volume. The journal asks yes/no; the ratio says how much.

    Floor and ceiling are the breakout screen's own spike thresholds, so the two
    modules cannot come to disagree about what counts as heightened.
    """
    spec = SPEC_BY_KEY["volume"]
    ratio = quote.volume_ratio
    if ratio <= 0:
        return _f(spec, None, None, "no volume data")
    frac = _ramp(ratio, 1.0, cfg.breakout_volume_spike_strong)
    return _f(spec, frac, ratio, f"{ratio:.2f}x the {cfg.avg_volume_window}-session average")


def _oversold_rising(df: pd.DataFrame, cfg: Config) -> Factor:
    """The journal's "Oversold & Increasing?", which is a state machine.

    This is the rule the project already got wrong once and corrected: the dip
    ARMS the name and it stays armed, it is not a coincidence that has to happen
    at one bar. Same reading here. RSI went under the oversold line inside the
    lookback, and it is now rising off it.
    """
    spec = SPEC_BY_KEY["oversold_rising"]
    values = rsi(df["close"], cfg.rsi_period)
    if len(values) < cfg.rsi_lookback + 1:
        return _f(spec, None, None, "not enough history for RSI")
    window = values.to_numpy(dtype=float)[-cfg.rsi_lookback :]
    if not np.any(np.isfinite(window)):
        return _f(spec, None, None, "RSI unavailable")
    trough = float(np.nanmin(window))
    latest = float(values.iloc[-1])
    if trough > cfg.rsi_oversold:
        return _f(
            spec,
            0.0,
            trough,
            f"not armed: RSI low was {trough:.1f}, never under {cfg.rsi_oversold:.0f}",
        )
    if latest <= trough:
        return _f(spec, 0.0, latest, f"armed at RSI {trough:.1f} but still falling")
    lift = latest - trough
    frac = _ramp(lift, 0.0, 15.0)
    return _f(spec, frac, lift, f"armed at RSI {trough:.1f}, now {latest:.1f} and rising")


def _top_loser(df: pd.DataFrame, cfg: Config) -> Factor:
    """The overreaction play. Page 142 sorts the scan by % change to find it.

    Scored on the recent drawdown from the trailing high, not on one day's move,
    because "beaten down unjustifiably" is a state rather than a session.
    """
    spec = SPEC_BY_KEY["top_loser"]
    window = min(len(df), cfg.level_lookback_days)
    if window < 20:
        return _f(spec, None, None, "not enough history")
    recent = df.iloc[-window:]
    peak = float(recent["high"].max())
    price = float(recent["close"].iloc[-1])
    if peak <= 0:
        return _f(spec, None, None, "no valid high")
    drawdown = 100.0 * (peak - price) / peak
    # Below 10% off the high is not a beaten-down name. Past 50% the discount
    # stops being an overreaction and starts being information, so it caps.
    frac = _ramp(drawdown, 10.0, 50.0)
    return _f(spec, frac, drawdown, f"{drawdown:.0f}% off its {window}-session high")


def score_ticker(
    df: pd.DataFrame,
    quote: Quote,
    cfg: Config = DEFAULT_CONFIG,
    enrichment: dict | None = None,
) -> Scorecard:
    """Read all twelve factors for one ticker.

    Pure, like every screen in this repo: no I/O, no printing, no network. The
    bars and the quote answer ten of the twelve; `enrichment` is one ticker's
    record from `data/fundamentals.json` and answers the other two, which
    abstain without it exactly as they did before it existed.

    Passing it in rather than fetching it here is the same protocol boundary the
    repo already draws around prices: the caller fetches, the screen decides.
    """
    factors = (
        _upward_potential(df, cfg),
        _confirmation(df, cfg),
        _deal_quality(df, cfg),
        _directional_strength(df, cfg),
        _pattern_confirmation(df, cfg),
        _catalyst(enrichment, cfg),
        _long_term(df, cfg),
        _recovery(df, cfg),
        _volume(quote, cfg),
        _oversold_rising(df, cfg),
        _top_loser(df, cfg),
        _analyst(enrichment, cfg),
    )
    return Scorecard(
        ticker=quote.ticker,
        as_of=quote.as_of,
        close=quote.close,
        factors=factors,
        dilution_filings=tuple(
            tuple(f) for f in ((enrichment or {}).get("dilution_filings") or [])
        ),
        insider_filings=(enrichment or {}).get("insider_filings"),
    )


def to_dict(card: Scorecard) -> dict:
    """The card as plain data, for the dashboard and the signal log.

    Exports every factor's FRACTION as well as its points, because the dashboard
    re-weights in the browser and needs the reading separated from the weight.
    """
    band, note = card.band
    return {
        "ticker": card.ticker,
        "as_of": card.as_of.isoformat(),
        "close": round(card.close, 4),
        "score": round(card.score, 2),
        "band": band,
        "band_note": note,
        "coverage": round(card.coverage, 4),
        "unmeasured": list(card.unmeasured),
        "warnings": list(card.warnings),
        "dilution_filings": [list(f) for f in card.dilution_filings],
        "insider_filings": card.insider_filings,
        "factors": [
            {
                "key": f.key,
                "label": f.label,
                "kind": f.kind,
                "source": f.source,
                "weight": round(f.weight, 4),
                "fraction": None if f.fraction is None else round(f.fraction, 4),
                "points": None if f.points is None else round(f.points, 4),
                "value": None if f.value is None else round(float(f.value), 4),
                "detail": f.detail,
            }
            for f in card.factors
        ],
    }
