# Pre-registration

Tests written down **before** they were run, with the decision rule fixed in
advance. Committed as its own file so the timestamps are in the git history and
not in anybody's memory.

The reason this file exists is on the record in the README: this project has
already run 24 percentile tests against one six-year snapshot, and a bar chosen
after seeing a number is not a bar. Writing the terms down first is the cheapest
protection against the most common way a backtest lies to the person who built
it.

Rules for this file:

- A test gets written here **before its first run on the data it will be judged
  on**. Building the code and checking it against the screen is not a run; a run
  is anything that produces a return.
- The decision rule, the family size and the reporting commitment are fixed at
  the same time. None of them may be revised once a result is known.
- The result gets written back under the same heading, whatever it says.

---

## 1. The breakout screen, three-touch level with a held retest

**Registered:** 11 August 2026, before the first measured run.
**Status:** run on 11 August 2026. Result below. Closed — no further variants.

### The hypothesis

Given the dates it fires on, the breakout screen picks names that outperform
other names drawn from the same universe on the same dates.

That is narrower than "the breakout rules work", and deliberately so. The
control takes the same number of names on the same dates, so every control
inherits whatever the screen knew about *when* to trade. A strategy whose edge
was timing or breadth scores 50 here regardless of how good it is. What is being
tested is name selection, which is what a cross-sectional screen advertises.

### The screen, exactly as it will run

`screens/breakout.py` at commit `b089624` plus the uncommitted rebuild of 11
August, with two corrections made while building the harness and committed
before this registration:

- a `ZeroDivisionError` when the baby bar has no body, which crashed the screen
  on a shape the data contains 6,380 times across six years;
- a duplicated `_normalise` definition, no behaviour change.

Gates, all required: a three-touch resistance level that price has genuinely been
below, broken within 5 sessions, the break retested and held, and the close above
the 180-period average. Volume spike, three-bar setup and level recency score but
do not gate; an overbought RSI deducts but does not reject.

No parameter is tuned for this test. Every threshold is the committed default.

### Universe, dates, execution

| | |
|---|---|
| Candidate pool | 267 tickers from `cache/*_1500d.csv`, the frozen snapshot |
| Benchmark | SPY, same snapshot |
| Window | 2021-09-01 to 2026-08-10, 1,239 sessions |
| Mean tradeable universe | 56.2 names per session |
| Calibration split | 2023-12-31; only results after it are quoted |
| Entry | next session's **open** after the signal |
| Exit | held to the horizon, 5, 10 and 20 sessions |
| Costs | 0.2% round trip |
| Thinning | one trade per ticker per 20 sessions, control thinned identically |

### Sample size, counted before any return was computed

731 raw signals, 246 after thinning, **192 of them out of sample**, across 115
distinct tickers. Counted with `--count-only`, which stops before the first
return is calculated, because the power statement below needs the sample size
and nothing about the sample size hints at the answer.

### The statistic and the decision rule

Primary: the **20-session mean**, out of sample, against 6,000 redrawn controls.
Reported alongside: 5 and 10 sessions, median and 5%-trimmed mean, and the tail
lift.

6,000 replicates rather than the usual 200 because the corrected bar sits at the
99.81st percentile and 200 draws cannot resolve a percentile that fine —
`NullTest.resolvable` needs about 5,400. Running 200 and printing "100%" would be
an artefact of the number of dice rolls.

**Family size 27, so the bar is the 99.81st percentile.** This test is the 9th
configuration run against this same snapshot, and it inherits the multiplicity of
the other eight. `TESTS_RUN` was raised from 24 to 27 in the same commit as the
harness, before the run.

**Stated in advance: that bar is very probably unreachable, and failing it will
not be reported as a negative result.** The README already records what happened
the last time this project measured against an unreachable bar and called the
failure a finding. So `detectable_effect` is reported next to the result, and if
the observed effect sits below it, the honest description is *the run could not
resolve this*, not *the screen does not work*.

Secondary, and labelled as descriptive rather than as evidence: the raw
uncorrected percentile.

### What happens next, fixed now

- Whatever comes back is written into the README as the headline for the breakout
  screen. Including if it is dull.
- **No further breakout variants get run against this snapshot.** Not a different
  retest window, not the 3-bar setup as a gate, not a score cut-off. If the
  result looks promising, the correct response is to add the breakout screen to
  the February 2027 pre-registered test on fresh data, not to slice this data
  again. Every extra variant raises the bar for everything already run.
- If the run is unresolvable, that is reported as the result, and the design
  question — this screen fires 192 times in five years, which may simply be too
  few to measure — is reported with it.

### Result

Run 11 August 2026. Full report in `out/breakout-backtest.txt`. The command, as
registered:

```
python scripts/measure_from_cache.py --screen breakout \
    --from 2021-09-01 --to 2026-08-10 --fit-end 2023-12-31 \
    --replicates 6000 --out out/breakout-backtest.txt
```

