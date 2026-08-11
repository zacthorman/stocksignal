"""Screen 3: the breakout. Rebuilt after an audit against the course transcript.

WHAT THIS SCREEN USED TO DO, AND WHY IT WAS WRONG. The first version gated on an
ignition bar being big, a "baby bar" before it being smaller, and that baby
bar's wick being under 60% of its range. It scored a post-breakout retest as a
small bonus. Three separate mistakes, all in the same direction.

  1.  IT CITED THE WRONG CHAPTER. The ignition and baby bar material is the
      3-bar setup on pages 77 to 81. Pages 72 to 76, which this screen claimed
      to implement, contain no ignition bar, no baby bar, no wick rule and no
      volume rule at all.
  2.  IT INVERTED THE BABY BAR. Page 77: "we get an uptrend then with the
      IGNITE, then we test this direction change using the BABY and then we
      have the CONFIRMATION using the 3rd bar." The baby bar comes AFTER the
      ignition bar and tests it. This screen compared the breaking bar to the
      bar before it, which is a different comparison the course never makes. A
      docstring here quoted the rulebook as saying "bigger than the baby bar
      BEFORE IT"; those last two words appear in no source document.
  3.  IT GATED ON AN ELEVATING FACTOR AND GARNISHED THE ACTUAL RULE. Page 79 is
      explicit that the 3-bar setup "is just another elevating factor in our
      favor". Meanwhile page 75 says "if you want to trade a quality breakout,
      WAIT UNTIL A PUSH BACK and start showing price strength again", page 76
      says "this reassurance is key", and the chapter's takeaway box lists two
      items, both of them the retest. The retest is the rule. The 3-bar setup
      is the bonus. This screen had them precisely the wrong way round, and
      justified it with a rulebook quote ("does not always appear") that does
      not exist.

WHAT IT DOES NOW, following pages 72 to 81 as written.

GATES, all required:
  1. A three-touch resistance level, broken within the recent window. From the
     support and resistance chapter, which was always sound.
  2. THE RETEST HELD. Price pulled back towards the broken level and closed
     back above it. "Reassurance is key."
  3. A healthy uptrend around it. Page 75 opens the quality section with "first
     you need to see if the breakout is part of a healthy uptrend".

DEPRECATING FACTOR, a score penalty and not a gate:
  * An overbought entry. Pages 72 to 74 treat an extreme RSI at the breakout as
    a reason to prefer a different entry, not as a disqualification, and the
    worked example calls such a breakout "still better than the first one".

ELEVATING FACTORS, scored:
  * The 3-bar setup: ignite, then one or two baby bars testing it, then
    confirmation. Page 81 notes the 4-bar variant with two baby bars "could be
    even slightly better", so both count.
  * The fat baby disqualifier, page 80, applies to THIS FACTOR ONLY and is
    positional, not a percentage: "when the WICK passed below the IGNITION bar".
    A baby that gives back the whole ignition move failed its test. The old 60%
    of range threshold was invented and measured something else.
  * A volume spike on the breaking bar. The course calls a volume spike "a lot
    of investor interest" and an elevating factor; it never makes it a gate.
  * How fresh the broken level is.
"""

from __future__ import annotations

import pandas as pd

from stocksignal.config import Config
from stocksignal.indicators import average_volume, body_and_wick, rsi
from stocksignal.levels import SUPPORT, Level, classify_levels, find_levels
from stocksignal.models import Quote, ScreenResult

NAME = "breakout"


