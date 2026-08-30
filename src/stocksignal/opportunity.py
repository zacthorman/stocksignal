"""The buy case: everything the rulebook says goes into deciding on one stock.

The screens answer "is this worth looking at". This module answers the question
that actually reaches the phone: **why**, **to what price**, **out at what
price**, and **what would make this wrong**. It is the difference between a
digest line and an opportunity card.

Every structure here is traceable to a page of the course. Where the course is
silent, this module says so in the output rather than inventing a rule, because
a card that quietly fabricates the missing half is worse than one that admits
the gap, you can act on an admitted gap.

THE THREE THINGS THIS MODULE REFUSES TO DO, which are the reason it can be
trusted with the rest.

1. **It will not print a discounted price target without a growth direction.**
   Page 219 makes the direction call step 2 of 3 and page 233 says it is "the
   most important step in this process". The direction cannot be computed from
   price bars, it comes from the quarterly report, the guidance range, the
   analyst write-ups and the investor presentation (pages 220 to 223). So the
   direction is an INPUT here, supplied by a research pass, and when it is
   absent the card reports `target = None` with the reason attached. A price
   target derived from chart geometry alone would look identical to a real one
   and mean nothing.

2. **It will not sum the elevating and deprecating factors into a score.** Page
   131: "A big elevating factor can counter a deprecating factor". That is not
   arithmetic and the course never scores it. A net tally would imply a
   precision the method does not have, and would let three trivial elevating
   factors outvote one disqualifying deprecating one. The ledger is presented,
   weighted big or normal, and the judgement stays with the reader.

3. **It will not place the hard stop on the support that earned the setup its
   reward-to-risk ratio** without saying so loudly. This is the one place the
   card contradicts the course, and it is not a preference, it is the finding
   from this project's own session-4 backtest. Page 115 (gate 1) wants a close
   floor so the ratio looks good; page 234 wants the stop at that same previous
   support. Applied together, mechanically, 77% of trades stopped out against
   the control's 57%, and the configuration went from the 96th percentile to
   the 10th. The tighter the ratio makes the floor look, the more certain that
   floor sits inside the noise of a stock selected for beta above 2. Every card
   where the two coincide carries the warning.

WHAT THE COURSE COVERS AND WHAT IT DOES NOT, since the card mixes both.
The median anchor, both price-target methods, the risk/reward framing, the
elevating/deprecating ledger, the entry and exit plan sentence forms, the hard
stop, the 5% trailing stop and the 20% sizing cap are all course-backed, with
page numbers on every one. The Growth Template valuation chain is NOT, it
exists only as a spreadsheet and none of its terms appear anywhere in the 256
pages. That lives in `growth_template.py`, separately, and is labelled there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import rsi, sma, swing_points
from stocksignal.levels import RESISTANCE, SUPPORT, Level, classify_levels, find_levels

# --- The judgement inputs the chart cannot supply -------------------------------

POSITIVE = "positive"
NEGATIVE = "negative"
UNKNOWN = "unknown"

DISCOUNTED = "discounted"
MOMENTUM = "momentum"
AT_MEDIAN = "at median"

ELEVATING = "elevating"
DEPRECATING = "deprecating"

BIG = "big"
NORMAL = "normal"


@dataclass(frozen=True)
class CardConfig:
    """Tunables that belong to the card rather than to the screens.

    Kept out of `Config` deliberately. `Config` is frozen, validated and
    referenced by the backtest, and every number in it has either a page
    citation or a calibration behind it. Nothing here has been backtested, so
    mixing them would let an uncalibrated number inherit the credibility of a
    calibrated one.
    """

    median_window_days: int = 252
    """One year, per page 219: "we find the Median price on our chart for the
    last year". Crash events are deliberately INCLUDED, page 220 is explicit:
    "We need to include everything on the price chart for that year so that we
    have the full context." No outlier trimming."""

    median_disagreement_pct: float = 15.0
    """The course eyeballs "the rough middle of this Chart", which is the
    midpoint of the visible range. The median of daily closes is the obvious
    statistical proxy and usually agrees. When they diverge by more than this,
    the distribution is skewed enough that the eyeball and the statistic mean
    different things, and the card says so rather than picking a winner."""

    run_up_count: int = 3
    """Page 231: "We can look at the three last periods with the increase in
    price". Three is what the worked example uses."""

    run_up_iterations: float = 1.0
    """Page 232 multiplies the average run-up by the number of growth
    iterations expected, using 3 for JMIA on the judgement that growth was
    accelerating "2-3 times" (the page says 3-4 in one sentence and 2-3 two
    paragraphs later, then uses 3). There is NO RULE behind the number. Default
    is 1, meaning "growth merely continues", and anything above it must be a
    deliberate human input."""

    account_size: float | None = None
    max_position_pct: float = 20.0
    """Page 40: "Limit your Capital used in a trade to maximum of 20% of your
    account. 20% is also pushing it." The wording is a ceiling, not a target."""

    trail_pct: float = 5.0
    """Page 237 to 238, applied only AFTER the price target is reached."""

    stop_two_supports_below: bool = False
    """Page 235: "If you are really bullish on something then you can put your
    exit-point two support levels below." A judgement input, off by default."""