178 out-of-sample trades across 93 names. 246 survived thinning and 192 fell out
of sample; 178 of those had a next open to buy at and a horizon that finished
before the data did.

**The declared bar was not cleared, and the run could not have cleared it.**

| Horizon | Screens mean | Controls | Beats | Detectable effect | Observed |
|---|---|---|---|---|---|
| 5 | +0.58% | +0.48% | 56% | 2.13 pts | +0.10 |
| 10 | +2.49% | +1.63% | 79% | 3.02 pts | +0.86 |
| 20 | +5.18% | +3.54% | 83% | 4.68 pts | +1.65 |

Underpowered, not negative, in the sense fixed in advance: at every horizon the
observed effect is a third to a half of what this run could have certified. Same
shape as gate 1.

**The finding is not in the mean, and this is the part worth reading.** The
20-session mean of 5.18% against a control's 1.55% is the best-looking number
this project has produced, and it does not survive being looked at:

| 20 sessions | screens | random |
|---|---|---|
| mean | +5.18% | +1.55% |
| median, the typical trade | **-0.04%** | **+0.31%** |
| hit rate | **49.7%** | **54.3%** |
| mean, best 5% of trades removed | +0.13% | -0.20% |

The best 5% of trades supply **5.05 of the 5.18 points**. The typical breakout
trade loses slightly, and loses by slightly more than a name drawn out of a hat
would have. The screen wins less often than chance at all three horizons and
wins bigger when it wins.

That is a right-skewed, lottery-ticket return profile, and the honest thing to
say about it cuts both ways. It is exactly the shape a breakout strategy is
supposed to have — you take many small losses waiting for the move that runs —
so the skew is not evidence against the method. But it is also the shape that a
mean cannot measure and 178 trades cannot resolve, because everything rests on a
handful of trades in the tail, and how many of those you got is mostly luck.

The trimmed-mean statistic in this harness was built to ask "is this apparent
edge really a handful of outsized winners". Here the answer is yes, unambiguously,
and it is the first time the question has changed the reading.

In sample, for completeness and not to be quoted: the screens LOSE to the control
badly (-0.35% against +2.65% at 20 sessions on 54 trades). Small sample, fitted
period, no weight either way — but it is not a result that would look better if
the hold-out had gone the other way, and it is recorded rather than dropped.

### What this closes

- No further breakout variants against this snapshot, as fixed above. The
  temptation is real — a 5.18% mean invites one more slice looking for the
  subset that produces the tail — and that is precisely the move this file
  exists to prevent.
- The breakout screen keeps running in the daily digest. Nothing here says it is
  broken; it says this data cannot tell whether it works.
- **Added to the February 2027 test.** A tail effect needs either far more trades
  or a much longer window, and fresh data is the only honest source of either.

---

## 2. Gate 1 at 2:1, on data that does not exist yet

**Registered:** 10 August 2026.
**Scheduled:** February 2027.
**Status:** open. Do not run early.

Recorded here so the terms are in one place rather than only in a scheduled task.

- **Configurations, now two:**
  1. gate 1 at 2:1, held to the horizon, no stops. Statistic: 20-session mean.
  2. the breakout screen, held to the horizon. Statistic: 20-session mean AND
     the 20-session mean with the best 5% of trades removed, because the August
     run showed the plain mean is entirely tail and the trimmed mean is the one
     that would distinguish a real edge from a lucky handful.
- **Family size 2, bar the 97.5th percentile**, up from a family of one at 95%.
  Adding the breakout screen costs gate 1 some significance and that is the
  correct price. Recorded here on the day the second test was added rather than
  in February, so the bar cannot drift once numbers exist.
- **Data:** sessions after 11 August 2026 only. The snapshot everything else was
  measured on is spent.
- **Fixed in advance:** if gate 1 fails, it is dropped rather than re-cut. If the
  breakout screen's trimmed mean is not above its control, the tail is luck and
  the screen becomes a monitor rather than an entry signal.
- **Known weakness, stated now:** six months of fresh data will produce roughly
  20 breakout trades, which is nowhere near enough to resolve a tail effect. This
  test will probably also come back underpowered, and if it does, the answer is
  to keep waiting rather than to lower the bar. Two years is a more realistic
  horizon for this particular question than six months.

The whole value of this one is that the terms were set before the data existed.
Running it early, on any pretext, destroys the only test in the project with a
reachable bar.

---

## 3. Do the indicators do anything in combination? (registered 2026-09-17)

Registered before the search was run, and before any combination number was
looked at. Zac asked the question in the form it is usually asked in — "does
combining them make it significant" — which is the form that manufactures
findings. This is the version that can answer no.

### The hypothesis

