"""Zac's entry rule as a ledger: N elevating factors, zero deprecating.

READ THIS BEFORE QUOTING ANY NUMBER THIS PRODUCES.

**The threshold in this script is Zac's, not the course's.** Searched all 256
pages on 14 August 2026. The course never prints a list of elevating factors,
never states how many are required, and explicitly refuses to score the ledger:

  p45   "Every indicator that is in your favor is an elevating factor."
        Open-ended by definition, so there is no roster to count against.
  p47   "a moderate amount of probability (Elevating factors) in our favor"
        is the most quantitative the course ever gets.
  p131  "Even good trades can have some deprecating factors, but the key is
        they have more elevating factors."
  p132  "A big elevating factor can counter a deprecating factor."
  p205  takes a UVXY position while overbought, because directional strength
        outweighs it.

So "at least N elevating AND zero deprecating" is STRICTER than the rulebook on
the deprecating side and invents a number on the elevating side. It is recorded
here as Zac's rule so that nobody reading this later mistakes it for page 131.

THE FACTOR LIST IS A SUBSET, AND THE SUBSET IS BIASED. Of the roughly 22
elevating factors named across the course, these are the ones computable from
daily OHLCV. Missing: analyst price targets (p133, p145-150), insider buying
(p159-165), catalysts (p133), overreaction news (p151-158). Missing on the other
side: dilution (p174-176), delisting threat (p174, p202), insider selling,
reverse splits (p184-185). Those absences are not symmetric in effect and there
is no way to correct for them here. A ledger built only from price bars is a
ledger that cannot see the reasons a stock is cheap.

CONFIRMATION IS THE TRIGGER, NOT A COUNTED FACTOR. p116 makes the first candle
OPENING above the short-term SMA the entry event, and p132 puts it on top of the
ledger rather than inside it: "Even if you have more elevating factors than
deprecating factors you should still wait for the confirmation." Counting it
would mean every candidate starts with one factor for free.

ENTRY  first candle OPENING above the 9 SMA (p116), where the ledger passes.
       Filled at the next open.
EXIT   first candle OPENING below the 9 SMA (p111: a candle that dips below but
       does not open below "was not a Validation"). Filled at the next open.

Validation is not, per p107, a concrete exit point: "It is just a point where you
evaluate your elevating factors with deprecating factors and make a decision."
Backtesting it as mechanical is a simplification, and a real one.

NaN IS NOT A VOTE. Where a factor cannot be evaluated (no three-touch level, not
enough history), it counts as neither elevating nor deprecating. Treating an
absent level as "no downside risk" is the failure mode gate 1 already has.

SPY is the comparator over each trade's own window, per the project's original
honesty gate: if it does not beat the tracker after costs, buy the tracker.
Costs NOT deducted here.
"""

from __future__ import annotations

import argparse
import math
import sys

sys.path.insert(0, "src")

from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.backtest import build_panel, universe_mask
from stocksignal.config import Config

MIN_ELEVATING = 2
MAX_HOLD = 252
DIRECTION_TEST_WINDOW = 20


