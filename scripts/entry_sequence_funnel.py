"""Zac's sequence as a STATE MACHINE, not a coincidence at one bar.

  ARM      RSI crosses below 30. The name goes on the watchlist.
  RECLAIM  first later bar closing above BOTH SMAs, with fast above slow.
  IGNITE   a 3- or 4-bar ignition setup completing at or shortly after reclaim,
           while still above both SMAs. This is the entry bar.
  RATIO    reward:risk >= 2 at that entry bar.

A funnel of COUNTS. No returns, no control, no percentile: this asks how often
the sequence completes, not whether it makes money."""
import sys; sys.path.insert(0,'src')
import numpy as np, pandas as pd
from pathlib import Path
from stocksignal.backtest import build_panel, universe_mask
from stocksignal.config import Config

frames={}
for p in sorted(Path('cache').glob('*_1500d.csv')):
    frames[p.name[:-len('_1500d.csv')].upper()] = pd.read_csv(p, index_col=0, parse_dates=True)
bench=frames.pop('SPY'); cfg=Config()
usable={t:d for t,d in frames.items() if len(d)>cfg.required_history}
panel = build_panel(usable, bench, cfg)
uni = universe_mask(panel, cfg)
n_d, n_t = panel.close.shape
o,c,l,h = panel.open, panel.close, panel.low, panel.high
fast, slow, rsi_, rr = panel.fast, panel.slow, panel.rsi, panel.reward_risk
holds = (c > fast) & (c > slow) & (fast > slow)

def ignites(t, i):
    for babies in (1,2):
        ig = t - babies - 1
        if ig < 0: continue
        ib = abs(c[ig,i]-o[ig,i])
        if not (ib > 0): continue
        bb = [abs(c[ig+k,i]-o[ig+k,i]) for k in range(1,babies+1)]
        if any(not np.isfinite(b) or b >= ib for b in bb): continue
        if any(l[ig+k,i] < l[ig,i] for k in range(1,babies+1)): continue
        if c[t,i] > max(c[ig+k,i] for k in range(1,babies+1)): return True
    return False

IGNITE_WINDOW = 10
for ARM in (10, 21, 63, 126, 252, 10**6):
    armed=reclaimed=ignited=ratio=0; rrs=[]
    for i in range(n_t):
        r = rsi_[:,i]
        for t in range(1, n_d):
            if not (np.isfinite(r[t]) and np.isfinite(r[t-1]) and r[t] < 30 <= r[t-1]):
                continue
            armed += 1
            end = min(t + ARM, n_d - 1)
            rec = next((u for u in range(t+1, end+1) if holds[u,i] and uni[u,i]), None)
            if rec is None: continue
            reclaimed += 1
            ign = next((v for v in range(rec, min(rec+IGNITE_WINDOW, n_d-1)+1)
                        if holds[v,i] and ignites(v,i)), None)
            if ign is None: continue
            ignited += 1
            if np.isfinite(rr[ign,i]):
                rrs.append(rr[ign,i])
                if rr[ign,i] >= 2.0: ratio += 1
    tag = "unbounded" if ARM > 10**5 else f"{ARM} sessions"
    rrs_a = np.array(rrs)
    med = f"{np.median(rrs_a):.2f}" if len(rrs_a) else "n/a"
    pct = f"{ratio/armed*100:.2f}%" if armed else "-"
    print(f"stay armed {tag:>12}:  armed {armed:5d}  -> reclaim SMAs {reclaimed:5d}"
          f"  -> ignition {ignited:5d}  -> R:R>=2 {ratio:4d}   ({pct} of dips)"
          f"   median R:R at entry {med}  measurable {len(rrs_a)}")
