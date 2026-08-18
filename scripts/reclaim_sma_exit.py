"""The same entry sequence, exited on a close below the 9 SMA. Zac's exit rule.

THE RULE, AND WHY IT IS A THIRD EXIT RATHER THAN A VARIANT OF THE TWO THAT EXIST.

`Config.exit_rule` currently knows two things. "hold" sells at a fixed horizon
come what may, and it is what every published number in this project measured.
"stops" is the page 234 support stop with a trailing stop after the target. This
is neither. It is a trend-following exit with no target and no fixed floor:

  ENTRY  first bar closing above BOTH SMAs after an RSI dip under 30 armed the
         name. Filled at the next open, as everywhere else.
  EXIT   first bar afterwards that CLOSES BELOW the 9 SMA. Filled at the next
         open, for the same reason the entry is: you cannot trade a close you
         have already watched print.

It is the mirror image of the entry. The course's confirmation is "the first
candlestick holding above the short-term SMA line"; this exits on the first
candlestick that stops doing so. Symmetric, and it needs no level to be defined,
which is the failure mode that made gate 1 unmeasurable 92% of the time.

WHY THIS IS WORTH MEASURING AFTER THE 2:1 RESULT. A 2R target off a close stop
failed its own arithmetic in every configuration tried: best hit rate 14.5%
against the 33% needed. The diagnosis was that a close floor sits inside ordinary
noise for a high-beta name. An SMA exit does not have a fixed distance at all. It
widens when the stock is extended and tightens when it is not, which is the one
property the fixed geometry could not have.

WHAT IS BEING COMPARED AGAINST, AND WHY IT IS NOT OPTIONAL HERE.

The earlier runs counted outcomes with no control, which was defensible when the
output was "how many completed". It is not defensible for returns: a 51% up rate
means nothing without knowing what the market did on the same days. So every
trade is paired with SPY over the IDENTICAL window, entry date to exit date.

That comparator is not invented for this script. The project overview committed
to it before any backtest was written: if the screens do not beat a tracker after
costs, buy the tracker. This is that gate, applied to this exit.

THE TRIMMED MEAN IS REPORTED BECAUSE OF WHAT SESSION 5 FOUND. The breakout
screen's entire +5.18% mean turned out to be the best 5% of trades, with a
median below the control's. Any mean printed here without the trimmed figure
beside it would be able to hide the same thing.

Costs are NOT deducted. Hold times are reported because a rule that exits in
three days and one that exits in three months are different products even at
identical returns.
"""

import sys

sys.path.insert(0, "src")

import math
from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.backtest import build_panel, universe_mask
from stocksignal.breakout_path import breakout_signals
from stocksignal.config import Config

ARM_WINDOW = 63
IGNITE_WINDOW = 10
MAX_HOLD = 252
MIN_N = 30