@dataclass(frozen=True)
class GrowthDirection:
    """Step 2 of the price target method, which no amount of price data supplies.

    Page 223: "You have to ask yourself the question 'Is the Company (Not the
    Stock) I am analyzing is on a path of growth and will their business
    continue to expand'." The output is strictly binary in the course, there is
    no growth *rate* anywhere in it, so this is POSITIVE, NEGATIVE or UNKNOWN
    and nothing finer.

    `basis` is the working, not decoration. Page 223's own summary of the RAD
    call reads as three clauses: the quarterly headline numbers, the new
    initiative in the presentation, and the market sentiment. A direction with
    no basis attached is a guess wearing a label.
    """

    call: str = UNKNOWN
    basis: tuple[str, ...] = ()
    researched_on: date | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if self.call not in (POSITIVE, NEGATIVE, UNKNOWN):
            raise ValueError(f"call must be positive, negative or unknown, got {self.call!r}")

    @property
    def is_positive(self) -> bool:
        return self.call == POSITIVE

    def describe(self) -> str:
        if self.call == UNKNOWN:
            return "growth direction NOT RESEARCHED, the most important step is missing"
        stamp = f" as of {self.researched_on}" if self.researched_on else ""
        return f"growth direction {self.call.upper()}{stamp}"


@dataclass(frozen=True)
class PriceTarget:
    """A target, the method that produced it, and the working behind it.

    `price` is None when the method could not run. The reasons say why, and an
    unrunnable method is a normal outcome rather than an error: a stock with
    only one resistance above its median genuinely has no midpoint to aim at.
    """

    price: float | None
    method: str
    basis: tuple[str, ...] = ()
    horizon_months: int = 6
    """Page 219: "Where do you see this stock going over the next Six months?" """

    def upside_pct(self, close: float) -> float | None:
        if self.price is None or close <= 0:
            return None
        return (self.price - close) / close * 100.0


@dataclass(frozen=True)
class Factor:
    """One elevating or deprecating factor, with its weight and its page.

    Weight is BIG or NORMAL rather than a number, because page 131's rule is
    "A big elevating factor can counter a deprecating factor" and the course
    never quantifies further. Two buckets is exactly as much precision as the
    source supports.
    """

    text: str
    kind: str
    weight: str = NORMAL
    page: str = ""

    def describe(self) -> str:
        mark = "!" if self.weight == BIG else ""
        cite = f" (p{self.page})" if self.page else ""
        return f"{mark}{self.text}{cite}"


@dataclass(frozen=True)
class PositionPlan:
    """Sizing and the money at risk. Pages 39 to 41."""

    account_size: float | None
    max_position_value: float | None
    shares_at_cap: int | None
    risk_per_share: float | None
    max_loss_at_cap: float | None
    note: str = ""


