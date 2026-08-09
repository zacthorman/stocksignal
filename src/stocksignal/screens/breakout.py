"""Screen 3: the breakout, the hardest and highest-value screen in the rulebook.

From the rulebook, verbatim:
  * The best breakouts show a dip and reject first: it breaks out, dips, the
    dip gets rejected, and it continues up.
  * The igniting bar must be big, and bigger than the baby bar before it.
  * Massive wicks on the baby bar disqualify it.
  * After a struggle period, a break above the moving averages counts only if
    the follow-through is strong, and a red second candle means it is still
    being beaten down rather than a play.
  * Ask whether it has broken the resistance from the previous run-up, and
    whether the ignition bar is strong.

Five conditions, four of them hard gates and one a bonus:
  1. A three-touch resistance level, broken in the last few sessions (hard).
     This reuses `levels.py` for the level itself, then checks separately
     whether and when it was crossed, so a level that was never broken and one
     that broke too long ago fail with different reasons.
  2. A volume spike on the breaking bar against the average before it (hard).
  3. The ignition bar test: the breaking bar's body must be bigger than the
     baby bar's, and big in absolute terms (hard, two sub-checks).
  4. The wick disqualifier on the baby bar (hard).
  5. Follow-through: a red second candle fails it. Skipped, not failed, if the
     breakout happened on the most recent bar and there is no second bar yet.

The dip-and-reject pattern is checked last and only adds to the score, never
gates it, because the rulebook itself says the pattern "does not always
appear".

Score is a weighted sum of three continuous readings, each normalised 0 to 1
the same way `trend.py` normalises its SMA gap: 0 at the pass/fail floor, 1.0
at a "strong" ceiling from `Config`. A very strong ignition bar can offset a
merely adequate volume spike, because both have already cleared their own
hard minimum by the time the score runs:

    score = w_breakout_volume * volume_strength
            + w_breakout_ignition * ignition_strength
            + w_breakout_recency * level.recency
    score += breakout_dip_reject_bonus if the dip-and-reject pattern confirms
"""

from __future__ import annotations

import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import average_volume, body_and_wick
from stocksignal.levels import SUPPORT, Level, classify_levels, find_levels
from stocksignal.models import Quote, ScreenResult

NAME = "breakout"


def screen_breakout(df: pd.DataFrame, quote: Quote, cfg: Config) -> ScreenResult:
    level, breaking_pos, failure_reason = _find_breakout(df, cfg)
    if level is None or breaking_pos is None:
        return ScreenResult(name=NAME, passed=False, reasons=(failure_reason,))

    baby = df.iloc[breaking_pos - 1]
    ignition = df.iloc[breaking_pos]
    follow = df.iloc[breaking_pos + 1] if breaking_pos + 1 < len(df) else None

    ignition_body, _ = body_and_wick(ignition)
    baby_body, baby_wick = body_and_wick(baby)

    avg_vol_before = average_volume(df["volume"].iloc[:breaking_pos], cfg.avg_volume_window)
    volume_ratio = float(ignition["volume"]) / avg_vol_before if avg_vol_before > 0 else 0.0

    failures: list[str] = []
    passes: list[str] = []

    if volume_ratio >= cfg.breakout_volume_spike_min:
        passes.append(
            f"breaking bar volume is {volume_ratio:.2f}x the recent average, "
            f"clearing the {cfg.breakout_volume_spike_min:.2f}x floor"
        )
    else:
        failures.append(
            f"breaking bar volume is only {volume_ratio:.2f}x the recent average, "
            f"below the {cfg.breakout_volume_spike_min:.2f}x spike floor"
        )

    if ignition_body <= baby_body:
        failures.append(
            f"igniting bar body {ignition_body:.2f} is not bigger than the baby "
            f"bar's body {baby_body:.2f}"
        )
    else:
        passes.append(
            f"igniting bar body {ignition_body:.2f} is bigger than the baby "
            f"bar's body {baby_body:.2f}"
        )

    ignition_body_pct = ignition_body / float(ignition["close"]) * 100.0
    if ignition_body_pct < cfg.breakout_ignition_min_body_pct:
        failures.append(
            f"igniting bar body is {ignition_body_pct:.2f}% of its close, under "
            f"the {cfg.breakout_ignition_min_body_pct:.2f}% floor for a big bar"
        )
    else:
        passes.append(
            f"igniting bar body is {ignition_body_pct:.2f}% of its close, "
            f"clearing the {cfg.breakout_ignition_min_body_pct:.2f}% floor"
        )

    baby_range = baby_body + baby_wick
    baby_wick_pct = (baby_wick / baby_range * 100.0) if baby_range > 0 else 0.0
    if baby_wick_pct > cfg.breakout_baby_max_wick_pct:
        failures.append(
            f"baby bar wick is {baby_wick_pct:.1f}% of its range, above the "
            f"{cfg.breakout_baby_max_wick_pct:.1f}% disqualifier"
        )
    else:
        passes.append(
            f"baby bar wick is {baby_wick_pct:.1f}% of its range, under the "
            f"{cfg.breakout_baby_max_wick_pct:.1f}% disqualifier"
        )

    if follow is None:
        passes.append("no follow-through bar yet, breakout is too recent to judge")
    elif float(follow["close"]) < float(follow["open"]):
        failures.append(
            f"follow-through candle closed red ({float(follow['close']):.2f} under "
            f"{float(follow['open']):.2f} open), still being beaten down"
        )
    else:
        passes.append(
            f"follow-through candle held at or above its open "
            f"({float(follow['close']):.2f} vs {float(follow['open']):.2f})"
        )

    if failures:
        return ScreenResult(name=NAME, passed=False, score=0.0, reasons=tuple(failures))

    volume_strength = _normalise(
        volume_ratio, cfg.breakout_volume_spike_min, cfg.breakout_volume_spike_strong
    )
    ignition_ratio = (
        ignition_body / baby_body if baby_body > 0 else cfg.breakout_ignition_strong_ratio
    )
    ignition_strength = _normalise(ignition_ratio, 1.0, cfg.breakout_ignition_strong_ratio)

    score = (
        cfg.w_breakout_volume * volume_strength
        + cfg.w_breakout_ignition * ignition_strength
        + cfg.w_breakout_recency * level.recency
    )

    if _dip_and_reject(df, level.price, breaking_pos, cfg):
        score += cfg.breakout_dip_reject_bonus
        passes.append(
            f"price dipped back to the {level.price:.2f} level and got rejected "
            "before continuing, the rulebook's preferred pattern"
        )

    passes.append(f"broke the previous resistance, now {level.describe()}")

    return ScreenResult(name=NAME, passed=True, score=round(score, 4), reasons=tuple(passes))


