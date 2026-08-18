"""Where the stop goes, and how many shares that allows.

THE PROBLEM THIS EXISTS TO SOLVE IS ALREADY MEASURED IN THIS REPO.

Section E of `Trading Strategy & Screens.md` records the finding: gate 1 (page
115) asks for at least twice as much room up as down, and page 234 says put the
hard stop at the previous support level. A 2:1 ratio means support is close, so
the stop lands inside ordinary daily noise. Same screen, same names, same dates:
**96th percentile held to the horizon, 10th percentile with the course's own
stop.** 77% of trades stopped out against a 57% control. Only the exit differed.

That is not a coding bug. It is two rules that are each sensible alone and
impossible together, and no amount of care inside the screen fixes it. The stop
has to stop being derived from the level that earned the ratio.

`Profit & Loss ZTU 2022.xlsx` says the same thing from the other direction. Four
real trades: three winners closed the same day, one loser held for 34 and down
34%. The win rate was 75% and the net was 2,651, because one position gave back
54% of the gains. Neither better entries nor a better ranking touches that.

THE FOUR STOP RULES, AND WHY THERE ARE FOUR.

    support     the course's own rule, page 234, the previous support level.
                Kept because it is the rulebook's and because the comparison is
                the whole point. Known to fail.
    atr         entry minus a multiple of average true range. Places the stop
                outside the name's own daily noise BY CONSTRUCTION, which is
                exactly what the support rule fails to do.
    wider       two support levels below, which is the course's own alternative
                on page 234 "if highly bullish on the name".
    percent     a flat percentage. The naive version, included so the others
                have something unflattering to beat.

Nothing here decides which is right. `scripts/backtest_exits.py` does, on a
pre-registered test, and it is the only place that number gets to matter.

SIZING, AND THE ONE NUMBER THE COURSE DOES NOT GIVE.

Page 39 to 41 caps a position at 20% of the account. That is a CONCENTRATION
limit and it says nothing about risk, because 20% of the account behind a stop
2% away and 20% behind a stop 30% away are wildly different bets.

The course never states a risk-per-trade rule. `max_risk_pct` is therefore an
addition, not a transcription, and it is flagged as such in every output. The
1% default is the conventional figure rather than a measured one.

Both limits are computed and the SMALLER binds, which is the useful part: which
one bound tells you something. If the cap binds, the stop is tight and the
trade is cheap. If the risk budget binds, the stop is wide and a full-sized
position would have risked more than the account should lose on one idea.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.indicators import true_range


@dataclass(frozen=True)
class TradePlan:
    """One position, sized and stopped, with the reasoning attached.

    `shares` of zero is a real answer and not an error: it means no size clears
    both limits, which happens when the stop is so wide that even one share
    risks more than the budget allows.
    """

    ticker: str
    entry: float
    stop: float | None
    target: float | None
    shares: int
    stop_basis: str
    binding_limit: str
    account: float
    risk_amount: float
    position_value: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def stop_distance_pct(self) -> float | None:
        if self.stop is None or self.entry <= 0:
            return None
        return 100.0 * (self.entry - self.stop) / self.entry

    @property
    def reward_risk(self) -> float | None:
        """Target over stop, in R. None if either end is unknown."""
        if self.stop is None or self.target is None:
            return None
        risk = self.entry - self.stop
        if risk <= 0:
            return None
        return (self.target - self.entry) / risk

    @property
    def account_pct(self) -> float:
        if self.account <= 0:
            return 0.0
        return 100.0 * self.position_value / self.account


def atr(df: pd.DataFrame, period: int) -> float | None:
    """Average true range over the last `period` bars.

    True range rather than the close-to-close range, because a gap through the
    prior close is real movement the position would have lived through, and a
    stop that ignores gaps is a stop that has not been tested by the name's
    actual behaviour.
    """
    if len(df) < period + 1:
        return None
    value = float(true_range(df).tail(period).mean())
    return value if math.isfinite(value) and value > 0 else None


def place_stop(
    df: pd.DataFrame,
    entry: float,
    cfg: Config = DEFAULT_CONFIG,
    support: float | None = None,
    second_support: float | None = None,
) -> tuple[float | None, str, tuple[str, ...]]:
    """Where the stop goes under `cfg.stop_rule`, and why.

    Returns (stop, basis, reasons). A stop of None means the rule cannot be
    applied on this name, which for the support rules is common: 92% of setups
    in this project have no three-touch level below. Abstaining is correct
    there. Inventing a level is not.
    """
    reasons: list[str] = []
    rule = cfg.stop_rule

    if rule == "support":
        if support is None:
            return None, "support", ("no three-touch support below, so no stop",)
        reasons.append(f"previous support at {support:.2f}, page 234")
        return support, "support", tuple(reasons)

    if rule == "wider":
        level = second_support if second_support is not None else support
        if level is None:
            return None, "wider", ("no second support level below",)
        which = "second" if second_support is not None else "only"
        reasons.append(f"{which} support level below at {level:.2f}, page 234")
        return level, "wider", tuple(reasons)

    if rule == "percent":
        stop = entry * (1 - cfg.stop_percent / 100.0)
        return stop, "percent", (f"flat {cfg.stop_percent:.1f}% below entry",)

    # Default and recommended: outside the name's own noise by construction.
    value = atr(df, cfg.atr_period)
    if value is None:
        return None, "atr", (f"not enough history for a {cfg.atr_period}-bar ATR",)
    stop = entry - cfg.atr_stop_multiple * value
    reasons.append(
        f"{cfg.atr_stop_multiple:.1f}x the {cfg.atr_period}-bar ATR of {value:.2f}, "
        f"so {100 * (entry - stop) / entry:.1f}% below entry"
    )
    if support is not None and stop > support:
        # Worth saying out loud rather than silently overriding. The course puts
        # the stop at support; an ATR stop above it is a deliberate departure,
        # and the reader should see that it happened.
        reasons.append(
            f"note: this sits ABOVE the three-touch support at {support:.2f}, "
            f"so it is tighter than the rulebook's own stop"
        )
    return stop, "atr", tuple(reasons)


def size_position(
    entry: float,
    stop: float | None,
    account: float,
    cfg: Config = DEFAULT_CONFIG,
) -> tuple[int, str, tuple[str, ...]]:
    """Shares, which limit bound, and the arithmetic.

    Two ceilings, and the smaller wins:

        concentration   the course's 20% of account, pages 39 to 41
        risk            `max_risk_pct` of account divided by the stop distance,
                        which is NOT in the course and is flagged as such

    Fractional shares are floored, never rounded, because rounding up quietly
    breaches whichever limit was binding.
    """
    if entry <= 0 or account <= 0:
        return 0, "none", ("no entry price or no account",)

    cap_value = account * cfg.max_position_pct / 100.0
    by_cap = int(cap_value // entry)

    if stop is None or stop >= entry:
        return (
            by_cap,
            "concentration",
            (
                f"no usable stop, so only the {cfg.max_position_pct:.0f}% cap applies: "
                f"{by_cap} shares. Size this by hand.",
            ),
        )

    risk_per_share = entry - stop
    risk_budget = account * cfg.max_risk_pct / 100.0
    by_risk = int(risk_budget // risk_per_share)

    shares = min(by_cap, by_risk)
    binding = "concentration" if by_cap <= by_risk else "risk"
    reasons = (
        f"{cfg.max_position_pct:.0f}% cap allows {by_cap} shares (pages 39 to 41)",
        f"{cfg.max_risk_pct:.1f}% risk budget of {risk_budget:,.0f} over a "
        f"{risk_per_share:.2f} stop allows {by_risk} shares",
        f"the {binding} limit binds, so {shares} shares",
    )
    return shares, binding, reasons


def build_plan(
    ticker: str,
    df: pd.DataFrame,
    entry: float,
    account: float,
    cfg: Config = DEFAULT_CONFIG,
    support: float | None = None,
    second_support: float | None = None,
    target: float | None = None,
) -> TradePlan:
    """The whole of layers 4 and 5's entry side, for one name.

    Pure, like the screens: no I/O, no network. The caller supplies the levels
    and the target because deciding those is not this module's job.
    """
    stop, basis, stop_reasons = place_stop(df, entry, cfg, support, second_support)
    shares, binding, size_reasons = size_position(entry, stop, account, cfg)

    warnings: list[str] = []
    if stop is not None and support is not None and abs(stop - support) / entry < 0.005:
        warnings.append(
            "THE STOP SITS ON THE SUPPORT THAT EARNED THE RATIO. This project's own "
            "backtest measured that combination stopping out 77% of trades against a "
            "57% control, and it moved the same screen from the 96th percentile to the "
            "10th. Widen the stop or size down."
        )
    if shares == 0 and stop is not None:
        warnings.append(
            "No size clears both limits. The stop is wide enough that even one share "
            "risks more than the budget allows, which is the honest answer rather than "
            "a reason to move the stop."
        )
    if stop is not None:
        distance = 100.0 * (entry - stop) / entry
        atr_value = atr(df, cfg.atr_period)
        if atr_value and (entry - stop) < atr_value:
            warnings.append(
                f"The stop is {distance:.1f}% away, which is less than one average "
                f"true range ({100 * atr_value / entry:.1f}%). This name moves that far "
                f"on an ordinary day, so the stop is inside the noise."
            )

    return TradePlan(
        ticker=ticker,
        entry=entry,
        stop=stop,
        target=target,
        shares=shares,
        stop_basis=basis,
        binding_limit=binding,
        account=account,
        risk_amount=0.0 if stop is None else shares * (entry - stop),
        position_value=shares * entry,
        reasons=stop_reasons + size_reasons,
        warnings=tuple(warnings),
    )


def to_dict(plan: TradePlan) -> dict:
    return {
        "ticker": plan.ticker,
        "entry": round(plan.entry, 4),
        "stop": None if plan.stop is None else round(plan.stop, 4),
        "target": None if plan.target is None else round(plan.target, 4),
        "shares": plan.shares,
        "stop_basis": plan.stop_basis,
        "binding_limit": plan.binding_limit,
        "stop_distance_pct": None
        if plan.stop_distance_pct is None
        else round(plan.stop_distance_pct, 2),
        "reward_risk": None if plan.reward_risk is None else round(plan.reward_risk, 2),
        "risk_amount": round(plan.risk_amount, 2),
        "position_value": round(plan.position_value, 2),
        "account_pct": round(plan.account_pct, 2),
        "reasons": list(plan.reasons),
        "warnings": list(plan.warnings),
    }