@dataclass(frozen=True)
class OpportunityCard:
    """One stock, fully worked up. The thing that reaches the phone."""

    ticker: str
    as_of: date
    close: float

    median: float | None
    median_basis: tuple[str, ...]
    play_type: str

    direction: GrowthDirection
    target: PriceTarget
    alternate_target: PriceTarget | None

    support: float | None
    resistance: float | None
    hard_stop: float | None
    reward_risk: float | None

    elevating: tuple[Factor, ...]
    deprecating: tuple[Factor, ...]

    entry_plan: str
    exit_plan: str
    position: PositionPlan
    warnings: tuple[str, ...] = field(default=())

    # THE BALANCE READING SITS OUTSIDE THE LEDGER, AND THAT IS THE WHOLE POINT.
    # It would have been easy to append the flags to `deprecating` and let them
    # take their chances in the table. Page 131 says a big elevating factor can
    # counter a deprecating one, so putting a negative-NTAV flag in there means
    # three good factors can talk past it. That is precisely the mistake the
    # source warns about: "I've seen more investors do their dough buying cheap
    # stocks without checking the balance sheet than any other mistake."
    #
    # So it is a separate field, printed above the ledger, and nothing in the
    # card is allowed to net it off. It still does not decide, because the card
    # does not decide. It just cannot be argued with by the other section.
    balance: object | None = None

    @property
    def upside_pct(self) -> float | None:
        return self.target.upside_pct(self.close)

    @property
    def has_target(self) -> bool:
        return self.target.price is not None

    @property
    def big_deprecating(self) -> tuple[Factor, ...]:
        return tuple(f for f in self.deprecating if f.weight == BIG)


# --- Step 1: the median anchor (pages 219 to 220) --------------------------------


def median_anchor(df: pd.DataFrame, cfg: CardConfig) -> tuple[float | None, tuple[str, ...]]:
    """The "rough middle of this Chart" over the last year.

    Page 220 describes eyeballing the middle of the visible price channel, which
    is the midpoint of the range, not the median of the closes. The two are the
    same on a symmetric year and diverge on a skewed one, a stock that spent
    eleven months at $10 and one month at $40 has a range midpoint of $25 and a
    close-median near $10, and those are different claims about what a fair
    price was.

    So the range midpoint is returned (it is what the course draws) and the
    close median is computed as a cross-check. When they disagree by more than
    the configured tolerance the card carries a note, because on those charts
    "the middle" is genuinely ambiguous and the reader should look at it.
    """
    if df.empty:
        return None, ("no price history",)

    window = df.tail(min(cfg.median_window_days, len(df)))
    high = float(window["high"].max())
    low = float(window["low"].min())
    midpoint = (high + low) / 2.0
    close_median = float(window["close"].median())

    sessions = len(window)
    basis = [
        f"range {low:,.2f} to {high:,.2f} over {sessions} sessions, midpoint {midpoint:,.2f}",
        f"median of closes {close_median:,.2f}",
    ]
    if sessions < cfg.median_window_days:
        basis.append(
            f"only {sessions} sessions available, the method asks for {cfg.median_window_days}"
        )
    if (
        midpoint > 0
        and abs(midpoint - close_median) / midpoint * 100.0 > cfg.median_disagreement_pct
    ):
        basis.append(
            "range midpoint and close median disagree by more than "
            f"{cfg.median_disagreement_pct:.0f}%, skewed year, eyeball the chart"
        )
    return midpoint, tuple(basis)


def classify_play(close: float, median: float | None) -> str:
    """Discounted or momentum, which decides WHICH target method applies.

    The course teaches two and they are not interchangeable. RAD (pages 219 to
    225) trades at $9 against a $14 median: a discounted play, and the target
    comes off resistance levels. JMIA (pages 226 to 232) trades at $38 against a
    $20 median: a momentum play, "which keeps breaking into higher highs so
    current price will be way above the median price", and the target comes off
    the average run-up instead.

    The median is the divider. Page 227 insists the median is still worth
    computing for a momentum name because "If we see that there is downward
    pressure then the median will start going down as well".
    """
    if median is None or median <= 0:
        return AT_MEDIAN
    if close < median * 0.98:
        return DISCOUNTED
    if close > median * 1.02:
        return MOMENTUM
    return AT_MEDIAN


# --- Step 3a: the discounted target (pages 223 to 225) ---------------------------


