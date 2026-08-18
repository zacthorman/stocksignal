"""Does moving the stop off the support level fix the 77% shakeout?

PRE-REGISTERED. Written and committed before its first run on this data, and
none of the decision rule, the family size or the reporting commitment is
revised once a result is known.

-----------------------------------------------------------------------------
WHY THIS TEST AND NOT ANOTHER
-----------------------------------------------------------------------------
Section E of `Trading Strategy & Screens.md` records that gate 1 at 2:1 plus the
course's own stop (page 234, at the previous support level) stopped out 77% of
trades against a 57% control, and moved the same screen from the 96th
percentile to the 10th. Only the exit differed.

That finding was left as a known contradiction between two rules. This asks
whether the obvious fix works: place the stop from the name's own volatility
instead of from a support level, so it sits outside ordinary daily noise BY
CONSTRUCTION rather than by luck.

The entries are held identical across every arm. Only the exit changes. Any
difference is therefore the exit and nothing else, which is the one thing the
original finding could not fully isolate.

-----------------------------------------------------------------------------
THE HYPOTHESIS, AND ONLY ONE
-----------------------------------------------------------------------------
H1: an ATR-based stop beats the course's support-based stop on the same entries.

FAMILY SIZE: 1. Four stop rules are RUN but only one comparison is tested. The
"wider" and "percent" arms are reported descriptively and are not eligible to be
declared winners, because letting the best of four rules count as a result is
the multiple-comparisons problem wearing a disguise. If ATR loses, the answer is
that ATR loses, not that percent happened to win.

-----------------------------------------------------------------------------
THE DECISION RULE, FIXED BEFORE RUNNING
-----------------------------------------------------------------------------
H1 PASSES only if all three hold:

  1. The ATR arm's stop-out rate is at least 10 percentage points below the
     support arm's. A smaller gap is noise at this sample size.
  2. The ATR arm's mean return after costs exceeds the support arm's.
  3. It still does so with the single best quarter removed from BOTH arms.
     Same guard as the scorecard test, and in for the same reason: this project
     has now found three results living in one quarter.

Anything else is a fail. A partial pass is a fail.

REPORTING COMMITMENT: the stop-out rate, mean, median, hit rate AND the loss
tail (worst trade, 5th percentile, share of trades below -30%) of every arm get
printed whatever the verdict, including arms not eligible to win and the
hold-to-horizon control that uses no stop at all.

THE TAIL IS REPORTED, NOT TESTED. Mean return is not what a stop is for: a stop
trades expected return for a smaller left tail, so judging one on mean alone
answers a question nobody asked. The tail numbers are therefore in the report
from the start, but they are NOT part of the decision rule above and no result
may be claimed from them in this run. If they suggest a hypothesis, that
hypothesis gets pre-registered and tested on data this run has not touched.
That is the whole point of writing the rule down first.

-----------------------------------------------------------------------------
WHAT IS CONTROLLED
-----------------------------------------------------------------------------
FILLS. Entry at the T+1 open, because the screen reads T's close overnight. A
gap through the stop fills at the OPEN, not at the stop price, because the stop
price is a fill nobody gets on a gap.

INTRABAR. On a bar touching both stop and target, the STOP is assumed to have
hit first. Daily bars cannot say, and the optimistic assumption manufactures
winners out of ambiguity.

COSTS. 0.35% round trip on every arm including the control.

SURVIVORSHIP. Unfixable here and identical across arms, which is why this test
compares arms to each other rather than to an absolute bar. It is the one design
where the bias genuinely cancels.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from score_watchlist import load_cache, read_watchlist  # noqa: E402

from stocksignal.config import DEFAULT_CONFIG as CFG  # noqa: E402
from stocksignal.config import Config  # noqa: E402
from stocksignal.exits import Position, walk  # noqa: E402
from stocksignal.indicators import sma  # noqa: E402
from stocksignal.levels import nearest_levels  # noqa: E402
from stocksignal.position import place_stop  # noqa: E402
from stocksignal.scanner import build_quote  # noqa: E402
from stocksignal.screens.tradability import screen_tradability  # noqa: E402

HORIZON = 60  # sessions held at most, fixed before running
COST_PCT = 0.35
WARMUP = 440
ARMS = ("atr", "support", "percent")
"""The "wider" rule (two support levels below, page 234's alternative for a name
you are highly bullish on) was in the first run and produced results identical
to "support", because this script never supplied a second level and the rule
falls back. That is a defect in the harness rather than a finding, and an arm
that silently duplicates another is worse than a missing one, so it is removed
until `nearest_levels` can return a second level down."""
TESTED = ("atr", "support")  # the only pair the hypothesis is about


def month_starts(index: pd.DatetimeIndex, first: int, last: int) -> list[int]:
    out, seen = [], set()
    for pos in range(first, last):
        key = (index[pos].year, index[pos].month)
        if key not in seen:
            seen.add(key)
            out.append(pos)
    return out


def run_arm(future: pd.DataFrame, entry: float, stop: float, target: float | None,
            cfg: Config) -> tuple[float, str]:
    """One arm's outcome: return after costs, and how it ended."""
    pos = Position(ticker="x", entry=entry, stop=stop, target=target)
    walk(future, pos, cfg, max_bars=HORIZON)
    if pos.exit_price is not None:
        return 100.0 * (pos.exit_price - entry) / entry - COST_PCT, pos.exit_reason
    close = float(future["close"].iloc[min(HORIZON, len(future)) - 1])
    return 100.0 * (close - entry) / entry - COST_PCT, "HORIZON"


