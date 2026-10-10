# Signal outcomes, as of 2026-10-10

1905 signals in the ledger, 1766 with at least one finished horizon, 139 with nothing finished yet.

Every signal is scored as an equal-weight paper trade whether or not it was taken: the ledger records what the tool claimed, so this measures the tool. Costs of 0.2% are deducted once from the trade and never from the benchmark.

**Entry is the first price that existed after the digest did.** A signal published before the opening bell fills at the next open; one published after it fills at that session's close, which is the next price a reader could actually have paid. Here that is 533 trades filled at an open and 1233 at a close. The split is computed per signal from the ledger's own clock, so it tracks whatever the scheduled scan actually does rather than what it is supposed to do.

**Read the median and the trimmed mean before the mean.** A mean that needs its best trades is a mean you cannot trade, because you do not know in advance which ones they are.

**No significance is claimed anywhere in this file.** Nothing here was pre-registered, no test was run, and the trades overlap heavily: dozens bought the same morning and held the same sessions are readings of one market move. Read it as a record of what happened, and look at the entry-day tables below before believing any average.

**The last row is a proxy and not your exit rule.** Page 107 says validation, the first candle holding below the 9 SMA, is not a concrete exit point: it is where you re-weigh the factors and decide. Selling on it is what can be scored without a person in the loop, so that is what the row measures. The rulebook's real exit needs a hard stop at a previous support level and a 5% trailing stop armed only after the price target is hit, and neither is decided yet: the support definition is the project's open question, and the tool deliberately publishes no price targets.

