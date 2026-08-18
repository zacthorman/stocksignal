"""Does a high scorecard number lead to a better forward return than a low one?

PRE-REGISTERED. Written and committed before its first run on this data. The
decision rule, the family size and the reporting commitment are all fixed here
and none of them is revised once a result is known. That is the standing rule in
`PRE-REGISTRATION.md` and this test does not get an exemption for being new.

-----------------------------------------------------------------------------
THE HYPOTHESIS
-----------------------------------------------------------------------------
H1: forward return over the horizon rises with the scorecard decile.

Deliberately the weaker of the two things that could be asked. "The top decile
beats the control" can be produced by one lucky quarter, which is precisely how
the breakout result already failed: 2026Q2 supplied 75% of its P&L. Monotonicity
across ten buckets cannot be produced that way, because a single good quarter
lifts every decile that traded in it.

-----------------------------------------------------------------------------
THE DECISION RULE, FIXED BEFORE RUNNING
-----------------------------------------------------------------------------
The test PASSES only if all three hold:

  1. Spearman rank correlation between decile and mean forward return > 0,
     with p < 0.05 across the deciles.
  2. Top decile mean forward return exceeds the random-pick control mean by
     more than the round-trip cost assumption below.
  3. The top decile still beats the control with its single best QUARTER
     removed. This is the specific check the breakout result failed, and it is
     in the rule because of that failure, not in spite of it.

Any other outcome is a fail. A partial pass is a fail. In particular, "the top
decile won but the ordering was noise" is a fail, because it is the shape of
an overfit cut-off and the pre-registration already closes score cut-offs
against this snapshot.

FAMILY SIZE: 1. One hypothesis, one horizon, one universe. Adding a second
horizon after seeing the first would raise the bar for both, so the horizon is
fixed at 20 sessions before running, matching the existing breakout test so the
two are readable side by side.

-----------------------------------------------------------------------------
WHAT IS CONTROLLED, AND WHAT CANNOT BE
-----------------------------------------------------------------------------
FILLS. The score is computed on session T's close. The earliest a human could
act is the OPEN of T+1, so entry is the T+1 open and exit is the open of
T+1+horizon. Close-to-close would flatter every momentum reading here and is
not obtainable.

COSTS. 0.35% round trip, charged to every arm including the controls. High-beta
names in this universe trade at wider spreads than megacaps, and the figure is
deliberately pessimistic rather than flattering.

CAUSALITY WITHIN A TICKER. Every factor is computed from a frame truncated at
T. `nearest_levels` already shifts swing points forward by the lookback so a
level exists only from the bar its third touch was confirmed.

SURVIVORSHIP, WHICH CANNOT BE FIXED HERE AND IS THEREFORE MEASURED AROUND.
The watchlist was built from symbols listed TODAY, screened on trailing beta.
Names that delisted are simply absent, and delistings skew towards losers. The
universe is biased upward and no amount of care inside this script removes it.

That is why the primary comparison is NOT against SPY. It is against a random
pick from the same universe on the same dates, which carries the identical
bias, so the difference between the arms measures the SCORE rather than the
universe. SPY is reported as well, and is the weaker of the two controls
precisely because it does not share the bias.

CROSS-SECTIONAL, NOT TIMING. Deciles are formed within each date, so every
decile trades on every date. This measures whether the score picks better
NAMES. It says nothing about whether it picks better DAYS, which is a separate
question the vault already has open and which this test is not asking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from score_watchlist import load_cache, read_watchlist  # noqa: E402

from stocksignal.config import DEFAULT_CONFIG as CFG  # noqa: E402
from stocksignal.scanner import build_quote  # noqa: E402
from stocksignal.scorecard import score_ticker  # noqa: E402
from stocksignal.screens.tradability import screen_tradability  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

HORIZON = 20          # sessions held, fixed before running
COST_PCT = 0.35       # round trip, charged to every arm
WARMUP = 440          # 180 SMA plus a 252-session level window
N_DECILES = 10
RANDOM_DRAWS = 40     # independent random picks per date, averaged
SEED = 20260817


def month_starts(index: pd.DatetimeIndex, first: int, last: int) -> list[int]:
    """Positions of the first session of each month inside the tradeable range."""
    out, seen = [], set()
    for pos in range(first, last):
        stamp = index[pos]
        key = (stamp.year, stamp.month)
        if key not in seen:
            seen.add(key)
            out.append(pos)
    return out


def main(cache_dir: Path) -> None:
    rng = np.random.default_rng(SEED)
    frames = load_cache(cache_dir)
    watchlist = set(read_watchlist(ROOT / "data" / "watchlist.txt"))
    bench = frames[CFG.beta_benchmark]
    bench_close = bench["close"]

    universe = [t for t in sorted(frames) if t in watchlist and len(frames[t]) >= WARMUP + HORIZON]
    print(f"universe {len(universe)} tickers")

    calendar = bench.index
    first = WARMUP
    last = len(calendar) - HORIZON - 2
    dates = month_starts(calendar, first, last)
    print(
        f"{len(dates)} monthly test dates, "
        f"{calendar[dates[0]].date()} to {calendar[dates[-1]].date()}"
    )

    rows = []
    for n, pos in enumerate(dates, 1):
        asof = calendar[pos]
        for t in universe:
            df = frames[t]
            sub = df.loc[:asof]
            if len(sub) < WARMUP:
                continue
            # Entry T+1 open, exit T+1+HORIZON open. Both must exist in this
            # ticker's own calendar, not the benchmark's.
            future = df.loc[df.index > asof]
            if len(future) < HORIZON + 1:
                continue
            entry = float(future["open"].iloc[0])
            exit_ = float(future["open"].iloc[HORIZON])
            if entry <= 0:
                continue
            try:
                quote = build_quote(t, sub, CFG, None, bench_close.loc[:asof])
                if not screen_tradability(sub, quote, CFG).passed:
                    continue
                card = score_ticker(sub, quote, CFG)
            except Exception:  # noqa: BLE001
                continue
            rows.append(
                {
                    "date": asof,
                    "ticker": t,
                    "score": card.score,
                    "coverage": card.coverage,
                    "ret": 100.0 * (exit_ - entry) / entry - COST_PCT,
                }
            )
        print(f"  {n}/{len(dates)} {asof.date()}  rows={len(rows)}", flush=True)

    data = pd.DataFrame(rows)
    data.to_csv(ROOT / "out" / "scorecard-backtest-rows.csv", index=False)
    print(f"\n{len(data)} observations across {data['date'].nunique()} dates")

    # Deciles formed WITHIN each date, so every decile trades on every date.
    data["decile"] = (
        data.groupby("date")["score"]
        .transform(lambda s: pd.qcut(s.rank(method="first"), N_DECILES, labels=False) + 1)
    )
    by_decile = data.groupby("decile")["ret"].agg(["mean", "median", "count"])
    by_decile["hit_rate"] = data.groupby("decile")["ret"].apply(lambda s: 100.0 * (s > 0).mean())

    # Random control: same dates, same universe, drawn from the same rows.
    control = []
    for asof, chunk in data.groupby("date"):
        pool = chunk["ret"].to_numpy()
        picks = rng.choice(pool, size=RANDOM_DRAWS, replace=True)
        control.append({"date": asof, "ret": float(picks.mean())})
    control_df = pd.DataFrame(control)
    control_mean = float(control_df["ret"].mean())

    # SPY over the identical windows.
    spy_rets = []
    for asof in sorted(data["date"].unique()):
        future = bench.loc[bench.index > asof]
        if len(future) < HORIZON + 1:
            continue
        e, x = float(future["open"].iloc[0]), float(future["open"].iloc[HORIZON])
        spy_rets.append(100.0 * (x - e) / e - COST_PCT)
    spy_mean = float(np.mean(spy_rets))

    # Rule 1: monotonicity.
    from scipy import stats  # noqa: PLC0415

    rho, pval = stats.spearmanr(by_decile.index.to_numpy(), by_decile["mean"].to_numpy())

    # Rule 3: top decile with its best quarter removed.
    top = data[data["decile"] == N_DECILES].copy()
    top["quarter"] = pd.PeriodIndex(top["date"], freq="Q")
    by_q = top.groupby("quarter")["ret"].mean()
    best_q = by_q.idxmax()
    top_ex_best = top[top["quarter"] != best_q]["ret"].mean()

    top_mean = float(by_decile.loc[N_DECILES, "mean"])
    bottom_mean = float(by_decile.loc[1, "mean"])

    rule1 = bool(rho > 0 and pval < 0.05)
    rule2 = bool(top_mean - control_mean > COST_PCT)
    rule3 = bool(top_ex_best > control_mean)

    print("\n" + "=" * 72)
    print(f"SCORECARD BACKTEST, horizon {HORIZON} sessions, costs {COST_PCT}% round trip")
    print("=" * 72)
    print(by_decile.round(3).to_string())
    print(f"\nrandom-pick control (same universe, same dates) : {control_mean:+.3f}%")
    print(f"SPY over the identical windows                  : {spy_mean:+.3f}%")
    print(f"top decile                                      : {top_mean:+.3f}%")
    print(f"bottom decile                                   : {bottom_mean:+.3f}%")
    print(f"top decile, best quarter ({best_q}) removed  : {top_ex_best:+.3f}%")
    print(f"\nSpearman rho {rho:+.3f}, p = {pval:.4f}")
    print(f"\n  rule 1 monotonic and significant  : {'PASS' if rule1 else 'FAIL'}")
    print(f"  rule 2 top beats control by cost  : {'PASS' if rule2 else 'FAIL'}")
    print(f"  rule 3 survives best-quarter drop : {'PASS' if rule3 else 'FAIL'}")
    print(f"\n  VERDICT: {'PASS' if (rule1 and rule2 and rule3) else 'FAIL'}")

    summary = {
        "horizon": HORIZON,
        "cost_pct": COST_PCT,
        "observations": int(len(data)),
        "dates": int(data["date"].nunique()),
        "tickers": int(data["ticker"].nunique()),
        "window": [str(data["date"].min().date()), str(data["date"].max().date())],
        "deciles": {
            int(k): {
                "mean": round(float(v["mean"]), 4),
                "median": round(float(v["median"]), 4),
                "count": int(v["count"]),
                "hit_rate": round(float(v["hit_rate"]), 2),
            }
            for k, v in by_decile.iterrows()
        },
        "control_mean": round(control_mean, 4),
        "spy_mean": round(spy_mean, 4),
        "top_mean": round(top_mean, 4),
        "bottom_mean": round(bottom_mean, 4),
        "top_ex_best_quarter": round(float(top_ex_best), 4),
        "best_quarter": str(best_q),
        "spearman_rho": round(float(rho), 4),
        "spearman_p": round(float(pval), 6),
        "rule1_monotonic": rule1,
        "rule2_beats_control": rule2,
        "rule3_survives_quarter_drop": rule3,
        "verdict": "PASS" if (rule1 and rule2 and rule3) else "FAIL",
    }
    (ROOT / "out" / "scorecard-backtest.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {ROOT / 'out' / 'scorecard-backtest.json'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache")