def summarise(rets, bench_rets, holds, truncated):
    """Mean, median, trimmed mean and the tracker comparison for one arm."""
    a = np.array(rets, dtype=float)
    b = np.array(bench_rets, dtype=float)
    n = len(a)
    if not n:
        return None
    drop = math.ceil(0.05 * n)
    trimmed = np.sort(a)[: n - drop] if drop < n else a
    return {
        "n": n,
        "hit": float((a > 0).mean() * 100),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "trimmed": float(trimmed.mean()),
        "spy_mean": float(b.mean()),
        "excess": float(a.mean() - b.mean()),
        "hold": float(np.median(holds)),
        "truncated": truncated,
    }


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

    o, c = panel.open, panel.close
    l = panel.low
    fast, slow, rsi_, gap = panel.fast, panel.slow, panel.rsi, panel.gap
    rr, avg_vol = panel.reward_risk, panel.avg_volume
    holds_mask = (c > fast) & (c > slow) & (fast > slow)
    spy_open = bench["open"].reindex(panel.dates).to_numpy(dtype=float)

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
        return (
            np.isfinite(v) and np.isfinite(a) and a > 0
            and v >= cfg.breakout_volume_spike_min * a
        )

    def f_breakout(t, i):
        return bool(brk[t, i])

    def run(factors, need_ignition, closes_below=1):
        rets, bench_rets, hold_lens, truncated = [], [], [], 0
        for i in range(n_tickers):
            r, close_i, open_i, fast_i = rsi_[:, i], c[:, i], o[:, i], fast[:, i]
            busy_until = -1
            for t in range(1, n_days):
                if not (np.isfinite(r[t]) and np.isfinite(r[t - 1]) and r[t] < 30 <= r[t - 1]):
                    continue
                if t <= busy_until:
                    continue
                end = min(t + ARM_WINDOW, n_days - 1)
                rec = next(
                    (u for u in range(t + 1, end + 1) if holds_mask[u, i] and uni[u, i]), None
                )
                if rec is None:
                    continue
                if need_ignition:
                    sig = next(
                        (v for v in range(rec, min(rec + IGNITE_WINDOW, n_days - 1) + 1)
                         if holds_mask[v, i] and ignites(v, i)),
                        None,
                    )
                    if sig is None:
                        continue
                else:
                    sig = rec
                if not all(fn(sig, i) for fn in factors):
                    continue
                entry_bar = sig + 1
                if entry_bar >= n_days - 1:
                    continue
                entry = open_i[entry_bar]
                if not np.isfinite(entry):
                    continue

                # Exit: first bar closing below the 9 SMA, filled the next open.
                # `closes_below` > 1 requires that many CONSECUTIVE closes below
                # before the rule fires, which is the stricter reading of "holds
                # below". Reported as a sensitivity check, not as a choice.
                streak = 0
                exit_bar = None
                limit = min(entry_bar + MAX_HOLD, n_days - 2)
                for u in range(entry_bar, limit + 1):
                    if np.isfinite(close_i[u]) and np.isfinite(fast_i[u]) and close_i[u] < fast_i[u]:
                        streak += 1
                        if streak >= closes_below:
                            exit_bar = u + 1
                            break
                    else:
                        streak = 0
                if exit_bar is None:
                    exit_bar = limit + 1
                    truncated += 1
                if exit_bar >= n_days:
                    continue
                exit_price = open_i[exit_bar]
                if not np.isfinite(exit_price):
                    continue
                sp_in, sp_out = spy_open[entry_bar], spy_open[exit_bar]
                if not (np.isfinite(sp_in) and np.isfinite(sp_out) and sp_in > 0):
                    continue

                rets.append((exit_price / entry - 1.0) * 100)
                bench_rets.append((sp_out / sp_in - 1.0) * 100)
                hold_lens.append(exit_bar - entry_bar)
                busy_until = exit_bar
        return summarise(rets, bench_rets, hold_lens, truncated)

    CONFIGS = [
        ("base: arm + reclaim both SMAs", [], False),
        ("+ SMA gap >= 3.6% (chop filter)", [f_gap], False),
        ("+ ignition bar within 10 sessions", [], True),
        ("+ RSI < 70 at signal", [f_not_overbought], False),
        ("+ volume >= 1.5x average", [f_volume], False),
        ("+ gate 1: reward:risk >= 2 (3-touch)", [f_ratio], False),
        ("+ full breakout screen fires", [f_breakout], False),
        ("ALL of gap, ignition, RSI<70, volume", [f_gap, f_not_overbought, f_volume], True),
    ]

    print(f"universe {n_tickers} tickers, {panel.dates[0].date()} to {panel.dates[-1].date()}")
    print(f"entry: RSI<30 arms ({ARM_WINDOW} sessions), reclaim both SMAs, next-open fill")
    print("exit:  first close below the 9 SMA, next-open fill")
    print(f"costs NOT deducted. SPY measured over each trade's OWN window.\n")
    header = (f"{'configuration':<40} {'n':>4} {'hit':>6} {'mean':>7} {'med':>7} "
              f"{'trim5%':>7} {'SPY':>7} {'excess':>7} {'hold':>5}")
    print(header)
    print("-" * len(header))

    for label, factors, need_ig in CONFIGS:
        s = run(factors, need_ig)
        if s is None:
            print(f"{label:<40}    0   no trades")
            continue
        warn = "  <-- n too small" if s["n"] < MIN_N else ""
        print(f"{label:<40} {s['n']:>4} {s['hit']:>5.1f}% {s['mean']:>+6.2f}% "
              f"{s['median']:>+6.2f}% {s['trimmed']:>+6.2f}% {s['spy_mean']:>+6.2f}% "
              f"{s['excess']:>+6.2f}% {s['hold']:>4.0f}d{warn}")

    print("\nSensitivity on what \"holds below\" means, BASE configuration only:")
    for k in (1, 2, 3):
        s = run([], False, closes_below=k)
        if s:
            print(f"  {k} consecutive close(s) below the 9 SMA: n {s['n']:>4}  "
                  f"hit {s['hit']:>5.1f}%  mean {s['mean']:>+6.2f}%  "
                  f"median {s['median']:>+6.2f}%  trim5% {s['trimmed']:>+6.2f}%  "
                  f"SPY {s['spy_mean']:>+6.2f}%  excess {s['excess']:>+6.2f}%  "
                  f"hold {s['hold']:>3.0f}d  truncated {s['truncated']}")
    print("\nexcess = mean minus SPY over the same windows. The project's own")
    print("honesty gate: if it does not beat the tracker after costs, buy the tracker.")


if __name__ == "__main__":
    main()