| horizon | trades | entry days | mean | median | trim best 5% | hit rate | SPY itself | excess vs SPY (mean / median) | VT itself | excess vs VT (mean / median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 sessions | 1653 | 34 |   -1.58% |   -1.63% |   -2.74% | 42% |   -0.02% |   -1.57% /   -1.72% |   -0.21% |   -1.38% /   -1.43% |
| 20 sessions | 893 | 19 |   -2.89% |   -5.33% |   -5.06% | 40% |   -0.15% |   -2.75% /   -5.34% |   -1.09% |   -1.81% /   -4.37% |
| 60 sessions | not yet elapsed | | | | | | | |
| sell on validation | 1665 | 37 |   -2.70% |   -2.32% |   -3.42% | 32% |   -0.10% |   -2.60% /   -2.18% |   -0.30% |   -2.40% /   -1.91% |

## The 20-session horizon, in words

These 893 trades were entered on 19 mornings, 2026-08-14 to 2026-09-11, so this is one window of market rather than a track record. It will read differently every month until the ledger covers several.
The average one lost to SPY by 2.75 points; the median one lost to it by 5.34.

## Every entry day at 20 sessions

One row here is one morning's worth of signals, which is one market move. Read the number of rows, not the number of trades, when judging how much any average above is worth.

| entry day | trades | mean | median | SPY itself | excess vs SPY |
|---|---:|---:|---:|---:|---:|
| 2026-08-14 | 94 |  -13.70% |  -15.28% |   -2.27% |  -11.43% |
| 2026-08-17 | 98 |  -15.32% |  -18.31% |   -2.42% |  -12.90% |
| 2026-08-18 | 105 |  -12.28% |  -15.15% |   -1.91% |  -10.37% |
| 2026-08-19 | 35 |   -7.50% |  -10.38% |   -1.01% |   -6.49% |
| 2026-08-20 | 28 |   -0.44% |   +1.97% |   -0.31% |   -0.13% |
| 2026-08-21 | 28 |   -1.86% |   -3.87% |   +1.22% |   -3.08% |
| 2026-08-24 | 30 |   +1.97% |   -0.72% |   +1.38% |   +0.60% |
| 2026-08-25 | 23 |   -2.21% |   -4.23% |   +0.46% |   -2.68% |
| 2026-08-26 | 26 |   -0.76% |   -7.02% |   +0.57% |   -1.33% |
| 2026-08-28 | 66 |   +2.04% |   +3.27% |   -0.55% |   +2.59% |
| 2026-08-31 | 60 |   +7.12% |   +6.64% |   -0.12% |   +7.25% |
| 2026-09-01 | 28 |   +6.18% |   +6.89% |   +0.36% |   +5.82% |
| 2026-09-02 | 14 |   +5.01% |   +9.77% |   +0.10% |   +4.91% |
| 2026-09-03 | 14 |   +6.13% |   +9.10% |   -0.21% |   +6.34% |
| 2026-09-04 | 28 |   -0.59% |   -3.80% |   +0.85% |   -1.45% |
| 2026-09-08 | 41 |   +3.25% |   +6.50% |   +1.97% |   +1.28% |
| 2026-09-09 | 64 |   +5.36% |   +5.69% |   +2.20% |   +3.16% |
| 2026-09-10 | 69 |   +3.83% |   +4.68% |   +2.38% |   +1.45% |
| 2026-09-11 | 42 |   +5.19% |   +3.20% |   +2.12% |   +3.07% |

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
| 2026-08-28 | 66 |   -6.09% |   -5.68% |   -1.02% |   -5.06% |
| 2026-08-31 | 60 |   -2.83% |   -2.49% |   -0.55% |   -2.28% |
| 2026-09-01 | 28 |   -0.47% |   -0.19% |   +0.28% |   -0.75% |
| 2026-09-02 | 14 |   -2.28% |   -0.83% |   +0.04% |   -2.32% |
| 2026-09-03 | 14 |   -1.20% |   -0.03% |   -1.21% |   +0.01% |
| 2026-09-04 | 28 |   -3.03% |   -2.30% |   -0.87% |   -2.16% |
| 2026-09-08 | 41 |   -4.21% |   -4.55% |   -0.53% |   -3.68% |
| 2026-09-09 | 64 |   -4.67% |   -4.51% |   -0.10% |   -4.56% |
| 2026-09-10 | 69 |   -1.12% |   -0.20% |   +0.60% |   -1.72% |
| 2026-09-11 | 42 |   -4.99% |   -5.44% |   -0.46% |   -4.53% |
| 2026-09-14 | 52 |   +1.71% |   +1.19% |   -0.02% |   +1.73% |
| 2026-09-15 | 15 |   +1.87% |   +1.60% |   +0.77% |   +1.10% |
| 2026-09-16 | 18 |   +3.58% |   +1.31% |   +1.94% |   +1.64% |
| 2026-09-17 | 20 |   -0.59% |   -0.81% |   +0.90% |   -1.49% |
| 2026-09-18 | 40 |   +1.96% |   +1.44% |   +0.90% |   +1.06% |
| 2026-09-21 | 44 |   -0.67% |   -1.14% |   -0.55% |   -0.11% |
| 2026-09-22 | 61 |   -2.66% |   -2.27% |   -0.58% |   -2.09% |
| 2026-09-23 | 68 |   -0.11% |   -0.39% |   +0.16% |   -0.26% |
| 2026-09-24 | 60 |   -0.53% |   +0.32% |   +0.28% |   -0.81% |
| 2026-09-25 | 45 |   -1.58% |   -1.30% |   -0.21% |   -1.37% |
| 2026-09-28 | 56 |   +0.39% |   +1.29% |   +0.64% |   -0.24% |
| 2026-09-29 | 51 |   -0.22% |   +0.61% |   +0.92% |   -1.14% |
| 2026-09-30 | 51 |   -0.73% |   +0.29% |   +1.18% |   -1.91% |
| 2026-10-01 | 46 |   -2.03% |   -0.49% |   +1.18% |   -3.22% |
| 2026-10-02 | 32 |   -6.62% |   -6.58% |   +0.61% |   -7.23% |
| 2026-10-06 | 50 |   -4.84% |   -4.65% |   -0.49% |   -4.35% |
| 2026-10-07 | 48 |   -1.97% |   -1.97% |   -0.26% |   -1.71% |
| 2026-10-08 | 15 |   +1.77% |   +1.64% |   +0.30% |   +1.48% |

## Data check: are these the prices the digest printed?

**Yes.** 1891 of 1905 signals match the close the digest recorded on the same date, within 0.5%. 0 could not be checked because the signal date is not in the returned history.

14 exceptions, which at this rate means a corrected bar rather than a broken join:

| ticker | date | digest said | bars say | gap |
|---|---|---:|---:|---:|
| HMY | 2026-08-13 | 19.26 | 18.84 | -2.18% |
| AUGO | 2026-08-14 | 76.02 | 75.32 | -0.92% |
| HMY | 2026-08-14 | 19.44 | 19.01 | -2.21% |
| HMY | 2026-08-17 | 20.03 | 19.59 | -2.20% |
| HMY | 2026-08-19 | 21.09 | 20.63 | -2.18% |
| HMY | 2026-08-20 | 22.02 | 21.54 | -2.18% |
| HMY | 2026-08-21 | 23.54 | 23.02 | -2.21% |
| HMY | 2026-08-24 | 22.81 | 22.31 | -2.19% |
| HMY | 2026-08-25 | 22.95 | 22.45 | -2.18% |
| HMY | 2026-09-09 | 20.80 | 20.34 | -2.21% |

## By screen, at 20 sessions

Descriptive. A screen looking better here is not a reason to promote it: these are overlapping subsets of one small sample, and choosing among them after the fact is the search that the September pre-registration exists to prevent.

| screen | n | mean | median | trim best 5% | excess vs SPY | excess vs VT |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 16 |   -7.29% |   -4.69% |   -8.41% |   -8.33% |   -6.77% |
| tradability | 360 |   +4.72% |   +5.47% |   +2.41% |   +3.33% |   +4.97% |
| trend | 871 |   -2.77% |   -5.29% |   -4.95% |   -2.62% |   -1.68% |

---

Benchmarks: **SPY**, like for like: US large caps over the same sessions; **VT**, the tracker gate: buy the world instead, proxy for VWRP.

Nothing here is financial advice or a verdict on any screen. It is a record of what the tool claimed and what happened next.
