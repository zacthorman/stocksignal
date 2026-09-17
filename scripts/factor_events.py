"""Every confirmation event, with its factors and what the trade did.

WHY THIS FILE EXISTS SEPARATELY FROM `factor_ledger.py`. That script asks one
question ("what does Zac's >= 2 elevating rule do?") and answers it by walking
the panel once. The combination search asks 512 questions, and walking the panel
512 times would take an afternoon and invite shortcuts.

The trick is that the trade is independent of the rule. A confirmation bar, its
next-open entry and its first-open-below-the-9 exit are the same whatever
factors are required, so the expensive part is computed ONCE here and every
config in `factor_search.py` becomes a filter over these rows.

WHAT IS NOT PRECOMPUTED, AND WHY. Overlap thinning ("do not open a second trade
in a name while one is still running") depends on which trades a config takes,
so it cannot live here. It is applied per config in the search, greedily and in
date order, exactly as `factor_ledger.py` does it.

Definitions are `factor_ledger.py`'s, unchanged and deliberately so: same
confirmation event, same entry, same exit, same factors, same page 142
universe. This file adds no judgement of its own. It writes the rows down.

ONE ADDITION, MARKED. `factor_ledger.py` records a deprecating factor only when
it fires; the inverse of `direction`, `macd` and `reward_risk` were pooled into
those same names. Here each side gets its own column (`direction_down`,
`macd_negative`, `reward_risk_poor`) so a config can require, veto or ignore
each one independently. Same measurements, split rather than changed.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "src")

from pathlib import Path

import numpy as np
import pandas as pd

from stocksignal.backtest import build_panel, universe_mask
from stocksignal.config import Config

MAX_HOLD = 252
DIRECTION_TEST_WINDOW = 20

ELEVATING = [
    "direction",
    "rsi_oversold",
    "rsi_below_fair",
    "macd",
    "reward_risk",
    "ignition_setup",
    "volume_spike",
    "direction_tested",
    "vol_squeeze",
]
DEPRECATING = [
    "direction_down",
    "rsi_overbought",
    "macd_negative",
    "reward_risk_poor",
    "vol_overexpanded",
    "at_resistance",
]


def ema(a: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(a).ewm(span=span, adjust=False).mean().to_numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/factor-events.csv"))
    ap.add_argument("--only", default=None)
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

    panel = build_panel(usable, bench, cfg)
    n_days, n_tickers = panel.close.shape
    o, c, low = panel.open, panel.close, panel.low
    fast, slow, rsi_, rr = panel.fast, panel.slow, panel.rsi, panel.reward_risk
    resistance, avg_vol = panel.resistance, panel.avg_volume
    spy_open = bench["open"].reindex(panel.dates).to_numpy(dtype=float)
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
        line = ema(close_s, 12) - ema(close_s, 26)
        macd_hist[rows[live], i] = (line - ema(line, 9))[live]
        tr = pd.Series((df["high"] - df["low"]).to_numpy(dtype=float) / close_s * 100)
        width = tr.rolling(20).mean()
        pct = width.rolling(252).rank(pct=True).to_numpy()
        atr_pctile[rows[live], i] = pct[live]

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
            if any(low[ig + k, i] < low[ig, i] for k in range(1, babies + 1)):
                continue
            if c[t, i] > max(c[ig + k, i] for k in range(1, babies + 1)):
                return True
        return False

    def tested_and_held(t, i):
        lo = max(0, t - DIRECTION_TEST_WINDOW)
        touched = False
        for u in range(lo, t):
            if np.isfinite(low[u, i]) and np.isfinite(slow[u, i]) and low[u, i] <= slow[u, i]:
                touched = True
                break
        return touched and np.isfinite(c[t, i]) and np.isfinite(slow[t, i]) and c[t, i] > slow[t, i]

    def flags(t, i) -> dict[str, int]:
        f = dict.fromkeys(ELEVATING + DEPRECATING, 0)
        if np.isfinite(slow[t, i]) and np.isfinite(c[t, i]):
            f["direction" if c[t, i] > slow[t, i] else "direction_down"] = 1
        if np.isfinite(rsi_[t, i]):
            if rsi_[t, i] < cfg.rsi_oversold:
                f["rsi_oversold"] = 1
            elif rsi_[t, i] < 50:
                f["rsi_below_fair"] = 1
            elif rsi_[t, i] >= cfg.rsi_overbought:
                f["rsi_overbought"] = 1
        if np.isfinite(macd_hist[t, i]):
            f["macd" if macd_hist[t, i] > 0 else "macd_negative"] = 1
        if np.isfinite(rr[t, i]):
            f["reward_risk" if rr[t, i] > 1.0 else "reward_risk_poor"] = 1
        if ignites(t, i):
            f["ignition_setup"] = 1
        v, a = volume[t, i], avg_vol[t, i]
        if np.isfinite(v) and np.isfinite(a) and a > 0 and v >= cfg.breakout_volume_spike_min * a:
            f["volume_spike"] = 1
        if tested_and_held(t, i):
            f["direction_tested"] = 1
        if np.isfinite(atr_pctile[t, i]):
            if atr_pctile[t, i] <= 0.25:
                f["vol_squeeze"] = 1
            elif atr_pctile[t, i] >= 0.90:
                f["vol_overexpanded"] = 1
        if np.isfinite(resistance[t, i]) and np.isfinite(c[t, i]) and c[t, i] > 0:
            if (resistance[t, i] - c[t, i]) / c[t, i] * 100 < 2.0:
                f["at_resistance"] = 1
        return f

    rows = []
    for i in range(n_tickers):
        ticker = panel.tickers[i]
        for t in range(1, n_days - 1):
            if not (opens_above[t, i] and uni[t, i]):
                continue
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
            row = {
                "ticker": ticker,
                "signal_date": panel.dates[t].date().isoformat(),
                "entry_date": panel.dates[entry_bar].date().isoformat(),
                "exit_date": panel.dates[exit_bar].date().isoformat(),
                "entry_bar": entry_bar,
                "exit_bar": exit_bar,
                "hold_days": exit_bar - entry_bar,
                "ret_pct": (ex / entry - 1.0) * 100,
                "spy_pct": (so / si - 1.0) * 100,
            }
            row.update(flags(t, i))
            rows.append(row)

    out = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(
        f"{len(out)} events, {out.ticker.nunique()} tickers, "
        f"{out.signal_date.min()} to {out.signal_date.max()} -> {args.out}"
    )


if __name__ == "__main__":
    main()