def screen_breakout(df: pd.DataFrame, quote: Quote, cfg: Config) -> ScreenResult:
    level, breaking_pos, failure_reason = _find_breakout(df, cfg)
    if level is None or breaking_pos is None:
        return ScreenResult(name=NAME, passed=False, reasons=(failure_reason,))

    failures: list[str] = []
    passes: list[str] = []

    # GATE: the retest. The course's actual rule for a quality breakout.
    retest = _retest_held(df, level.price, breaking_pos, cfg)
    if cfg.breakout_require_retest and not retest:
        waiting = len(df) - 1 - breaking_pos
        failures.append(
            f"the {level.price:.2f} break has not been retested yet "
            f"({waiting} session(s) since it broke). The course says wait for the "
            "push back and for price strength to return, so this setup is "
            "unfinished rather than failed"
        )
    elif retest:
        passes.append(
            f"price pulled back to the {level.price:.2f} level and closed back above it. "
            "This is the reassurance the course calls the key tell"
        )

    # GATE: a healthy uptrend around the break, page 75's opening requirement.
    slow = df["close"].rolling(cfg.sma_slow, min_periods=cfg.sma_slow).mean()
    latest_slow = float(slow.iloc[-1]) if len(slow) and pd.notna(slow.iloc[-1]) else None
    close = float(df["close"].iloc[-1])
    if latest_slow is None:
        failures.append(
            f"not enough history to know whether this sits in an uptrend "
            f"({len(df)} bars, need {cfg.sma_slow})"
        )
    elif close <= latest_slow:
        failures.append(
            f"close {close:,.2f} is below the {cfg.sma_slow}-period average "
            f"{latest_slow:,.2f}, so this is a bounce rather than a breakout inside "
            "a healthy uptrend"
        )
    else:
        passes.append(f"sits in an uptrend, close {close:,.2f} above the slow average")

    if failures:
        return ScreenResult(name=NAME, passed=False, score=0.0, reasons=tuple(failures))

    # Everything below is elevating or deprecating. None of it gates.
    breaking = df.iloc[breaking_pos]
    avg_vol_before = average_volume(df["volume"].iloc[:breaking_pos], cfg.avg_volume_window)
    volume_ratio = float(breaking["volume"]) / avg_vol_before if avg_vol_before > 0 else 0.0
    volume_strength = _normalise(
        volume_ratio, cfg.breakout_volume_spike_min, cfg.breakout_volume_spike_strong
    )
    if volume_ratio >= cfg.breakout_volume_spike_min:
        passes.append(
            f"the breaking bar traded {volume_ratio:.2f}x its recent average volume, "
            "which the course reads as investor interest behind the move"
        )

    three_bar, three_bar_note = _three_bar_setup(df, breaking_pos, cfg)
    if three_bar_note:
        passes.append(three_bar_note)

    score = (
        cfg.w_breakout_volume * volume_strength
        + cfg.w_breakout_three_bar * three_bar
        + cfg.w_breakout_recency * level.recency
    )

    reading = rsi(df["close"], cfg.rsi_period)
    latest_rsi = float(reading.iloc[-1]) if len(reading) and pd.notna(reading.iloc[-1]) else None
    if latest_rsi is not None and latest_rsi >= cfg.rsi_overbought:
        score -= cfg.breakout_overbought_penalty
        passes.append(
            f"deprecating: RSI {latest_rsi:.1f} is at or above the "
            f"{cfg.rsi_overbought:.0f} line, so this is a poor entry on a good setup"
        )

    passes.append(f"broke the previous resistance, now {level.describe()}")
    return ScreenResult(
        name=NAME, passed=True, score=round(max(score, 0.0), 4), reasons=tuple(passes)
    )


