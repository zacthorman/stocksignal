"""One factor at a time, added to the armed reclaim sequence. Counts only.

Follows `reclaim_outcomes.py`, which measured the bare sequence: RSI under 30
arms the name, first later bar closing above both SMAs is the signal, entry at
the next open. This asks what each additional rulebook filter does to that.

WHAT IS HELD FIXED, AND WHY IT MATTERS THAT IT WAS FIXED FIRST.

  arming window   63 sessions. The realistic three-month patience limit named in
                  the README. ONE window, not four, because varying the window
                  as well as the factor turns eight comparisons into thirty two.
  horizon         20 sessions. Already the project's primary horizon; the 5 and
                  10 session numbers are not computed here and must not be
                  substituted if 20 disappoints.
  risk            most recent causally confirmed swing low, 5-bar lookback, as
                  in `reclaim_outcomes.py`. Same rulebook change, same caveat.

EVERY ROW IS PRINTED. Nothing is dropped for being unflattering, and no row is
promoted for being the best. With eight configurations against a base rate near
a coin flip, one of them looking good is the expected outcome rather than a
finding. Read the whole table or none of it.

FACTORS ARE ADDED SINGLY, NOT STACKED, except for the final row. Stacking
collapses the sample fast, and a row with nine trades in it says nothing. Any
row under `MIN_N` is printed with a warning and should not be read as a result.

WHAT IS NOT HERE, and why.

  float minimum   `min_float` needs shares outstanding. The cache holds OHLCV
                  only, so it cannot be evaluated from this data at all.
  growth template `growth_template.py` scores fundamentals, not price bars. It
                  is explicitly a non-price axis, which is the whole argument
                  for it, and it cannot be backtested from this cache.
  price targets   `opportunity.py` requires a growth direction supplied by a
                  research pass. It is an input, not something derivable here.

The last two are the only factors in the project that are independent of the
price series. Their absence from this table is a limit of the data, not a
judgement, and it is worth remembering when every row below comes back looking
like every other row: they are all reading the same six years of the same bars.

NO CONTROL ARM, NO PERCENTILE, NO SIGNIFICANCE CLAIM. Costs not deducted.
"""

import sys

sys.path.insert(0, "src")

from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.backtest import build_panel, universe_mask
from stocksignal.breakout_path import breakout_signals
from stocksignal.config import Config

SWING_LOOKBACK = 5
ARM_WINDOW = 63
HORIZON = 20
TARGET_R = 2.0
IGNITE_WINDOW = 10
MIN_N = 30


