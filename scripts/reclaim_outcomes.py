"""What actually HAPPENED to the armed reclaim sequence. Counts only.

Companion to `entry_sequence_funnel.py`, which answered "how often does the
sequence complete". This one answers the next question: of the setups that did
complete, how many went up, how many went down, and how many reached a 2:1 move.

  ARM      RSI crosses below 30. The name goes on the watchlist and STAYS there.
  RECLAIM  first later bar closing above BOTH SMAs, with fast above slow, while
           inside the page 142 universe filter. This is the signal bar.
  ENTRY    the NEXT bar's open. Same next-open fill the main backtest uses, for
           the same reason: you cannot buy a close you have already seen.

Note what is NOT in this sequence. The ignition bar is absent, because the rule
as stated is "RSI under 30, then price reclaims the 9 while holding the 180".
`entry_sequence_funnel.py` adds ignition and its numbers are the ones to read
for that variant. Gate 1 is also absent, deliberately: it is the thing being
questioned, and filtering by it here would answer a different question.

WHAT COUNTS AS RISK, AND WHY THIS IS A RULEBOOK CHOICE RATHER THAN A DETAIL.

"Hit 2:1" needs a floor to measure against, and the project has two candidates
that disagree:

  three-touch   The rulebook's own definition, `panel.support`. Faithful, and
                undefined 92% of the time, which is the finding from 11 August.
  swing low     The most recent confirmed local low, which always has an answer
                and is what an eye does when it marks a chart.

Both are reported. The swing low is primary because the three-touch definition
cannot answer often enough to produce a count worth reading. This is a change to
the rulebook and it is recorded as one, not smuggled in.

The swing low is CAUSAL. A local low at bar j is not knowable until `SWING_LOOKBACK`
bars have passed on the right hand side, so it is treated as confirmed at bar
j + SWING_LOOKBACK and never before. Getting this wrong would hand every trade a
stop chosen with hindsight, which is the most flattering bug available here.

OVERLAP. One name can dip under 30 repeatedly during the same drawdown, and
counting every crossing as a separate trade would let a single move contribute
five times. A new arm is skipped while an earlier setup on that ticker is still
inside its horizon. The number skipped is reported, because a rule that quietly
drops half the sample is a rule that should be visible.

COSTS ARE NOT DEDUCTED. These are gross counts. The main backtest deducts costs;
this script is descriptive and deliberately simpler, so the hit rates here are
slightly kinder than a tradeable version of the same thing would be.

NO CONTROL ARM, NO PERCENTILE, NO SIGNIFICANCE CLAIM. This says what happened,
not whether it beats chance. A hit rate with nothing to compare it against is
not evidence of an edge, and nothing in the output should be read as one.
"""

import sys

sys.path.insert(0, "src")

from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.backtest import build_panel, universe_mask
from stocksignal.config import Config

SWING_LOOKBACK = 5
HORIZONS = (5, 10, 20)
PRIMARY_HORIZON = 20
TARGET_R = 2.0
ARM_WINDOWS = (21, 63, 252, 10**6)


def causal_swing_lows(low: np.ndarray, lookback: int = SWING_LOOKBACK) -> np.ndarray:
    """Value of the most recent CONFIRMED swing low at each bar, NaN before the first.

    A bar is a swing low if its low is strictly under the `lookback` bars either
    side of it. That verdict needs the right hand side, so it is published at
    bar j + lookback and the array carries it forward from there.
    """
    n = len(low)
    out = np.full(n, np.nan)
    if n < 2 * lookback + 1:
        return out
    is_swing = np.zeros(n, dtype=bool)
    for j in range(lookback, n - lookback):
        window = low[j - lookback : j + lookback + 1]
        if not np.isfinite(window).all():
            continue
        if low[j] == window.min() and (window[:lookback] > low[j]).all():
            if (window[lookback + 1 :] > low[j]).all():
                is_swing[j] = True
    current = np.nan
    for t in range(n):
        j = t - lookback
        if j >= 0 and is_swing[j]:
            current = low[j]
        out[t] = current
    return out


def walk(entry_price, stop, target, high, low, close, start, horizon, n_days):
    """Outcome of one trade: which level was reached first, and where it finished.

    Returns (hit_target_first, hit_stop_first, finished_up, finished_flat_or_down).

    A bar that spans both levels is scored as the STOP. Daily bars cannot say
    which came first inside the session, and assuming the good one is how a
    backtest talks itself into a hit rate it would not have had.
    """
    last = min(start + horizon, n_days - 1)
    hit_target = hit_stop = False
    for u in range(start, last + 1):
        bar_low, bar_high = low[u], high[u]
        if np.isfinite(bar_low) and bar_low <= stop:
            hit_stop = True
            break
        if np.isfinite(bar_high) and bar_high >= target:
            hit_target = True
            break
    final = close[last]
    if not np.isfinite(final):
        return hit_target, hit_stop, False, False
    return hit_target, hit_stop, final > entry_price, final <= entry_price