def main(cache_dir: Path) -> None:
    frames = load_cache(cache_dir)
    watchlist = set(read_watchlist(ROOT / "data" / "watchlist.txt"))
    bench = frames[CFG.beta_benchmark]
    bench_close = bench["close"]
    universe = [t for t in sorted(frames) if t in watchlist and len(frames[t]) >= WARMUP + HORIZON]
    calendar = bench.index
    dates = month_starts(calendar, WARMUP, len(calendar) - HORIZON - 2)
    print(f"{len(universe)} tickers, {len(dates)} monthly dates", flush=True)

    rows = []
    for n, pos_i in enumerate(dates, 1):
        asof = calendar[pos_i]
        for t in universe:
            df = frames[t]
            sub = df.loc[:asof]
            if len(sub) < WARMUP:
                continue
            future = df.loc[df.index > asof]
            if len(future) < HORIZON + 1:
                continue
            try:
                quote = build_quote(t, sub, CFG, None, bench_close.loc[:asof])
                if not screen_tradability(sub, quote, CFG).passed:
                    continue
                # A deliberately plain entry: above both SMAs. The point is to
                # isolate the exit, so the entry must not be the clever part.
                close = sub["close"]
                fast = float(sma(close, CFG.sma_fast).iloc[-1])
                slow = float(sma(close, CFG.sma_slow).iloc[-1])
                price = float(close.iloc[-1])
                if not (price > fast > slow):
                    continue

                levels = nearest_levels(sub, CFG)
                row = levels.iloc[-1] if len(levels) else None
                support = None if row is None else float(row.get("support", np.nan))
                resistance = None if row is None else float(row.get("resistance", np.nan))
                support = None if support is None or not np.isfinite(support) else support
                target = (
                    None if resistance is None or not np.isfinite(resistance) else resistance
                )
                entry = float(future["open"].iloc[0])
                if entry <= 0:
                    continue

                record = {"date": asof, "ticker": t, "entry": entry}
                ok = True
                for arm in ARMS:
                    cfg = Config(stop_rule=arm)
                    stop, _, _ = place_stop(sub, entry, cfg, support=support)
                    if stop is None or stop >= entry:
                        ok = False
                        break
                    ret, how = run_arm(future, entry, stop, target, cfg)
                    record[f"{arm}_ret"] = ret
                    record[f"{arm}_exit"] = how
                    record[f"{arm}_dist"] = 100.0 * (entry - stop) / entry
                if not ok:
                    continue
                # The control: no stop at all, held to the horizon.
                close_h = float(future["close"].iloc[HORIZON - 1])
                record["hold_ret"] = 100.0 * (close_h - entry) / entry - COST_PCT
                rows.append(record)
            except Exception:  # noqa: BLE001
                continue
        print(f"  {n}/{len(dates)} {asof.date()}  rows={len(rows)}", flush=True)

    data = pd.DataFrame(rows)
    if data.empty:
        raise SystemExit("no rows: every name lacked a support level, which is itself a finding")
    data.to_csv(ROOT / "out" / "exits-backtest-rows.csv", index=False)
    data["quarter"] = pd.PeriodIndex(data["date"], freq="Q")

    summary = {}
    for arm in ARMS:
        ret = data[f"{arm}_ret"]
        stopped = (data[f"{arm}_exit"] == "STOP").mean()
        summary[arm] = {
            "mean": float(ret.mean()),
            "median": float(ret.median()),
            "hit_rate": float((ret > 0).mean() * 100),
            "stop_out_rate": float(stopped * 100),
            "mean_stop_distance": float(data[f"{arm}_dist"].mean()),
            "median_stop_distance": float(data[f"{arm}_dist"].median()),
            "worst": float(ret.min()),
            "p05": float(ret.quantile(0.05)),
            "share_below_minus_30": float((ret < -30).mean() * 100),
        }
    hold = data["hold_ret"]
    summary["hold"] = {
        "mean": float(hold.mean()),
        "median": float(hold.median()),
        "hit_rate": float((hold > 0).mean() * 100),
        "stop_out_rate": 0.0,
        "mean_stop_distance": float("nan"),
        "median_stop_distance": float("nan"),
        "worst": float(hold.min()),
        "p05": float(hold.quantile(0.05)),
        "share_below_minus_30": float((hold < -30).mean() * 100),
    }

    # Rule 3: drop the best quarter from BOTH tested arms, chosen on the
    # support arm so the choice cannot be made to flatter ATR.
    best_q = data.groupby("quarter")["support_ret"].mean().idxmax()
    trimmed = data[data["quarter"] != best_q]
    atr_ex = float(trimmed["atr_ret"].mean())
    sup_ex = float(trimmed["support_ret"].mean())

    r1 = summary["support"]["stop_out_rate"] - summary["atr"]["stop_out_rate"] >= 10.0
    r2 = summary["atr"]["mean"] > summary["support"]["mean"]
    r3 = atr_ex > sup_ex
    verdict = "PASS" if (r1 and r2 and r3) else "FAIL"

    print("\n" + "=" * 74)
    print(f"EXIT RULES, {len(data)} entries, horizon {HORIZON} sessions, costs {COST_PCT}%")
    print("=" * 74)
    print(f"{'arm':9s} {'stop':>7} {'stopped':>8} {'mean':>8} {'median':>8} "
          f"{'hit':>6} {'worst':>8} {'5th pct':>8} {'<-30%':>7}")
    for arm in [*ARMS, "hold"]:
        v = summary[arm]
        d = "none" if arm == "hold" else f"{v['median_stop_distance']:.0f}%"
        tag = "" if arm in TESTED or arm == "hold" else "  (not eligible)"
        print(f"{arm:9s} {d:>7} {v['stop_out_rate']:7.0f}% {v['mean']:7.2f}% "
              f"{v['median']:7.2f}% {v['hit_rate']:5.0f}% {v['worst']:7.1f}% "
              f"{v['p05']:7.1f}% {v['share_below_minus_30']:6.1f}%{tag}")
    print("\nStop distance is the median, because the mean is dragged by a long "
          "right tail on the support rule.")
    print("The last three columns are the loss tail. They are REPORTED, not tested: "
          "no claim\nis made from them in this run, per the pre-registration.")

    print(f"\nbest quarter for the support arm: {best_q}, removed from both for rule 3")
    print(f"  atr without it     {atr_ex:+.2f}%")
    print(f"  support without it {sup_ex:+.2f}%")
    print(f"\n  rule 1 stop-out rate at least 10pp lower : {'PASS' if r1 else 'FAIL'}")
    print(f"  rule 2 mean return higher                : {'PASS' if r2 else 'FAIL'}")
    print(f"  rule 3 survives best-quarter removal     : {'PASS' if r3 else 'FAIL'}")
    print(f"\n  VERDICT: {verdict}")

    out = {
        "entries": int(len(data)),
        "horizon": HORIZON,
        "cost_pct": COST_PCT,
        "window": [str(data["date"].min().date()), str(data["date"].max().date())],
        "arms": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in summary.items()},
        "tested_pair": list(TESTED),
        "best_quarter_removed": str(best_q),
        "atr_ex_best": round(atr_ex, 4),
        "support_ex_best": round(sup_ex, 4),
        "rule1_stopout_gap": r1,
        "rule2_mean_higher": r2,
        "rule3_survives": r3,
        "verdict": verdict,
    }
    (ROOT / "out" / "exits-backtest.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {ROOT / 'out' / 'exits-backtest.json'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cache")