def causal_swing_lows(low: np.ndarray, lookback: int = SWING_LOOKBACK) -> np.ndarray:
    """Most recent CONFIRMED swing low at each bar. Published at j + lookback."""
    n = len(low)
    out = np.full(n, np.nan)
    if n < 2 * lookback + 1:
        return out
    is_swing = np.zeros(n, dtype=bool)
    for j in range(lookback, n - lookback):
        window = low[j - lookback : j + lookback + 1]
        if not np.isfinite(window).all():
            continue
        if (window[:lookback] > low[j]).all() and (window[lookback + 1 :] > low[j]).all():
            is_swing[j] = True
    current = np.nan
    for t in range(n):
        j = t - lookback
        if j >= 0 and is_swing[j]:
            current = low[j]
        out[t] = current
    return out


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
    fast, slow, rsi_, gap = panel.fast, panel.slow, panel.rsi, panel.gap
    rr, avg_vol = panel.reward_risk, panel.avg_volume
    holds = (c > fast) & (c > slow) & (fast > slow)
    swings = np.column_stack([causal_swing_lows(l[:, i]) for i in range(n_tickers)])

    # Raw volume, reindexed exactly as build_panel reindexes everything else.
    volume = np.full((n_days, n_tickers), np.nan)
    brk = np.zeros((n_days, n_tickers), dtype=bool)
    for i, ticker in enumerate(panel.tickers):
        df = usable[ticker]
        rows = panel.dates.get_indexer(df.index)
        live = rows >= 0
        volume[rows[live], i] = df["volume"].to_numpy(dtype=float)[live]
        passed, _ = breakout_signals(df, cfg)
        brk[rows[live], i] = passed[live]

    def ignites(t, i):
        """The 3- or 4-bar ignition setup, as in `entry_sequence_funnel.py`."""
        for babies in (1, 2):
            ig = t - babies - 1
            if ig < 0:
                continue
            ib = abs(c[ig, i] - o[ig, i])
            if not (ib > 0):
                continue
            bodies = [abs(c[ig + k, i] - o[ig + k, i]) for k in range(1, babies + 1)]
            if any(not np.isfinite(b) or b >= ib for b in bodies):
                continue
            if any(l[ig + k, i] < l[ig, i] for k in range(1, babies + 1)):
                continue
            if c[t, i] > max(c[ig + k, i] for k in range(1, babies + 1)):
                return True
        return False

    def f_gap(t, i):
        return np.isfinite(gap[t, i]) and gap[t, i] >= cfg.min_sma_gap_pct

    def f_not_overbought(t, i):
        return np.isfinite(rsi_[t, i]) and rsi_[t, i] < cfg.rsi_overbought

    def f_ratio(t, i):
        return np.isfinite(rr[t, i]) and rr[t, i] >= 2.0

    def f_volume(t, i):
        v, a = volume[t, i], avg_vol[t, i]
        return np.isfinite(v) and np.isfinite(a) and a > 0 and v >= cfg.breakout_volume_spike_min * a

    def f_breakout(t, i):
        return bool(brk[t, i])

    CONFIGS = [
        ("base: arm + reclaim both SMAs", [], False),
        ("+ SMA gap >= 3.6% (chop filter)", [f_gap], False),
        ("+ ignition bar within 10 sessions", [], True),
        ("+ RSI < 70 at signal (not overbought)", [f_not_overbought], False),
        ("+ volume >= 1.5x average at signal", [f_volume], False),
        ("+ gate 1: reward:risk >= 2 (3-touch)", [f_ratio], False),
        ("+ full breakout screen fires", [f_breakout], False),
        ("ALL of gap, ignition, RSI<70, volume", [f_gap, f_not_overbought, f_volume], True),
    ]

    print(f"universe {n_tickers} tickers, {n_days} sessions, "
          f"{panel.dates[0].date()} to {panel.dates[-1].date()}")
    print(f"arming window {ARM_WINDOW} sessions, horizon {HORIZON} sessions, "
          f"target {TARGET_R:.0f}R off the confirmed swing low")
    print(f"costs NOT deducted, no control arm, rows under n={MIN_N} are not readable\n")
    print(f"{'configuration':<40} {'n':>5} {'up':>7} {'down':>7} "
          f"{'hit 2R':>8} {'stopped':>8}  {'net R':>7}")
    print("-" * 90)

    for label, factors, need_ignition in CONFIGS:
        n = up = down = target_hit = stopped = 0
        for i in range(n_tickers):
            r, low_i, high_i, close_i, open_i = rsi_[:, i], l[:, i], h[:, i], c[:, i], o[:, i]
            swing_i = swings[:, i]
            busy_until = -1
            for t in range(1, n_days):
                if not (np.isfinite(r[t]) and np.isfinite(r[t - 1]) and r[t] < 30 <= r[t - 1]):
                    continue
                if t <= busy_until:
                    continue
                end = min(t + ARM_WINDOW, n_days - 1)
                rec = next((u for u in range(t + 1, end + 1) if holds[u, i] and uni[u, i]), None)
                if rec is None:
                    continue
                if need_ignition:
                    sig = next(
                        (v for v in range(rec, min(rec + IGNITE_WINDOW, n_days - 1) + 1)
                         if holds[v, i] and ignites(v, i)),
                        None,
                    )
                    if sig is None:
                        continue
                else:
                    sig = rec
                if not all(fn(sig, i) for fn in factors):
                    continue
                entry_bar = sig + 1
                if entry_bar >= n_days:
                    continue
                entry, stop = open_i[entry_bar], swing_i[sig]
                if not (np.isfinite(entry) and np.isfinite(stop)) or stop >= entry:
                    continue
                n += 1
                risk = entry - stop
                target = entry + TARGET_R * risk
                last = min(entry_bar + HORIZON, n_days - 1)
                hit_t = hit_s = False
                for u in range(entry_bar, last + 1):
                    if np.isfinite(low_i[u]) and low_i[u] <= stop:
                        hit_s = True
                        break
                    if np.isfinite(high_i[u]) and high_i[u] >= target:
                        hit_t = True
                        break
                if hit_t:
                    target_hit += 1
                if hit_s:
                    stopped += 1
                final = close_i[last]
                if np.isfinite(final):
                    if final > entry:
                        up += 1
                    else:
                        down += 1
                busy_until = entry_bar + HORIZON

        if not n:
            print(f"{label:<40} {0:>5}   no trades")
            continue
        # Resolved trades only: wins at +2R against stops at -1R. The rest
        # finished somewhere in between and are not counted either way.
        net_r = target_hit * TARGET_R - stopped
        warn = "  <-- n too small to read" if n < MIN_N else ""
        print(f"{label:<40} {n:>5} {up/n*100:>6.1f}% {down/n*100:>6.1f}% "
              f"{target_hit/n*100:>7.1f}% {stopped/n*100:>7.1f}%  {net_r:>+7.0f}{warn}")

    print("\nnet R counts resolved trades only: 2R per target hit, -1R per stop.")
    print("A 2R target against a 1R stop needs a hit rate above 33% to break even.")


if __name__ == "__main__":
    main()