def discounted_target(
    levels: tuple[Level, ...],
    median: float | None,
    close: float,
    direction: GrowthDirection,
) -> PriceTarget:
    """Midpoint of the two resistance levels above the median.

    Page 224: "every single time the stock went to this median it later went up
    to these two levels of resistance as shown below. Therefore, we will set the
    price target in the range of this lower resistance to the higher
    resistance." Page 225: "So we set the price target right in the middle of
    these two Resistance levels i.e. 17$."

    CONDITIONAL ON A POSITIVE DIRECTION, and this is load-bearing. Page 224
    opens the placement with "Since our Growth direction is positive, our
    projection is that RAD is going to continue to grow and actually surpass the
    value it was providing". Without that clause the whole construction is just
    "point at the resistance levels", which would produce an identical-looking
    number for a company in terminal decline.
    """
    if not direction.is_positive:
        return PriceTarget(
            None,
            DISCOUNTED,
            (
                f"not placed: {direction.describe()}",
                "page 224 places the target only on a positive growth direction",
            ),
        )
    if median is None:
        return PriceTarget(None, DISCOUNTED, ("not placed: no median anchor",))

    above = sorted(
        (lv for lv in levels if lv.kind == RESISTANCE and lv.price > median),
        key=lambda lv: lv.price,
    )
    if len(above) < 2:
        return PriceTarget(
            None,
            DISCOUNTED,
            (
                f"not placed: needs two resistance levels above the median {median:,.2f}, "
                f"found {len(above)}",
            ),
        )

    lower, upper = above[0], above[1]
    price = (lower.price + upper.price) / 2.0
    return PriceTarget(
        price,
        DISCOUNTED,
        (
            f"median {median:,.2f}, price {close:,.2f} sits below it",
            f"resistance above the median at {lower.price:,.2f} ({lower.touches} touches) "
            f"and {upper.price:,.2f} ({upper.touches} touches)",
            f"target is the midpoint, {price:,.2f}",
        ),
    )


# --- Step 3b: the momentum target (pages 231 to 232) -----------------------------


def average_run_up(
    df: pd.DataFrame, cfg: Config, card: CardConfig
) -> tuple[float | None, tuple[str, ...]]:
    """Mean dollar magnitude of the last few major run-ups.

    Page 231: "We can look at the three last periods with the increase in price
    shown as well below... If we add all of these run-ups together and take an
    average." A run-up is a swing low to the swing high that follows it.

    The course eyeballs "the three last periods" off a chart, which in practice
    means the three visually obvious ones rather than the three most recent. The
    largest N inside the window is the closest mechanical reading of "major",
    and it is stated in the basis so the reader knows which convention produced
    the number.

    OCR WARNING carried forward: the three individual magnitudes behind the
    worked example's $18 average sit inside an image and did not survive OCR.
    Only the result is legible in the text. The method is reconstructed from the
    surrounding prose and the arithmetic checks out ($38 + $18 ≈ $55 for one
    iteration, $38 + $54 ≈ $90 for three), but the inputs were never verified.
    """
    window = df.tail(min(card.median_window_days, len(df)))
    if len(window) < 2 * cfg.level_swing_lookback + 1:
        return None, ("not enough history to find swing points",)

    highs, lows = swing_points(window["high"], window["low"], cfg.level_swing_lookback)
    if highs.empty or lows.empty:
        return None, ("no swing points in the window",)

    pivots = sorted(
        [(stamp, float(price), "low") for stamp, price in lows.items()]
        + [(stamp, float(price), "high") for stamp, price in highs.items()],
        key=lambda item: item[0],
    )

    runs: list[float] = []
    open_low: float | None = None
    for _, price, kind in pivots:
        if kind == "low":
            # A lower low before any high replaces the pending one: the run-up
            # measures from the bottom of the leg, not from the first dip into it.
            open_low = price if open_low is None else min(open_low, price)
        elif open_low is not None:
            runs.append(price - open_low)
            open_low = None

    runs = [r for r in runs if r > 0]
    if not runs:
        return None, ("no completed low-to-high runs in the window",)

    biggest = sorted(runs, reverse=True)[: card.run_up_count]
    average = sum(biggest) / len(biggest)
    listed = ", ".join(f"{r:,.2f}" for r in biggest)
    return average, (
        f"{len(runs)} low-to-high runs in the window, largest {len(biggest)}: {listed}",
        f"average run-up {average:,.2f}",
    )


def momentum_target(
    df: pd.DataFrame,
    cfg: Config,
    card: CardConfig,
    close: float,
    direction: GrowthDirection,
) -> PriceTarget:
    """Current price plus the average run-up, times the expected iterations.

    Page 232: "With each iteration equal to 18$ we get 18$ x 3 = 54$. This will
    give us a total price target of around $90." JMIA was at $38.13, so the base
    is the CURRENT PRICE, not the median.

    The iteration count has no rule behind it anywhere in the course, it is the
    reader's judgement about whether growth is merely continuing (1) or
    accelerating (n). Default 1 keeps the card from inheriting somebody else's
    bullishness by accident.
    """
    if not direction.is_positive:
        return PriceTarget(
            None,
            MOMENTUM,
            (
                f"not placed: {direction.describe()}",
                "a run-up projection assumes the growth that caused the run-ups continues",
            ),
        )

    average, basis = average_run_up(df, cfg, card)
    if average is None:
        return PriceTarget(None, MOMENTUM, ("not placed: " + basis[0],))

    iterations = card.run_up_iterations
    price = close + average * iterations
    extra = (
        f"{iterations:g} iteration(s) of growth from {close:,.2f} → target {price:,.2f}",
        "iteration count is a judgement input, the course gives no rule for it",
    )
    return PriceTarget(price, MOMENTUM, basis + extra)