def _find_breakout(df: pd.DataFrame, cfg: Config) -> tuple[Level | None, int | None, str | None]:
    """The nearest broken resistance below today's close, and the bar that broke it.

    A level only qualifies as "resistance from the previous run-up" if price
    was genuinely below it at some point in the recorded history. A level
    that has sat at or above price for the whole history was a floor from the
    start, never a ceiling, whatever its current `kind` reads as: `kind` is
    derived from today's close alone, so a level three-touch support has held
    since day one still comes out "support" with nothing to tell it apart
    from one that used to be resistance and broke. Filtering on genuine past
    resistance here, rather than tightening the crossing comparison in
    `_find_breaking_bar`, keeps a baby bar that closes exactly at the level
    before the ignition bar clears it counting as a real break, which it is.

    Picks the highest-priced qualifying level, because that is the resistance
    from the most recent run-up rather than some older ceiling far below
    price. On failure, the third element explains which of three different
    situations this is: no such level exists, it exists but has never been
    broken, or it broke too long ago to count. Those are different facts
    about the chart and the digest should say which one.
    """
    levels = classify_levels(find_levels(df, cfg), df, cfg)
    # Not redundant with `lv.kind`: kind == RESISTANCE already implies this
    # filter is true (today's own close is below the level, so `.any()` holds
    # trivially), so the two can only ever diverge on kind == SUPPORT. That
    # divergence is a level that has sat at or above price for its whole
    # history, a floor from day one, which kind cannot detect because it only
    # looks at today's close.
    resistance_candidates = [lv for lv in levels if (df["close"] < lv.price).any()]
    if not resistance_candidates:
        return None, None, "no three-touch resistance level found in the recent swing history"

    level = max(resistance_candidates, key=lambda lv: lv.price)
    if level.kind != SUPPORT:
        return None, None, f"the {level.price:.2f} resistance has never been broken to the upside"

    pos = _find_breaking_bar(df, level.price, cfg.level_break_lookback)
    if pos is not None:
        return level, pos, None

    # It broke at some point, since it is support now and used to be below
    # price, just not recently enough for the window above to find it.
    stale_pos = _find_breaking_bar(df, level.price, lookback=len(df) - 1)
    if stale_pos is None:
        return None, None, f"the {level.price:.2f} resistance has never been broken to the upside"

    sessions_ago = len(df) - 1 - stale_pos
    return (
        None,
        None,
        f"the {level.price:.2f} resistance broke {sessions_ago} sessions ago, outside the "
        f"{cfg.level_break_lookback}-session window, too old to act on",
    )


def _find_breaking_bar(df: pd.DataFrame, level_price: float, lookback: int) -> int | None:
    """The first bar in the lookback window whose close crosses above `level_price`."""
    back = min(lookback, len(df) - 1)
    start = len(df) - 1 - back
    closes = df["close"]
    for pos in range(start + 1, len(df)):
        if closes.iloc[pos - 1] <= level_price < closes.iloc[pos]:
            return pos
    return None


def _normalise(value: float, floor: float, ceiling: float) -> float:
    """0 at `floor`, 1.0 at `ceiling` and beyond. Mirrors trend.py's gap strength."""
    if ceiling <= floor:
        return 0.0
    return min(max((value - floor) / (ceiling - floor), 0.0), 1.0)


def _dip_and_reject(df: pd.DataFrame, level_price: float, breaking_pos: int, cfg: Config) -> bool:
    """Did price pull back to the level and then close back above it?

    Bonus only. The rulebook is explicit that the pattern "does not always
    appear", so a breakout with no pullback yet must not be disqualified here.
    """
    touch_ceiling = level_price * (1 + cfg.breakout_dip_tolerance_pct / 100.0)
    touched = False
    for pos in range(breaking_pos + 1, len(df)):
        row = df.iloc[pos]
        if not touched and float(row["low"]) <= touch_ceiling:
            touched = True
        if touched and float(row["close"]) > level_price:
            return True
    return False