def _three_bar_setup(df: pd.DataFrame, breaking_pos: int, cfg: Config) -> tuple[float, str | None]:
    """The 3-bar setup as pages 77 to 81 describe it, scored 0 to 1.

    IGNITE first, then one or two BABY bars testing the move, then a
    CONFIRMATION bar holding above them. The breaking bar is the ignite.

    Returns a strength rather than a verdict, because the course calls this an
    elevating factor and nothing more. A setup that is absent, unfinished, or
    spoiled by a fat baby simply scores zero; none of those reject the breakout.
    """
    ignite = df.iloc[breaking_pos]
    ignite_body, _ = body_and_wick(ignite)
    if ignite_body <= 0:
        return 0.0, None

    # One baby, or two for the 4-bar variant page 81 says is slightly better.
    for babies in (1, 2):
        confirm_pos = breaking_pos + babies + 1
        if confirm_pos >= len(df):
            continue
        baby_rows = [df.iloc[breaking_pos + n] for n in range(1, babies + 1)]
        bodies = [body_and_wick(row)[0] for row in baby_rows]
        if any(body >= ignite_body for body in bodies):
            continue  # "if the IGNITING-BAR is smaller than the BABY-BAR it shows weakness"

        # Page 80's fat baby, and it is POSITIONAL. A test that gives back the
        # whole ignition move is not a test that held.
        if any(float(row["low"]) < float(ignite["low"]) for row in baby_rows):
            return 0.0, (
                "no 3-bar setup credited: the baby bar's wick passed below the "
                "ignition bar, which the course calls a fat baby"
            )

        confirm = df.iloc[confirm_pos]
        if float(confirm["close"]) <= max(float(row["close"]) for row in baby_rows):
            continue
        # A baby bar that closed exactly where it opened has no body at all. That
        # is the STRONGEST version of this test, not an error: the whole
        # comparison asks how much bigger the ignition bar is than the bar that
        # tested it, and the answer here is unboundedly. `_normalise` clamps at
        # the ceiling, so infinity scores 1.0 and nothing overflows.
        #
        # It crashed instead, with a ZeroDivisionError, until the backtest ran
        # this screen over every bar of 272 tickers and found it. Worth recording
        # how it hid: `scan` catches per-ticker exceptions and files them as data
        # errors, so this never looked like a bug, it looked like a handful of
        # tickers with bad data. The bias points the wrong way too — it dropped
        # exactly the setups that would have scored highest.
        biggest_baby = max(bodies)
        ratio = ignite_body / biggest_baby if biggest_baby > 0 else float("inf")
        strength = _normalise(ratio, 1.0, cfg.breakout_ignition_strong_ratio)
        # The 4-bar variant is two tests of strength rather than one.
        if babies == 2:
            strength = min(strength * 1.1, 1.0)
        shape = "3-bar" if babies == 1 else "4-bar"
        return strength, (
            f"{shape} setup: the igniting bar's body is {ratio:.1f}x the baby bar's, "
            "and the confirmation bar held above it"
        )
    return 0.0, None


def _retest_held(df: pd.DataFrame, level_price: float, breaking_pos: int, cfg: Config) -> bool:
    """Did price pull back to the broken level and then close back above it?

    Promoted from a scoring bonus to a gate. See `breakout_require_retest` in
    Config for the passages that forced the change, and for the invented quote
    that had been justifying the old behaviour.

    The window is bounded: a pullback fifteen sessions after the break is the
    course's "test of the change of direction", while one three months later is
    a separate event that happens to be near the same price.
    """
    touch_ceiling = level_price * (1 + cfg.breakout_dip_tolerance_pct / 100.0)
    last = min(breaking_pos + cfg.breakout_retest_window, len(df) - 1)
    touched = False
    for pos in range(breaking_pos + 1, last + 1):
        row = df.iloc[pos]
        if not touched and float(row["low"]) <= touch_ceiling:
            touched = True
        elif touched and float(row["close"]) > level_price:
            return True
    return False


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
    """0 at `floor`, 1.0 at `ceiling` and beyond. Mirrors trend.py's gap strength.

    Defined once. The rebuild left two copies of this in the file, identical
    apart from the order of the clamp, and Python silently kept the second.
    Harmless in effect and worth deleting anyway: two definitions of the same
    name is a merge accident waiting to be resolved the wrong way round.
    """
    if ceiling <= floor:
        return 0.0
    return max(0.0, min((value - floor) / (ceiling - floor), 1.0))