# --- Risk, reward and the stop ---------------------------------------------------


def reward_risk(close: float, target: float | None, support: float | None) -> float | None:
    """(target − price) : (price − support). Pages 21 to 25, restated on page 242.

    Page 242 gives it plainly for the averaging-up case: "If support is at 50
    cents and you took a position at 1$ then at that time you have a 50 cents
    downside... The upside (from price target) in case of 1$ is 9$". So upside
    is measured to the target and downside to the support.

    None when either leg is unknown. A missing ceiling is not an infinite one,
    and treating it as one is how a screen ends up buying tops.
    """
    if target is None or support is None:
        return None
    downside = close - support
    if downside <= 0:
        return None
    return (target - close) / downside


def hard_stop(
    levels: tuple[Level, ...], close: float, card: CardConfig
) -> tuple[float | None, tuple[str, ...]]:
    """A concrete level decided in advance, at a previous support. Page 234.

    "Charlie's take on this is to have a concrete level where you are going to
    sellout regardless of what happens. This must be a concrete level so you
    can't talk yourself out to holding and hoping strategy. This
    risk-management exit-point should be at a previous support level."

    Page 235 allows two supports below when highly bullish, which is the
    `stop_two_supports_below` input.
    """
    below = sorted(
        (lv for lv in levels if lv.kind == SUPPORT and lv.price < close),
        key=lambda lv: lv.price,
        reverse=True,
    )
    if not below:
        return None, ("no qualifying support below price, no concrete stop available",)

    if card.stop_two_supports_below and len(below) >= 2:
        chosen = below[1]
        note = f"second support below, {chosen.price:,.2f} (page 235, highly bullish)"
    else:
        chosen = below[0]
        note = f"previous support at {chosen.price:,.2f} ({chosen.touches} touches, page 234)"
        if card.stop_two_supports_below:
            note += ", only one support below, could not go two down"
    return chosen.price, (note,)


# --- The elevating and deprecating ledger (pages 117 to 132) ---------------------


