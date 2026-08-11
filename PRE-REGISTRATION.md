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
**Status:** registered, not yet run.

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

Not yet run. This section is filled in after the run and not before.

The command, fixed here so the run cannot be quietly re-specified:

```
python scripts/measure_from_cache.py --screen breakout \
    --from 2021-09-01 --to 2026-08-10 --fit-end 2023-12-31 \
    --replicates 6000 --out out/breakout-backtest.txt
```

---

## 2. Gate 1 at 2:1, on data that does not exist yet

**Registered:** 10 August 2026.
**Scheduled:** February 2027.
**Status:** open. Do not run early.

Recorded here so the terms are in one place rather than only in a scheduled task.

- **Configuration:** gate 1 at 2:1, held to the horizon, no stops.
- **Statistic:** 20-session mean.
- **Family size 1, bar the 95th percentile.** A family of one is legitimate here
  and nowhere else in this project, because this test is fixed in advance and run
  once, on data that did not exist when the threshold was chosen.
- **Data:** sessions after 11 August 2026 only. The snapshot everything else was
  measured on is spent.
- **Fixed in advance:** if it fails, gate 1 is dropped rather than re-cut.

The whole value of this one is that the terms were set before the data existed.
Running it early, on any pretext, destroys the only test in the project with a
reachable bar.
