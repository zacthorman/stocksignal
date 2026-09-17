"""Does COMBINING the indicators do anything? Searched on one half, tested once.

THE QUESTION AND WHY IT IS DANGEROUS. Nine elevating factors give 512 subsets,
and with a veto axis on top, 1,024 configurations. Run all of them on the same
five years that produced every other number in this project and the best one
will look excellent. That is arithmetic, not evidence: the expected maximum of
1,024 noisy estimates is large even when every single factor is worthless.

SO THE SEARCH AND THE TEST ARE SEPARATED, and the separation is enforced by
dates rather than good intentions.

  FIT       signal on or before FIT_END, and the trade also CLOSES by FIT_END,
            so nothing in the search has seen a price from the hold-out period.
            All 1,024 configurations are searched here. Nothing here is a result.
  HOLD-OUT  signal after FIT_END. Exactly ONE configuration is ever measured
            here, the fit winner, and it is measured once.

EVERY NUMBER BELOW IS FIXED BEFORE THE RUN. Eligibility MIN_FIT trades, the
selection statistic (mean excess over SPY per trade, net of costs), the
tie-break (more trades), the hold-out decision rule (MIN_HOLDOUT trades, mean
excess above zero, and a selection p-value under ALPHA). Change any of them
after seeing output and the run is exploratory, not a test, and must say so.

THE NULL IS BEST-OF-1,024, NOT BEST-OF-ONE. Comparing the winner against an
ordinary null would be comparing a maximum against a mean. So the whole search
is repeated on shuffled outcomes: the trades and their dates stay exactly as
they are, the (return, benchmark) pairs are dealt out at random, and the best
configuration under each shuffle is recorded. That distribution is what the
observed winner has to beat, and it is the only fair comparison available here.

THE HOLD-OUT P-VALUE IS A SELECTION TEST. A filter's job is to pick better than
average confirmations, so the null is a random handful of confirmations from the
same period, the same size. It is not a test against zero: in a rising market a
random handful is profitable, which is why SPY is subtracted everywhere.

OVERLAP THINNING IS PART OF THE CONFIGURATION, not of the data. A second trade
in a name is skipped while the first is still open, greedily in date order, as
in `factor_ledger.py`. Which trades those are depends on what the config
selects, so it is done per config and the count kept is reported.

WHAT THIS CANNOT ANSWER. Costs are a flat COST_PCT per trade with no slippage
model. There is no position sizing, so every trade counts equally. The universe
is whatever is in `cache/`, built from a watchlist that already reflects a point
of view. And all of it reads the same six years of the same bars as every
earlier test in this project.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")

from factor_events import DEPRECATING, ELEVATING  # noqa: E402

FIT_END = "2023-12-31"
MIN_FIT = 40
MIN_HOLDOUT = 20
ALPHA = 0.05
COST_PCT = 0.2
REPLICATES = 6000
SHUFFLES = 200
SEED = 20260917


def thin(idx: np.ndarray, ticker_code: np.ndarray, entry: np.ndarray, exit_: np.ndarray):
    """Greedy no-overlap, in date order, per ticker. Returns the kept indices."""
    keep = []
    busy: dict[int, int] = {}
    for j in idx:
        t = ticker_code[j]
        if entry[j] <= busy.get(t, -1):
            continue
        keep.append(j)
        busy[t] = exit_[j]
    return np.array(keep, dtype=int)


def configs() -> list[tuple[tuple[str, ...], bool]]:
    """Every subset of the elevating factors, with and without the veto."""
    out = []
    for r in range(len(ELEVATING) + 1):
        for combo in itertools.combinations(ELEVATING, r):
            out.append((combo, False))
            out.append((combo, True))
    return out


def select(df: pd.DataFrame, combo: tuple[str, ...], veto: bool) -> np.ndarray:
    mask = np.ones(len(df), dtype=bool)
    for f in combo:
        mask &= df[f].to_numpy(dtype=bool)
    if veto:
        for f in DEPRECATING:
            mask &= ~df[f].to_numpy(dtype=bool)
    return np.flatnonzero(mask)


def describe(combo: tuple[str, ...], veto: bool) -> str:
    body = " + ".join(combo) if combo else "(no factor required)"
    return f"{body}{' , zero deprecating' if veto else ''}"


def diagnostics(ev: pd.DataFrame, rows: np.ndarray, say) -> None:
    """Descriptive, and it CANNOT change the verdict. Registered rules decide.

    These are the four questions that killed the breakout result in August: is
    the typical trade any good, does the mean survive trimming, is it one
    quarter, is it three names. A mean that only exists in its own right tail is
    a mean you cannot trade, because you cannot know in advance which seven of
    138 trades you are allowed to skip.
    """
    x = ev.excess.to_numpy()[rows]
    srt = np.sort(x)
    drop = int(np.ceil(0.05 * len(x)))
    total = x.sum()
    say("CONCENTRATION (descriptive, decides nothing)")
    say(f"  mean {x.mean():+.2f}%   median {np.median(x):+.2f}%")
    say(f"  trim best 5% ({drop} trades) {srt[:-drop].mean():+.2f}%   "
        f"trim best 10% {srt[: -2 * drop].mean():+.2f}%")
    say(f"  top 5% of trades supply {srt[-drop:].sum() / total * 100:.0f}% of the excess, "
        f"the single best {srt[-1] / total * 100:.0f}%")
    sub = ev.loc[rows].copy()
    sub["q"] = pd.PeriodIndex(pd.to_datetime(sub.signal_date), freq="Q").astype(str)
    byq = sub.groupby("q").excess.agg(["count", "mean", "sum"])
    say(f"  quarters with a positive mean {(byq['mean'] > 0).sum()}/{len(byq)}   "
        f"biggest quarter supplies {byq['sum'].max() / total * 100:.0f}%")
    byt = sub.groupby("ticker").excess.sum().sort_values(ascending=False)
    say(f"  {len(byt)} names, top three supply {byt.head(3).sum() / total * 100:.0f}%: "
        f"{', '.join(byt.head(3).index)}")
    say("  by quarter: " + "  ".join(f"{q} n={r['count']:.0f} {r['mean']:+.1f}%"
                                     for q, r in byq.iterrows()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=Path, default=Path("out/factor-events.csv"))
    ap.add_argument("--out", type=Path, default=Path("out/factor-combination-search.txt"))
    args = ap.parse_args()

    ev = pd.read_csv(args.events)
    ev["excess"] = ev.ret_pct - COST_PCT - ev.spy_pct
    codes = pd.Categorical(ev.ticker).codes
    entry_bar = ev.entry_bar.to_numpy()
    exit_bar = ev.exit_bar.to_numpy()

    fit = ev.index[(ev.signal_date <= FIT_END) & (ev.exit_date <= FIT_END)].to_numpy()
    hold = ev.index[ev.signal_date > FIT_END].to_numpy()
    fit_set, hold_set = set(fit.tolist()), set(hold.tolist())

    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s)
        lines.append(s)

    say("FACTOR COMBINATION SEARCH")
    say(f"events {len(ev)}   fit {len(fit)} (signal and exit by {FIT_END})   hold-out {len(hold)}")
    say(f"selection: mean excess over SPY per trade, net of {COST_PCT}% costs, "
        f"eligible at {MIN_FIT}+ fit trades")
    say(f"decision:  hold-out needs {MIN_HOLDOUT}+ trades, excess above zero, "
        f"selection p < {ALPHA}")
    say()

    # Every config's kept trades, computed once. Thinning depends on the
    # selection and not on the returns, so the same indices serve every shuffle.
    kept_fit: dict[int, np.ndarray] = {}
    kept_hold: dict[int, np.ndarray] = {}
    cfgs = configs()
    for k, (combo, veto) in enumerate(cfgs):
        chosen = select(ev, combo, veto)
        kept = thin(chosen, codes, entry_bar, exit_bar)
        kept_fit[k] = np.array([j for j in kept if j in fit_set], dtype=int)
        kept_hold[k] = np.array([j for j in kept if j in hold_set], dtype=int)

    excess = ev.excess.to_numpy()

    def best_under(values: np.ndarray) -> tuple[int, float]:
        best_k, best_v, best_n = -1, -np.inf, -1
        for k in range(len(cfgs)):
            rows = kept_fit[k]
            if len(rows) < MIN_FIT:
                continue
            m = values[rows].mean()
            if m > best_v or (m == best_v and len(rows) > best_n):
                best_k, best_v, best_n = k, m, len(rows)
        return best_k, best_v

    winner, winner_fit_mean = best_under(excess)
    combo, veto = cfgs[winner]
    eligible = sum(1 for k in range(len(cfgs)) if len(kept_fit[k]) >= MIN_FIT)

    say(f"configurations searched {len(cfgs)}, eligible on the fit half {eligible}")
    say()
    say("WINNER ON THE FIT HALF (this is a search result and proves nothing)")
    say(f"  rule        {describe(combo, veto)}")
    say(f"  fit trades  {len(kept_fit[winner])}")
    say(f"  fit excess  {winner_fit_mean:+.2f}% per trade")
    say()

    # How good does the best of 1,024 look when nothing means anything?
    rng = np.random.default_rng(SEED)
    fit_rows = np.array(sorted(fit_set))
    shuffled_best = np.empty(SHUFFLES)
    for s in range(SHUFFLES):
        fake = excess.copy()
        perm = rng.permutation(fit_rows)
        fake[fit_rows] = excess[perm]
        _, v = best_under(fake)
        shuffled_best[s] = v
    p_search = float((shuffled_best >= winner_fit_mean).mean())
    say("THE SAME SEARCH ON SHUFFLED OUTCOMES (best-of-1,024 null)")
    say(f"  shuffles           {SHUFFLES}")
    say(f"  best by luck       median {np.median(shuffled_best):+.2f}%, "
        f"95th {np.quantile(shuffled_best, 0.95):+.2f}%, max {shuffled_best.max():+.2f}%")
    say(f"  observed best      {winner_fit_mean:+.2f}%   p = {p_search:.3f}")
    say("  Reading: a p above 0.05 here means the fit winner is what searching "
        "1,024 rules")
    say("  produces from noise, and the hold-out is unlikely to rescue it.")
    say()

    # THE ONE HOLD-OUT MEASUREMENT.
    rows = kept_hold[winner]
    say("HOLD-OUT, MEASURED ONCE")
    if len(rows) < MIN_HOLDOUT:
        say(f"  {len(rows)} trades, under the {MIN_HOLDOUT} required. NOT MEASURABLE.")
        verdict = "UNRESOLVED: too few hold-out trades"
    else:
        obs = excess[rows].mean()
        pool = excess[np.array(sorted(hold_set))]
        draws = np.array([rng.choice(pool, len(rows), replace=False).mean()
                          for _ in range(REPLICATES)])
        p_hold = float((draws >= obs).mean())
        wins = float((excess[rows] > 0).mean() * 100)
        say(f"  trades             {len(rows)}")
        say(f"  excess over SPY    {obs:+.2f}% per trade, net of costs")
        say(f"  raw return         {ev.ret_pct.to_numpy()[rows].mean() - COST_PCT:+.2f}%   "
            f"SPY over the same windows {ev.spy_pct.to_numpy()[rows].mean():+.2f}%")
        say(f"  hit rate           {wins:.1f}%   median hold "
            f"{np.median(ev.hold_days.to_numpy()[rows]):.0f}d")
        say(f"  random {len(rows)} of {len(pool)} confirmations: "
            f"mean {draws.mean():+.2f}%, 95th {np.quantile(draws, 0.95):+.2f}%")
        say(f"  selection p        {p_hold:.3f}")
        passed = obs > 0 and p_hold < ALPHA
        verdict = ("SIGNIFICANT by the rule fixed above" if passed
                   else "NOT SIGNIFICANT by the rule fixed above")
        say()
        diagnostics(ev, rows, say)
    say()
    say(f"VERDICT: {verdict}")
    say()

    # Pre-specified reference points, so the winner has something to sit next to.
    say("SAMPLE SHAPE, and it is not symmetric")
    for half, sel in (("fit", fit), ("hold-out", hold)):
        part = ev.loc[sel]
        say(f"  {half:<9} {len(part):>5} events, {part.ticker.nunique():>3} names, "
            f"{part.signal_date.min()} to {part.signal_date.max()}")
    say("  The watchlist in cache/ was built recently, so a name only enters the "
        "page 142")
    say("  universe once it cleared $15 and beta 2. The early half is a smaller, "
        "different market.")
    say()
    say("REFERENCE POINTS (specified before the run, not selected)")
    for label, (cmb, vt) in [
        ("every confirmation, no filter", ((), False)),
        ("zero deprecating only", ((), True)),
        ("Zac's rule: direction + macd, zero deprecating", (("direction", "macd"), True)),
    ]:
        k = cfgs.index((cmb, vt))
        f_rows, h_rows = kept_fit[k], kept_hold[k]
        f_m = excess[f_rows].mean() if len(f_rows) else float("nan")
        h_m = excess[h_rows].mean() if len(h_rows) else float("nan")
        say(f"  {label:<46} fit {len(f_rows):>5} trades {f_m:+6.2f}%   "
            f"hold-out {len(h_rows):>5} trades {h_m:+6.2f}%")
    say()
    say("TOP 10 ON THE FIT HALF, printed so the search is visible rather than "
        "just its winner.")
    say("None of these are results. The hold-out above is the only measurement.")
    ranked = sorted(
        (k for k in range(len(cfgs)) if len(kept_fit[k]) >= MIN_FIT),
        key=lambda k: -excess[kept_fit[k]].mean(),
    )[:10]
    for k in ranked:
        cmb, vt = cfgs[k]
        say(f"  {excess[kept_fit[k]].mean():+6.2f}%  n={len(kept_fit[k]):>4}  "
            f"{describe(cmb, vt)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"\nwritten {args.out}")


if __name__ == "__main__":
    main()