def build_ledger(
    df: pd.DataFrame,
    cfg: Config,
    close: float,
    support: float | None,
    resistance: float | None,
    volume_ratio: float | None,
    direction: GrowthDirection,
) -> tuple[tuple[Factor, ...], tuple[Factor, ...]]:
    """Every factor this project can read off the data, sorted into two columns.

    Page 44: "Every indicator that is in your favor is an elevating factor."
    Page 131 is the rule for reading the result, and it is emphatically not a
    tally: "Even good trades can have some deprecating factors, but the key is
    they have more elevating factors" alongside "A big elevating factor can
    counter a deprecating factor". So this returns two lists and no score.

    Factors the course names that CANNOT be read from bars are omitted rather
    than guessed: news catalysts (page 133 step 5), analyst consensus position
    (pages 145 to 150), insider buying or selling (pages 160 to 165), share
    offerings (pages 190 to 192) and reverse splits (page 184). Their absence
    from the ledger is not evidence of their absence from the stock, which is
    why the card carries a standing note saying so.
    """
    elevating: list[Factor] = []
    deprecating: list[Factor] = []

    closes = df["close"]
    fast = sma(closes, cfg.sma_fast)
    slow = sma(closes, cfg.sma_slow)
    reading = rsi(closes, cfg.rsi_period)

    fast_now = float(fast.iloc[-1]) if not pd.isna(fast.iloc[-1]) else None
    slow_now = float(slow.iloc[-1]) if not pd.isna(slow.iloc[-1]) else None
    rsi_now = float(reading.iloc[-1]) if not pd.isna(reading.iloc[-1]) else None

    # Gate 4 / directional strength. Page 44: "If we are above the red SMA line,
    # we are in a period of upward direction". Page 129 calls upward direction a
    # big elevating factor explicitly, and the one that can neutralise an
    # overbought RSI.
    if slow_now is not None:
        if close > slow_now:
            elevating.append(
                Factor(
                    f"upward direction: above the {cfg.sma_slow} SMA at {slow_now:,.2f}",
                    ELEVATING,
                    BIG,
                    "44, 129",
                )
            )
        else:
            deprecating.append(
                Factor(
                    f"below the {cfg.sma_slow} SMA at {slow_now:,.2f}, not in an upward direction",
                    DEPRECATING,
                    BIG,
                    "44",
                )
            )

    # Gate 2 / price strength, and the confirmation EVENT rather than the state.
    # Page 116: "the first candlestick holding (OPENING) above the blue SMA
    # line". A state check stays true for the whole run; the event fires once,
    # on the day price crosses. Both are reported because the repo has not yet
    # settled which the screens should use, and pretending otherwise here would
    # hide a known open question.
    if fast_now is not None:
        if close > fast_now:
            elevating.append(
                Factor(
                    f"price strength: above the {cfg.sma_fast} SMA at {fast_now:,.2f}",
                    ELEVATING,
                    NORMAL,
                    "45, 115",
                )
            )
            if len(fast) > 1 and not pd.isna(fast.iloc[-2]):
                previous_close = float(closes.iloc[-2])
                if previous_close <= float(fast.iloc[-2]):
                    elevating.append(
                        Factor(
                            "CONFIRMATION today: first candle holding above the "
                            f"{cfg.sma_fast} SMA",
                            ELEVATING,
                            BIG,
                            "116",
                        )
                    )
        else:
            deprecating.append(
                Factor(
                    f"price back below the {cfg.sma_fast} SMA at {fast_now:,.2f}: "
                    "VALIDATION, re-weigh the factors",
                    DEPRECATING,
                    BIG,
                    "107, 120",
                )
            )

    # Gate 3 / is this a good deal. Pages 51 to 52 and 115: below the middle line
    # is an "okay deal", oversold is a "good deal". Page 138 states 30 outright:
    # "A value of 30 is used as on the RSI we have set 30 as the oversold line".
    # The overbought line is never printed in the course; 70 is the platform
    # default and remains an assumption.
    if rsi_now is not None:
        if rsi_now <= cfg.rsi_oversold:
            elevating.append(
                Factor(f"good deal: RSI {rsi_now:.1f}, oversold", ELEVATING, BIG, "51, 115, 138")
            )
        elif rsi_now < 50:
            elevating.append(
                Factor(f"okay deal: RSI {rsi_now:.1f}, below fair value", ELEVATING, NORMAL, "115")
            )
        elif rsi_now >= cfg.rsi_overbought:
            deprecating.append(
                Factor(
                    f"RSI {rsi_now:.1f}, overbought (the 70 line is an assumption, "
                    "the course never prints it)",
                    DEPRECATING,
                    NORMAL,
                    "118, 129",
                )
            )

    # Gate 1 / more upward potential than downward. Pages 21 to 25.
    if support is not None and resistance is not None:
        up = resistance - close
        down = close - support
        if down > 0 and up > down:
            elevating.append(
                Factor(
                    f"more upward potential ({up:,.2f}) than downward ({down:,.2f})",
                    ELEVATING,
                    NORMAL,
                    "21, 115",
                )
            )
        elif down > 0:
            deprecating.append(
                Factor(
                    f"downward potential ({down:,.2f}) exceeds upward ({up:,.2f})",
                    DEPRECATING,
                    NORMAL,
                    "23, 121",
                )
            )
    elif resistance is None:
        # Not a neutral absence. The session-4 backtest found that names with no
        # resistance above them had their winners run uncapped under a trailing
        # stop, which alone put a signal-free feed at the 96th percentile. Worth
        # flagging on the card as an artefact rather than as good news.
        deprecating.append(
            Factor(
                "no qualifying resistance above, no target ceiling, and no upward "
                "potential to measure",
                DEPRECATING,
                NORMAL,
                "23",
            )
        )

    # Volume. Page 119: "the huge spike of volume. That means a lot of investor
    # interest. If you have a huge spike of volume in a stock, which is in upward
    # direction, it is likely to go up. That is also an elevating factor."
    if volume_ratio is not None and volume_ratio >= 2.0:
        upward = slow_now is not None and close > slow_now
        elevating.append(
            Factor(
                f"volume spike: {volume_ratio:.1f}x average"
                + (", in an upward direction" if upward else ""),
                ELEVATING,
                BIG if upward else NORMAL,
                "119",
            )
        )

    if direction.call == NEGATIVE:
        deprecating.append(
            Factor("growth direction researched as NEGATIVE", DEPRECATING, BIG, "223")
        )
    elif direction.is_positive:
        elevating.append(Factor("growth direction researched as POSITIVE", ELEVATING, BIG, "223"))

    return tuple(elevating), tuple(deprecating)


