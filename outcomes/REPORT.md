# Signal outcomes, as of 2026-09-26

1361 signals in the ledger, 1136 with at least one finished horizon, 225 with nothing finished yet.

Every signal is scored as an equal-weight paper trade whether or not it was taken: the ledger records what the tool claimed, so this measures the tool. Costs of 0.2% are deducted once from the trade and never from the benchmark.

**Entry is the first price that existed after the digest did.** A signal published before the opening bell fills at the next open; one published after it fills at that session's close, which is the next price a reader could actually have paid. Here that is 533 trades filled at an open and 603 at a close. The split is computed per signal from the ledger's own clock, so it tracks whatever the scheduled scan actually does rather than what it is supposed to do.

**Read the median and the trimmed mean before the mean.** A mean that needs its best trades is a mean you cannot trade, because you do not know in advance which ones they are.

**No significance is claimed anywhere in this file.** Nothing here was pre-registered, no test was run, and the trades overlap heavily: dozens bought the same morning and held the same sessions are readings of one market move. Read it as a record of what happened, and look at the entry-day tables below before believing any average.

**The last row is a proxy and not your exit rule.** Page 107 says validation, the first candle holding below the 9 SMA, is not a concrete exit point: it is where you re-weigh the factors and decide. Selling on it is what can be scored without a person in the loop, so that is what the row measures. The rulebook's real exit needs a hard stop at a previous support level and a 5% trailing stop armed only after the price target is hit, and neither is decided yet: the support definition is the project's open question, and the tool deliberately publishes no price targets.

