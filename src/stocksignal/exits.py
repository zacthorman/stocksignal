"""The exit rules, as a state machine, because that is what they are.

WHY THIS IS THE PIECE THAT MATTERS. Two independent pieces of evidence in this
project point at exits rather than entries, and nothing else in the repo
addresses either.

The backtest: gate 1 at 2:1 plus the course's own stop stopped out 77% of trades
against a 57% control, and moved the same screen from the 96th percentile to the
10th. Only the exit differed.

The trade log: three winners closed the same day, one loser held 34 days that
gave back 54% of the gains. A 75% win rate netted 2,651.

THE THREE RULES, KEPT DISTINCT ON PURPOSE.

1. VALIDATION, pages 107 and 120. The first candlestick OPENING below the blue
   9 SMA. Page 107 is explicit that this is **not a concrete exit point**: it is
   the moment you re-weigh the elevating against the deprecating factors and
   decide. So it raises an alert and never sells. Collapsing it into a sell
   would be the single easiest way to get this module wrong, and it is why
   `ExitEvent` has a `is_instruction` flag rather than everything being a sell.

2. THE HARD STOP, page 234. A concrete price decided in advance so it cannot be
   argued away later. Where it goes is `position.py`'s problem, not this one.
   This module only enforces it.

3. THE TRAILING STOP, pages 237 and 238. **Five per cent, and only AFTER the
   price target is hit.** The reasoning in the course matters for the
   implementation: a stop left down at support would erase gains already made,
   so once the target is reached the protection moves up behind the price. It
   is not a trailing stop from entry, and implementing it as one would change
   the strategy rather than the code.

INTRABAR ORDERING IS A REAL DECISION, NOT AN IMPLEMENTATION DETAIL. On a bar
that touches both the target and the stop, daily data cannot say which came
first. This module assumes the STOP hit first. That is the pessimistic reading,
and it is the right one: the optimistic assumption manufactures winners out of
ambiguity, and every backtest that flatters itself does so with a choice like
this one made quietly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from stocksignal.config import DEFAULT_CONFIG, Config
from stocksignal.indicators import sma

HOLDING = "holding"
TRAILING = "trailing"
CLOSED = "closed"


@dataclass(frozen=True)
class ExitEvent:
    """Something that happened, and whether it is an instruction or a prompt."""

    when: date
    kind: str
    price: float
    message: str
    is_instruction: bool
    """True only for the two rules that actually close a position. VALIDATION is
    False, because page 107 says it is a moment to re-weigh rather than a sell,
    and the project committed to raising it as an alert and never as an order."""


@dataclass
class Position:
    """One open position, walked forward bar by bar.

    Mutable, unlike everything else in this repo, because it is a state machine
    and pretending otherwise would mean rebuilding it on every bar.
    """

    ticker: str
    entry: float
    stop: float
    target: float | None = None
    shares: int = 0
    state: str = HOLDING
    peak: float = 0.0
    exit_price: float | None = None
    exit_reason: str | None = None
    events: list[ExitEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.peak <= 0:
            self.peak = self.entry

    @property
    def is_open(self) -> bool:
        return self.state != CLOSED

    def step(self, when: date, bar: pd.Series, fast_sma: float | None, cfg: Config) -> None:
        """Advance one bar. Order of checks is the strategy, so it is explicit.

        Stop before target, for the intrabar reason in the module docstring.
        VALIDATION last, because it never closes anything and would otherwise
        clutter the record of a bar that already resolved.
        """
        if self.state == CLOSED:
            return

        low = float(bar["low"])
        high = float(bar["high"])
        open_ = float(bar["open"])

        # 1. The hard stop, and a gap through it fills at the open, not at the
        #    stop price. Assuming the stop price would be a fill nobody gets.
        if low <= self.stop:
            fill = min(open_, self.stop) if open_ < self.stop else self.stop
            self._close(when, fill, "STOP", f"stop at {self.stop:.2f} hit, filled {fill:.2f}")
            return

        # 2. The target, which switches on the trailing stop rather than selling.
        if self.state == HOLDING and self.target is not None and high >= self.target:
            self.state = TRAILING
            self.peak = high
            self.stop = self.peak * (1 - cfg.trail_pct / 100.0)
            self.events.append(
                ExitEvent(
                    when,
                    "TARGET",
                    self.target,
                    f"target {self.target:.2f} reached, switching to a "
                    f"{cfg.trail_pct:.0f}% trailing stop at {self.stop:.2f} "
                    f"(pages 237 to 238)",
                    is_instruction=False,
                )
            )
            return

        # 3. Ratchet the trail upward. It only ever rises.
        if self.state == TRAILING and high > self.peak:
            self.peak = high
            self.stop = max(self.stop, self.peak * (1 - cfg.trail_pct / 100.0))

        # 4. VALIDATION. An alert, never an order.
        if fast_sma is not None and open_ < fast_sma:
            self.events.append(
                ExitEvent(
                    when,
                    "VALIDATION",
                    open_,
                    f"candle OPENED below the {cfg.sma_fast} SMA at {fast_sma:.2f}. "
                    f"Page 107 calls this validation, not a sell: re-weigh the "
                    f"elevating against the deprecating factors and decide.",
                    is_instruction=False,
                )
            )

    def _close(self, when: date, price: float, kind: str, message: str) -> None:
        self.state = CLOSED
        self.exit_price = price
        self.exit_reason = kind
        self.events.append(ExitEvent(when, kind, price, message, is_instruction=True))

    @property
    def pnl_pct(self) -> float | None:
        if self.exit_price is None or self.entry <= 0:
            return None
        return 100.0 * (self.exit_price - self.entry) / self.entry


def walk(
    df: pd.DataFrame,
    position: Position,
    cfg: Config = DEFAULT_CONFIG,
    max_bars: int | None = None,
) -> Position:
    """Run a position forward over the bars in `df`, which must start after entry.

    Returns the same position, mutated. Stops early once closed, so a caller can
    read `exit_price` and `exit_reason` without checking how far it got.
    """
    fast = sma(df["close"], cfg.sma_fast)
    for i, (stamp, bar) in enumerate(df.iterrows()):
        if max_bars is not None and i >= max_bars:
            break
        value = float(fast.iloc[i]) if i < len(fast) else float("nan")
        position.step(
            stamp.date() if hasattr(stamp, "date") else stamp,
            bar,
            None if value != value else value,
            cfg,
        )
        if not position.is_open:
            break
    return position


def open_alerts(
    df: pd.DataFrame,
    position: Position,
    cfg: Config = DEFAULT_CONFIG,
) -> tuple[ExitEvent, ...]:
    """What today's bar says about a position you are already holding.

    This is the daily job: the user tells the bot what he holds, the bot reads
    the newest bar and says whether anything fired. Selling stays his click,
    which was the commitment in the project overview and is not renegotiated
    here.
    """
    if len(df) < 1:
        return ()
    fast = sma(df["close"], cfg.sma_fast)
    value = float(fast.iloc[-1])
    before = len(position.events)
    stamp = df.index[-1]
    position.step(
        stamp.date() if hasattr(stamp, "date") else stamp,
        df.iloc[-1],
        None if value != value else value,
        cfg,
    )
    return tuple(position.events[before:])