# --- The plan sentences (page 135) ----------------------------------------------


def entry_plan(
    ticker: str,
    close: float,
    fast_period: int,
    elevating: tuple[Factor, ...],
    target: PriceTarget,
    stop: float | None,
    deprecating: tuple[Factor, ...] = (),
) -> str:
    """The reason for the buy, in the course's own good-plan form.

    Page 135's good and bad examples differ by exactly one thing: the trigger.
    "I notice that this stock is oversold, so I'll buy in because its
    discounted" is a BAD plan; "I am noticing that we are oversold, so I will
    buy in if we have a confirmation of price strength" is a GOOD one. Same
    observation, and the whole difference is "if we have a confirmation".

    Page 135's own summary of what good plans share: "They all involve a
    concrete entry (confirmation) & concrete exit (validation) point." So every
    sentence this builds is observation + confirmation trigger + concrete exit.

    THE LEAD FACTOR IS THE BIGGEST ONE, not the first one found. An earlier
    version took `elevating[0]`, which is whichever factor the ledger happened
    to append first, and on a real card that produced "I am noticing okay deal"
    as the headline reason while a researched positive growth direction sat
    unmentioned two lines below. The sentence is the part that gets read; it
    has to lead with the strongest thing said.

    BIG DEPRECATING FACTORS GET NAMED IN THE SENTENCE. Page 135's good plans do
    not mention them, but page 133's step 7 is "Is the Position WORTH IT? Do not
    trade a setup that doesn't make sense based on your elevating and
    deprecating factors." A plan sentence that reads as unqualified enthusiasm
    while the ledger carries two big negatives is not a summary of the card, it
    is a misrepresentation of it.
    """
    ranked = sorted(elevating, key=lambda f: f.weight != BIG)
    if ranked:
        best = ranked[0].text
        lead = best.split(":")[0] if ":" in best else best
        observation = f"I am noticing {lead} on {ticker} at {close:,.2f}"
    else:
        observation = f"{ticker} at {close:,.2f} has nothing in its favour I can measure"

    trigger = f"so I will buy in only on a confirmation candle holding above the {fast_period} SMA"

    big_against = [f.text.split(":")[0] for f in deprecating if f.weight == BIG]
    caveat = f" Against it: {', '.join(big_against)}." if big_against else ""

    if target.price is not None and stop is not None:
        close_out = f"targeting {target.price:,.2f} and out at {stop:,.2f} regardless"
    elif stop is not None:
        close_out = f"out at {stop:,.2f} regardless, with no target set until the research is done"
    elif target.price is not None:
        close_out = f"targeting {target.price:,.2f}, with NO concrete stop available"
    else:
        close_out = "with neither a target nor a concrete stop, which is not a tradeable plan"

    return f"{observation}, {trigger}, {close_out}.{caveat}"


def exit_plan(fast_period: int, stop: float | None, target: PriceTarget, card: CardConfig) -> str:
    """Validation, the hard stop, and the trailing stop after the target.

    Page 107 is the one that keeps this honest: VALIDATION is explicitly "not a
    concrete exit point", it is the moment you re-weigh elevating against
    deprecating factors. So the sentence says re-weigh, never sell.
    """
    parts = [
        f"a candle opening below the {fast_period} SMA is VALIDATION, re-weigh the "
        "factors, it is not an automatic sell (page 107)"
    ]
    if stop is not None:
        parts.append(
            f"hard stop at {stop:,.2f}, decided now so it cannot be argued away (page 234)"
        )
    if target.price is not None:
        parts.append(
            f"if {target.price:,.2f} is reached, switch to a {card.trail_pct:g}% trailing "
            "stop (pages 237 to 238)"
        )
    return "; ".join(parts) + "."