| horizon | trades | entry days | mean | median | trim best 5% | hit rate | SPY itself | excess vs SPY (mean / median) | VT itself | excess vs VT (mean / median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 sessions | 1048 | 24 |   -2.48% |   -3.31% |   -3.75% | 37% |   -0.24% |   -2.24% /   -3.17% |   -0.26% |   -2.22% /   -3.08% |
| 20 sessions | 467 | 9 |   -9.46% |  -11.38% |  -11.34% | 22% |   -1.27% |   -8.18% /  -10.41% |   -1.66% |   -7.80% /   -9.67% |
| 60 sessions | not yet elapsed | | | | | | | |
| sell on validation | 1097 | 28 |   -3.55% |   -3.25% |   -4.24% | 25% |   -0.34% |   -3.21% /   -2.88% |   -0.38% |   -3.17% /   -2.83% |

## The 20-session horizon, in words

These 467 trades were entered on 9 mornings, 2026-08-14 to 2026-08-26, so this is one window of market rather than a track record. It will read differently every month until the ledger covers several.
The average one lost to SPY by 8.18 points; the median one lost to it by 10.41.

## Every entry day at 20 sessions

One row here is one morning's worth of signals, which is one market move. Read the number of rows, not the number of trades, when judging how much any average above is worth.

| entry day | trades | mean | median | SPY itself | excess vs SPY |
|---|---:|---:|---:|---:|---:|
| 2026-08-14 | 94 |  -13.70% |  -15.28% |   -2.27% |  -11.43% |
| 2026-08-17 | 98 |  -15.32% |  -18.31% |   -2.42% |  -12.90% |
| 2026-08-18 | 105 |  -12.28% |  -15.15% |   -1.91% |  -10.37% |
| 2026-08-19 | 35 |   -7.50% |  -10.38% |   -1.01% |   -6.49% |
| 2026-08-20 | 28 |   -0.44% |   +1.99% |   -0.31% |   -0.13% |
| 2026-08-21 | 28 |   -1.85% |   -3.87% |   +1.22% |   -3.08% |
| 2026-08-24 | 30 |   +1.97% |   -0.70% |   +1.38% |   +0.60% |
| 2026-08-25 | 23 |   -2.21% |   -4.23% |   +0.46% |   -2.67% |
| 2026-08-26 | 26 |   -0.76% |   -7.00% |   +0.57% |   -1.33% |

## Every entry day at sell on validation

One row here is one morning's worth of signals, which is one market move. Read the number of rows, not the number of trades, when judging how much any average above is worth.

| entry day | trades | mean | median | SPY itself | excess vs SPY |
|---|---:|---:|---:|---:|---:|
| 2026-08-14 | 94 |   -4.94% |   -6.00% |   -1.29% |   -3.66% |
| 2026-08-17 | 98 |   -7.83% |   -8.42% |   -1.11% |   -6.73% |
| 2026-08-18 | 105 |   -4.44% |   -3.99% |   -0.15% |   -4.29% |
| 2026-08-19 | 35 |   -4.51% |   -5.09% |   -0.58% |   -3.93% |
| 2026-08-20 | 28 |   -0.07% |   -0.29% |   -0.02% |   -0.05% |
| 2026-08-21 | 28 |   -4.87% |   -4.76% |   -0.09% |   -4.78% |
| 2026-08-24 | 30 |   -4.09% |   -4.21% |   -0.01% |   -4.08% |
| 2026-08-25 | 23 |   -3.45% |   -3.84% |   -0.24% |   -3.20% |
| 2026-08-26 | 26 |   -5.21% |   -5.14% |   -0.02% |   -5.18% |
| 2026-08-28 | 66 |   -6.09% |   -5.69% |   -1.02% |   -5.06% |
| 2026-08-31 | 60 |   -2.83% |   -2.49% |   -0.55% |   -2.28% |
| 2026-09-01 | 28 |   -0.47% |   -0.19% |   +0.28% |   -0.75% |
| 2026-09-02 | 14 |   -2.28% |   -0.83% |   +0.04% |   -2.32% |
| 2026-09-03 | 14 |   -1.20% |   -0.03% |   -1.21% |   +0.01% |
| 2026-09-04 | 28 |   -3.03% |   -2.30% |   -0.87% |   -2.16% |
| 2026-09-08 | 41 |   -4.21% |   -4.55% |   -0.53% |   -3.68% |
| 2026-09-09 | 63 |   -4.87% |   -4.55% |   -0.11% |   -4.75% |
| 2026-09-10 | 68 |   -1.34% |   -0.27% |   +0.59% |   -1.93% |
| 2026-09-11 | 41 |   -5.31% |   -5.72% |   -0.48% |   -4.83% |
| 2026-09-14 | 51 |   +1.44% |   +1.13% |   -0.04% |   +1.48% |
| 2026-09-15 | 14 |   +1.07% |   +1.54% |   +0.74% |   +0.33% |
| 2026-09-16 | 14 |   +0.87% |   -0.11% |   +1.92% |   -1.04% |
| 2026-09-17 | 15 |   -2.08% |   -1.17% |   +0.88% |   -2.96% |
| 2026-09-18 | 25 |   -0.47% |   -0.35% |   +0.80% |   -1.28% |
| 2026-09-21 | 21 |   -2.74% |   -2.17% |   -0.60% |   -2.14% |
| 2026-09-22 | 24 |   -3.35% |   -2.58% |   -0.68% |   -2.67% |
| 2026-09-23 | 25 |   +0.44% |   -0.41% |   +0.00% |   +0.44% |
| 2026-09-24 | 18 |   +0.39% |   +0.47% |   +0.21% |   +0.19% |

## Data check: are these the prices the digest printed?

**Yes.** 1360 of 1361 signals match the close the digest recorded on the same date, within 0.5%. 0 could not be checked because the signal date is not in the returned history.

1 exception, which at this rate means a corrected bar rather than a broken join:

| ticker | date | digest said | bars say | gap |
|---|---|---:|---:|---:|
| AUGO | 2026-08-14 | 76.02 | 75.32 | -0.92% |

## By screen, at 20 sessions

Descriptive. A screen looking better here is not a reason to promote it: these are overlapping subsets of one small sample, and choosing among them after the fact is the search that the September pre-registration exists to prevent.

| screen | n | mean | median | trim best 5% | excess vs SPY | excess vs VT |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 1 |  -33.08% |  -33.08% |  -33.08% |  -30.81% |  -30.73% |
| trend | 456 |   -9.38% |  -11.63% |  -11.24% |   -8.11% |   -7.73% |

---

Benchmarks: **SPY**, like for like: US large caps over the same sessions; **VT**, the tracker gate: buy the world instead, proxy for VWRP.

Nothing here is financial advice or a verdict on any screen. It is a record of what the tool claimed and what happened next.