def ema(a: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(a).ewm(span=span, adjust=False).mean().to_numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-elevating", type=int, default=MIN_ELEVATING)
    ap.add_argument("--no-beta-filter", action="store_true",
                    help="Drop the page 142 beta>=2 gate. Correct for ETFs: the "
                         "red-day module (p204-212) uses a hand-picked watchlist "
                         "with no scanner, and broad ETFs sit at beta ~1.")
    ap.add_argument("--only", default=None, help="Comma-separated tickers to restrict to")
    args = ap.parse_args()

    frames = {}
    for p in sorted(Path("cache").glob("*_1500d.csv")):
        frames[p.name[: -len("_1500d.csv")].upper()] = pd.read_csv(p, index_col=0, parse_dates=True)
    bench = frames.pop("SPY")
    cfg = Config()
    usable = {t: d for t, d in frames.items() if len(d) > cfg.required_history}
    if args.only:
        keep = {s.strip().upper() for s in args.only.split(",")}
        usable = {t: d for t, d in usable.items() if t in keep}
        if not usable:
            print("none of those tickers are in cache/. Run scripts/fetch_cache.py first.")
            return

    panel = build_panel(usable, bench, cfg)
    n_days, n_tickers = panel.close.shape
    o, c, h, l = panel.open, panel.close, panel.high, panel.low
    fast, slow, rsi_, rr = panel.fast, panel.slow, panel.rsi, panel.reward_risk
    resistance, avg_vol = panel.resistance, panel.avg_volume
    spy_open = bench["open"].reindex(panel.dates).to_numpy(dtype=float)

    if args.no_beta_filter:
        with np.errstate(invalid="ignore"):
            uni = (c >= cfg.min_price) & (avg_vol >= cfg.min_avg_volume)
    else:
        uni = universe_mask(panel, cfg)

    volume = np.full((n_days, n_tickers), np.nan)
    macd_hist = np.full((n_days, n_tickers), np.nan)
    atr_pctile = np.full((n_days, n_tickers), np.nan)
    for i, ticker in enumerate(panel.tickers):
        df = usable[ticker]
        rows = panel.dates.get_indexer(df.index)
        live = rows >= 0
        volume[rows[live], i] = df["volume"].to_numpy(dtype=float)[live]
        close_s = df["close"].to_numpy(dtype=float)
        # MACD 12/26/9, listed in the course's indicator set on p11. Positive
        # histogram is "positive price strength territory", p60.
        line = ema(close_s, 12) - ema(close_s, 26)
        macd_hist[rows[live], i] = (line - ema(line, 9))[live]
        # Volatility regime, p95-96: a squeeze is elevating, over-expansion is
        # deprecating. Measured as today's 20-day range width against its own
        # trailing year, so it is causal and comparable across instruments.
        tr = pd.Series((df["high"] - df["low"]).to_numpy(dtype=float) / close_s * 100)
        width = tr.rolling(20).mean()
        pct = width.rolling(252).rank(pct=True).to_numpy()
        atr_pctile[rows[live], i] = pct[live]

    # Confirmation is a transition: the FIRST candle opening above the 9 SMA.
    opens_above = np.zeros((n_days, n_tickers), dtype=bool)
    with np.errstate(invalid="ignore"):
        raw = (o > fast) & np.isfinite(fast)
    opens_above[1:] = raw[1:] & ~raw[:-1]

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

    def tested_and_held(t, i):
        """Rejection or acceptance of a direction change, p63 and p76.

        Price came down to the long-term SMA inside the recent window and is
        back above it. "when there is change of direction we usually test it.
        This reassures that they have the power to hold that breakout."
        """
        lo = max(0, t - DIRECTION_TEST_WINDOW)
        touched = False
        for u in range(lo, t):
            if np.isfinite(l[u, i]) and np.isfinite(slow[u, i]) and l[u, i] <= slow[u, i]:
                touched = True
                break
        return touched and np.isfinite(c[t, i]) and np.isfinite(slow[t, i]) and c[t, i] > slow[t, i]

    def ledger(t, i):
        """Returns (elevating names, deprecating names). NaN votes for neither."""
        up, down = [], []
        # Directional strength, p45 / p115 item 4 / p64 for the inverse.
        if np.isfinite(slow[t, i]) and np.isfinite(c[t, i]):
            (up if c[t, i] > slow[t, i] else down).append("direction")
        # Is this a good deal, p115 item 3. Below fair value is "okay", oversold
        # is "good". Overbought is deprecating, p73 / p119.
        if np.isfinite(rsi_[t, i]):
            if rsi_[t, i] < cfg.rsi_oversold:
                up.append("rsi_oversold")
            elif rsi_[t, i] < 50:
                up.append("rsi_below_fair")
            elif rsi_[t, i] >= cfg.rsi_overbought:
                down.append("rsi_overbought")
        # MACD price-strength territory, p60.
        if np.isfinite(macd_hist[t, i]):
            (up if macd_hist[t, i] > 0 else down).append("macd")
        # More upward potential than downward, p21 / p115 item 1 / p25 inverse.
        if np.isfinite(rr[t, i]):
            (up if rr[t, i] > 1.0 else down).append("reward_risk")
        # The 3 or 4 bar setup, p77-81, "a huge elevating factor".
        if ignites(t, i):
            up.append("ignition_setup")
        # Volume spike, p119 / p122.
        v, a = volume[t, i], avg_vol[t, i]
        if np.isfinite(v) and np.isfinite(a) and a > 0 and v >= cfg.breakout_volume_spike_min * a:
            up.append("volume_spike")
        # Rejection or acceptance of a direction change, p63 / p76 / p115 item 8.
        if tested_and_held(t, i):
            up.append("direction_tested")
        # Volatility regime, p95-96.
        if np.isfinite(atr_pctile[t, i]):
            if atr_pctile[t, i] <= 0.25:
                up.append("vol_squeeze")
            elif atr_pctile[t, i] >= 0.90:
                down.append("vol_overexpanded")
        # Entering right under a resistance level, p14.
        if np.isfinite(resistance[t, i]) and np.isfinite(c[t, i]) and c[t, i] > 0:
            if (resistance[t, i] - c[t, i]) / c[t, i] * 100 < 2.0:
                down.append("at_resistance")
        return up, down

    confirmations = 0
    blocked_few = 0
    blocked_dep = 0
    rets, bench_rets, holds = [], [], []
    dep_counter, up_counter = {}, {}

    for i in range(n_tickers):
        busy_until = -1
        for t in range(1, n_days - 1):
            if not (opens_above[t, i] and uni[t, i]):
                continue
            confirmations += 1
            if t <= busy_until:
                continue
            up, down = ledger(t, i)
            for d in down:
                dep_counter[d] = dep_counter.get(d, 0) + 1
            if down:
                blocked_dep += 1
                continue
            if len(up) < args.min_elevating:
                blocked_few += 1
                continue
            for u_ in up:
                up_counter[u_] = up_counter.get(u_, 0) + 1
            entry_bar = t + 1
            entry = o[entry_bar, i]
            if not np.isfinite(entry):
                continue
            exit_bar = None
            limit = min(entry_bar + MAX_HOLD, n_days - 2)
            for u in range(entry_bar, limit + 1):
                if np.isfinite(o[u, i]) and np.isfinite(fast[u, i]) and o[u, i] < fast[u, i]:
                    exit_bar = u + 1
                    break
            if exit_bar is None:
                exit_bar = limit + 1
            ex = o[exit_bar, i]
            si, so = spy_open[entry_bar], spy_open[exit_bar]
            if not (np.isfinite(ex) and np.isfinite(si) and np.isfinite(so) and si > 0):
                continue
            rets.append((ex / entry - 1.0) * 100)
            bench_rets.append((so / si - 1.0) * 100)
            holds.append(exit_bar - entry_bar)
            busy_until = exit_bar

    a, b = np.array(rets), np.array(bench_rets)
    print(f"universe {n_tickers} tickers, {panel.dates[0].date()} to {panel.dates[-1].date()}")
    print(f"beta filter: {'OFF (ETF mode)' if args.no_beta_filter else 'ON (page 142)'}")
    print(f"rule: >= {args.min_elevating} elevating AND zero deprecating  <-- Zac's rule, not the course's\n")
    print(f"confirmations (candle opens above the 9 SMA, in universe)  {confirmations:>6}")
    print(f"  blocked by a deprecating factor                          {blocked_dep:>6}")
    print(f"  blocked by too few elevating factors                     {blocked_few:>6}")
    print(f"  TRADES TAKEN                                             {len(a):>6}")
    if not len(a):
        print("\nNo trades. The rule is too strict for this universe.")
        return
    drop = math.ceil(0.05 * len(a))
    trimmed = np.sort(a)[: len(a) - drop] if drop < len(a) else a
    print(f"\nhit rate    {(a > 0).mean() * 100:>7.1f}%")
    print(f"mean        {a.mean():>+7.2f}%      SPY over same windows  {b.mean():>+7.2f}%")
    print(f"median      {np.median(a):>+7.2f}%      excess                 {a.mean() - b.mean():>+7.2f}%")
    print(f"trim best5% {trimmed.mean():>+7.2f}%      median hold            {np.median(holds):>7.0f}d")
    print("\nwhat blocked entries (deprecating factor counts):")
    for k, v in sorted(dep_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v:>6}")
    print("\nwhat qualified the trades taken (elevating factor counts):")
    for k, v in sorted(up_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v:>6}")


if __name__ == "__main__":
    main()