def position_plan(close: float, stop: float | None, card: CardConfig) -> PositionPlan:
    """20% of the account, at most, and what that costs if the stop is hit.

    Page 40: "Limit your Capital used in a trade to maximum of 20% of your
    account. 20% is also pushing it." The wording is a ceiling being grumbled
    about, so the card reports the cap and the loss it implies rather than
    recommending a size.
    """
    risk_per_share = (close - stop) if stop is not None and stop < close else None

    if card.account_size is None or card.account_size <= 0:
        return PositionPlan(
            None,
            None,
            None,
            risk_per_share,
            None,
            "set account_size to see the 20% cap and the money at risk",
        )

    cap_value = card.account_size * card.max_position_pct / 100.0
    shares = int(cap_value // close) if close > 0 else 0
    max_loss = shares * risk_per_share if risk_per_share is not None else None
    note = f"{card.max_position_pct:g}% cap (page 40); size DOWN from here, never up"
    return PositionPlan(card.account_size, cap_value, shares, risk_per_share, max_loss, note)


# --- Assembly --------------------------------------------------------------------


def build_card(
    ticker: str,
    df: pd.DataFrame,
    cfg: Config,
    card: CardConfig | None = None,
    direction: GrowthDirection | None = None,
    volume_ratio: float | None = None,
    balance: object | None = None,
) -> OpportunityCard:
    """Everything above, in the order the 7-Step Test runs (page 133).

    The step order is not cosmetic. Risk versus reward is step 2, before the
    factors are even looked at, because page 23's reject case ("the stock has no
    upward potential with a downward potential of 2 dollars... it won't make
    sense to take a position here") throws the setup out before any of the
    elevating factors get a chance to be persuasive.
    """
    card = card or CardConfig()
    direction = direction or GrowthDirection()
    as_of = df.index[-1].date() if len(df) else date.today()
    close = float(df["close"].iloc[-1])

    median, median_basis = median_anchor(df, card)
    play = classify_play(close, median)

    levels = classify_levels(find_levels(df, cfg), df, cfg)
    supports = [lv.price for lv in levels if lv.kind == SUPPORT and lv.price < close]
    resistances = [lv.price for lv in levels if lv.kind == RESISTANCE and lv.price > close]
    support = max(supports) if supports else None
    resistance = min(resistances) if resistances else None

    stop, stop_basis = hard_stop(levels, close, card)

    primary = (
        momentum_target(df, cfg, card, close, direction)
        if play == MOMENTUM
        else discounted_target(levels, median, close, direction)
    )
    alternate = (
        discounted_target(levels, median, close, direction)
        if play == MOMENTUM
        else momentum_target(df, cfg, card, close, direction)
    )

    ratio = reward_risk(close, primary.price, support)
    elevating, deprecating = build_ledger(
        df, cfg, close, support, resistance, volume_ratio, direction
    )

    warnings: list[str] = list(stop_basis)

    # THE SESSION-4 FINDING. This is the card's single most important line and
    # the only place it overrides the course. See the module docstring.
    if (
        stop is not None
        and support is not None
        and abs(stop - support) < 1e-9
        and ratio is not None
    ):
        warnings.append(
            f"STOP SITS ON THE SUPPORT THAT EARNED THE {ratio:.1f}:1 RATIO. This project's "
            "own backtest measured that combination stopping out 77% of trades against a "
            "57% control, and it moved the same screen from the 96th percentile to the "
            "10th. The tighter the ratio makes the floor look, the more certain that "
            "floor is inside the noise. Widen the stop or size down."
        )

    if direction.call == UNKNOWN:
        warnings.append(
            "No growth direction researched. Page 233 calls this the most important step "
            "of the three, so this card is chart geometry with the thesis missing."
        )

    warnings.append(
        "Not represented here: news catalysts, analyst consensus, insider activity, share "
        "offerings and splits. The course counts all of them (pages 133, 145-150, 160-165, "
        "184, 190-192) and none is readable from price bars."
    )

    return OpportunityCard(
        ticker=ticker,
        as_of=as_of,
        close=close,
        median=median,
        median_basis=median_basis,
        play_type=play,
        direction=direction,
        target=primary,
        alternate_target=alternate,
        support=support,
        resistance=resistance,
        hard_stop=stop,
        reward_risk=ratio,
        elevating=elevating,
        deprecating=deprecating,
        entry_plan=entry_plan(ticker, close, cfg.sma_fast, elevating, primary, stop, deprecating),
        exit_plan=exit_plan(cfg.sma_fast, stop, primary, card),
        position=position_plan(close, stop, card),
        warnings=tuple(warnings),
        balance=balance,
    )
