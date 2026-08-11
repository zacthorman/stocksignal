"""The fast breakout path must return what the screen returns. That is the whole file.

`breakout_path` exists only because calling `screen_breakout` on a truncated
frame at every bar takes about five hours for the universe. A reimplementation
bought with that argument is worth having exactly as long as somebody checks it,
because the failure mode is silent: the backtest measures one strategy, the
digest runs a slightly different one, and the number in the README describes
something nobody is trading.

So the tests here are almost all one assertion — same passes, same scores, bar
for bar — run over price series shaped to hit the parts that are easy to get
wrong:

  * plateaus, where `swing_points` marks every bar of a flat stretch and
    `_collapse_runs` has to reduce the run to one touch. This is the case the
    incremental version could most plausibly diverge on, because truncation sees
    a growing PREFIX of each run and the representative bar moves as it fills in.
  * levels ageing out of the lookback window.
  * zero-body bars, which used to crash the screen outright.
  * frames too short to have levels at all.

The random-walk test is deliberately not a hand-built chart. Hand-built frames
check that a rule does what you meant; this file checks that two implementations
agree, and for that the useful input is one neither implementation was written
with in mind.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocksignal.breakout_path import breakout_signals
from stocksignal.config import Config
from stocksignal.levels import classify_levels, find_levels
from stocksignal.screens.breakout import screen_breakout


def synthetic(seed: int, n: int = 700, plateaus: bool = True) -> pd.DataFrame:
    """A random walk with flat stretches and the odd doji, as OHLC bars."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.02, n)
    close = 100.0 * np.exp(np.cumsum(steps))

    if plateaus:
        # Flat runs are what force `_collapse_runs` to do something, and they are
        # the reason this file exists. Without them a swing is a single bar and
        # the prefix-extremum logic never gets exercised.
        for start in range(40, n - 12, 97):
            close[start : start + 6] = close[start]

    open_ = close * (1 + rng.normal(0, 0.004, n))
    # Zero-body bars: the case that raised ZeroDivisionError in the screen.
    doji = rng.random(n) < 0.03
    open_[doji] = close[doji]

    spread = np.abs(rng.normal(0, 0.012, n)) + 0.001
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = rng.lognormal(13.5, 0.6, n)
    index = pd.bdate_range(end=pd.Timestamp("2026-08-05"), periods=n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def assert_agrees(df: pd.DataFrame, cfg: Config, start: int = 60) -> int:
    """Bar for bar, the fast path and the screen. Returns how many bars passed."""
    passed, score = breakout_signals(df, cfg)
    fired = 0
    for t in range(start, len(df)):
        expected = screen_breakout(df.iloc[: t + 1], None, cfg)
        stamp = df.index[t].date()
        assert bool(passed[t]) is bool(expected.passed), (
            f"{stamp} (bar {t}): screen says passed={expected.passed}, "
            f"fast path says {bool(passed[t])}"
        )
        if expected.passed:
            fired += 1
            assert score[t] == pytest.approx(expected.score, abs=1e-9), (
                f"{stamp} (bar {t}): screen scored {expected.score}, fast path scored {score[t]}"
            )
        else:
            assert np.isnan(score[t]), f"{stamp}: scored a bar that did not pass"
    return fired


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_matches_the_screen_bar_for_bar(seed: int) -> None:
    """The load-bearing test. Five walks, every bar, passes and scores."""
    df = synthetic(seed)
    fired = assert_agrees(df, Config())
    # A test that agreed on nothing but rejections would pass while proving
    # nothing, so insist the input actually produced some signals.
    assert fired > 0, "this seed never fires; it cannot be checking much"


def test_matches_the_screen_without_plateaus() -> None:
    """No flat runs, so every swing is a single bar. The degenerate case."""
    assert_agrees(synthetic(9, plateaus=False), Config())


def test_matches_the_screen_on_a_short_lookback() -> None:
    """Levels age out fast, so the tracker has to evict as well as accumulate."""
    cfg = Config(level_lookback_days=60, level_fresh_days=10)
    assert_agrees(synthetic(3), cfg)


def test_matches_the_screen_when_the_retest_is_not_required() -> None:
    """The gate the rebuild promoted, turned back off. Far more signals, so a
    much wider sweep of the scoring path gets compared."""
    cfg = Config(breakout_require_retest=False)
    fired = assert_agrees(synthetic(2), cfg)
    assert fired > 10


def test_no_signal_before_there_is_enough_history() -> None:
    """`find_levels` returns nothing until a centred window fits, and so must this."""
    df = synthetic(1, n=120)
    cfg = Config()
    passed, _ = breakout_signals(df, cfg)
    assert not passed[: 2 * cfg.level_swing_lookback].any()


def test_levels_agree_with_find_levels_at_sampled_bars() -> None:
    """The tracker on its own, against the function it replaces.

    Checked separately from the screen because a level set can be wrong in ways
    the screen then hides: it only ever looks at the highest level price has been
    below, so an error in a lower level is invisible from the outside.
    """
    from stocksignal.breakout_path import _LevelTracker

    df = synthetic(7)
    cfg = Config()
    tracker = _LevelTracker(df, cfg)
    checked = 0
    for t in range(len(df)):
        mine = tracker.at(t)  # must be called every bar; it carries state
        if t < 60 or t % 17:
            continue
        window = df.iloc[: t + 1]
        theirs = classify_levels(find_levels(window, cfg), window, cfg)
        assert len(mine) == len(theirs), f"bar {t}: {len(mine)} levels against {len(theirs)}"
        for (price, last_pos), level in zip(sorted(mine), theirs, strict=True):
            assert price == pytest.approx(level.price, abs=1e-9)
            assert window.index[last_pos].date() == level.last_touch
        checked += 1
    assert checked > 20


def test_zero_body_baby_bar_scores_full_marks_instead_of_crashing() -> None:
    """The bug the backtest found: a doji baby bar divided by zero.

    Built as a frame rather than mocked, because the point is that the screen
    survives a shape real data contains 6,380 times in six years.
    """
    cfg = Config()
    ignite = pd.Series({"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0})
    baby = pd.Series({"open": 108.0, "high": 109.0, "low": 108.0, "close": 108.0})
    from stocksignal.indicators import body_and_wick

    assert body_and_wick(baby)[0] == 0.0
    assert body_and_wick(ignite)[0] > 0.0

    from stocksignal.screens.breakout import _three_bar_setup

    frame = pd.DataFrame(
        [
            ignite,
            baby,
            pd.Series({"open": 108.5, "high": 112.0, "low": 108.0, "close": 111.0}),
        ]
    )
    strength, note = _three_bar_setup(frame, 0, cfg)
    assert strength == 1.0, "an ignition bar infinitely larger than its baby is full strength"
    assert note is not None