def main() -> None:
    frames = {}
    for p in sorted(Path("cache").glob("*_1500d.csv")):
        frames[p.name[: -len("_1500d.csv")].upper()] = pd.read_csv(
            p, index_col=0, parse_dates=True
        )
    bench = frames.pop("SPY")
    cfg = Config()
    usable = {t: d for t, d in frames.items() if len(d) > cfg.required_history}
    panel = build_panel(usable, bench, cfg)
    uni = universe_mask(panel, cfg)
    n_days, n_tickers = panel.close.shape

    o, c, l, h = panel.open, panel.close, panel.low, panel.high
    fast, slow, rsi_, support = panel.fast, panel.slow, panel.rsi, panel.support
    holds = (c > fast) & (c > slow) & (fast > slow)

    swings = np.column_stack([causal_swing_lows(l[:, i]) for i in range(n_tickers)])

    print(f"universe {n_tickers} tickers, {n_days} sessions, "
          f"{panel.dates[0].date()} to {panel.dates[-1].date()}")
    print(f"risk = entry minus most recent confirmed swing low "
          f"(lookback {SWING_LOOKBACK}), target = entry plus {TARGET_R:.0f}R")
    print(f"costs NOT deducted, no control arm\n")

    for arm_window in ARM_WINDOWS:
        stats = {
            "arms": 0, "overlap_skipped": 0, "reclaims": 0,
            "no_risk": 0, "entries": 0,
            "three_touch_measurable": 0,
        }
        per_h = {H: {"target": 0, "stop": 0, "up": 0, "down": 0} for H in HORIZONS}

        for i in range(n_tickers):
            r, low_i, high_i, close_i, open_i = rsi_[:, i], l[:, i], h[:, i], c[:, i], o[:, i]
            swing_i = swings[:, i]
            busy_until = -1
            for t in range(1, n_days):
                if not (np.isfinite(r[t]) and np.isfinite(r[t - 1]) and r[t] < 30 <= r[t - 1]):
                    continue
                stats["arms"] += 1
                if t <= busy_until:
                    stats["overlap_skipped"] += 1
                    continue
                end = min(t + arm_window, n_days - 1)
                rec = next(
                    (u for u in range(t + 1, end + 1) if holds[u, i] and uni[u, i]), None
                )
                if rec is None:
                    continue
                stats["reclaims"] += 1
                entry_bar = rec + 1
                if entry_bar >= n_days:
                    continue
                entry = open_i[entry_bar]
                stop = swing_i[rec]
                if not (np.isfinite(entry) and np.isfinite(stop)) or stop >= entry:
                    stats["no_risk"] += 1
                    continue
                stats["entries"] += 1
                if np.isfinite(support[rec, i]):
                    stats["three_touch_measurable"] += 1
                risk = entry - stop
                target = entry + TARGET_R * risk
                for H in HORIZONS:
                    ht, hs, up, down = walk(
                        entry, stop, target, high_i, low_i, close_i, entry_bar, H, n_days
                    )
                    if ht:
                        per_h[H]["target"] += 1
                    if hs:
                        per_h[H]["stop"] += 1
                    if up:
                        per_h[H]["up"] += 1
                    elif down:
                        per_h[H]["down"] += 1
                busy_until = entry_bar + PRIMARY_HORIZON

        tag = "unbounded" if arm_window > 10**5 else f"{arm_window} sessions"
        n = stats["entries"]
        print(f"--- stay armed: {tag} ---")
        print(f"  RSI dips under 30      {stats['arms']:6d}"
              f"   (skipped as overlapping: {stats['overlap_skipped']})")
        print(f"  reclaimed both SMAs    {stats['reclaims']:6d}")
        print(f"  had a usable risk      {n:6d}"
              f"   (dropped, no swing low under entry: {stats['no_risk']})")
        print(f"  of those, three-touch support also defined: "
              f"{stats['three_touch_measurable']}"
              f" ({stats['three_touch_measurable']/n*100:.1f}%)" if n else "")
        for H in HORIZONS:
            d = per_h[H]
            if not n:
                continue
            star = " <-- primary" if H == PRIMARY_HORIZON else ""
            print(f"  {H:3d} sessions:  up {d['up']:5d} ({d['up']/n*100:5.1f}%)"
                  f"   down {d['down']:5d} ({d['down']/n*100:5.1f}%)"
                  f"   reached 2R {d['target']:5d} ({d['target']/n*100:5.1f}%)"
                  f"   stopped first {d['stop']:5d} ({d['stop']/n*100:5.1f}%){star}")
        print()


if __name__ == "__main__":
    main()