Some combination of the nine price-bar factors in `factor_ledger.py` selects
confirmation bars that go on to beat SPY by more than the confirmation bars it
rejects, out of sample, after costs.

### The search, exactly as it will run

- **Events.** Every first candle opening above the 9 SMA inside the page 142
  universe, entry at the next open, exit at the first open below the 9 SMA
  (filled the following open), 252-session cap. Built once by
  `scripts/factor_events.py`. 7,562 events, 247 tickers, 2021-08-23 to
  2026-08-07.
- **Configurations.** All 512 subsets of the nine elevating factors, each with
  and without a veto on all six deprecating factors. 1,024 in total.
- **Split.** Fit is every event whose signal AND exit fall on or before
  2023-12-31. Hold-out is every event with a signal after it. The fit half
  therefore never sees a hold-out price.
- **Eligibility.** 40 or more fit trades. Below that a configuration is not
  ranked at all.
- **Selection statistic.** Mean excess over SPY per trade, net of 0.2% costs,
  over the same window as each trade. Tie-break: more trades.
- **Overlap.** One open trade per ticker at a time, greedy in date order.

### The decision rule, fixed now

The single fit winner is measured **once** on the hold-out. It counts as
significant only if all three hold:

1. 20 or more hold-out trades.
2. Mean excess above zero.
3. Selection p below 0.05, where the null is a random draw of the same number
   of hold-out confirmations from the same period.

Anything else is reported as not significant. No second configuration gets a
hold-out measurement, no threshold moves afterwards, and the top ten fit
configurations are printed so the search is visible rather than just its winner.

### The best-of-1,024 null

The whole search is repeated 200 times with the (return, SPY) pairs dealt out at
random across the fit events, recording the best configuration each time. The
observed fit winner is reported against that distribution. This is the number
that says how much of any winner is the search itself.

### What happens next, fixed now

- The result goes into the README and the project dashboard **whatever it says**,
  including if the answer is that nothing survives.
- **No further combination variants get run against this snapshot.** Not a
  different exit, not a different horizon, not a different factor definition, not
  a threshold on the number of factors. If something looks promising the correct
  response is a fresh pre-registered test on data that does not exist yet.
- If the winner fails the hold-out, the honest reading is that these nine
  factors, on these bars, do not combine into an edge. That is an answer and it
  is allowed to be the answer.

### Result

Run 17 September 2026. Full report in `out/factor-combination-search.txt`.

```
python scripts/factor_events.py
python scripts/factor_search.py
```

**It passes, and the passing is the least interesting thing about it.**

| | |
|---|---|
| Configurations searched | 1,024, of which 65 had 40+ fit trades |
| Fit winner | `macd + direction_tested + vol_squeeze`, 60 trades, +4.29% excess |
| Best-of-1,024 null | median +1.51%, 95th +3.33%. Observed p = 0.015 |
| Hold-out | 138 trades, **+3.35% excess per trade**, selection p = 0.011 |
| Verdict by the registered rule | **SIGNIFICANT** |

And then the diagnostics, which were not part of the decision rule and do not
change the verdict:

- **Median excess −1.11%.** The typical trade loses to SPY. The mean is positive
  because seven trades out of 138 supply **92%** of the excess, and one of them,
  GRAL, supplies 26% by itself.
- **Trim the best 5% and it is +0.27%. Trim the best 10% and it is −1.04%.**
- **2025Q2 and 2025Q3 supply essentially all of it.** 2024 is negative in three
  quarters of four, 2026 is flat, and 6 of 11 quarters have a positive mean.
- Three names out of 66 supply 55%.

**The registered statistic was the mean, and that was my choice and a poor one.**
The mean is precisely what a fat right tail flatters, and this project already
knew that: it is the same shape that killed the breakout screen in August, where
the best 5% of trades supplied 5.05 of 5.18 points. A rule passing a
pre-registered test and still being untradeable is not a contradiction. It means
the test asked whether the average was positive when the question worth asking
was whether the typical trade was.

**The sample is also not symmetric.** The fit half has 1,665 events across 80
names; the hold-out has 5,872 across 247. The watchlist in `cache/` was built
recently, so a name only enters the page 142 universe once it cleared $15 and
beta 2, and the early half is a smaller and different market. The selection
p-value is immune to this, since it compares the rule against random
confirmations from the same period, but any comparison between the two halves is
not.

**What this closes.** Per the registration, no further combination variants get
run against this snapshot: not a different exit, not a different horizon, not a
threshold on factor count. The honest summary is that combining these nine
price-bar factors produced a rule whose edge lives in seven trades in two
quarters of 2025, which is the shape of something that does not repeat.

**What it opens, and it needs its own registration before anything is run.** If
the question is worth asking again, the statistic should be the median or a
trimmed mean fixed in advance, the test should run forward on signals that did
not exist when the rule was chosen, and the committed ledger in `signals/` is
now capable of supplying exactly that.

