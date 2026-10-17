# Signal outcomes, as of 2026-10-17

1964 signals in the ledger, 1961 with at least one finished horizon, 3 with nothing finished yet.

Every signal is scored as an equal-weight paper trade whether or not it was taken: the ledger records what the tool claimed, so this measures the tool. Costs of 0.2% are deducted once from the trade and never from the benchmark.

**Entry is the first price that existed after the digest did.** A signal published before the opening bell fills at the next open; one published after it fills at that session's close, which is the next price a reader could actually have paid. Here that is 533 trades filled at an open and 1428 at a close. The split is computed per signal from the ledger's own clock, so it tracks whatever the scheduled scan actually does rather than what it is supposed to do.

**Read the median and the trimmed mean before the mean.** A mean that needs its best trades is a mean you cannot trade, because you do not know in advance which ones they are.

**No significance is claimed anywhere in this file.** Nothing here was pre-registered, no test was run, and the trades overlap heavily: dozens bought the same morning and held the same sessions are readings of one market move. Read it as a record of what happened, and look at the entry-day tables below before believing any average.

**The last row is a proxy and not your exit rule.** Page 107 says validation, the first candle holding below the 9 SMA, is not a concrete exit point: it is where you re-weigh the factors and decide. Selling on it is what can be scored without a person in the loop, so that is what the row measures. The rulebook's real exit needs a hard stop at a previous support level and a 5% trailing stop armed only after the price target is hit, and neither is decided yet: the support definition is the project's open question, and the tool deliberately publishes no price targets.

| horizon | trades | entry days | mean | median | trim best 5% | hit rate | SPY itself | excess vs SPY (mean / median) | VT itself | excess vs VT (mean / median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 sessions | 1905 | 38 |   -2.86% |   -2.83% |   -4.05% | 38% |   -0.11% |   -2.74% /   -2.98% |   -0.30% |   -2.55% /   -2.79% |
| 20 sessions | 1048 | 24 |   -2.60% |   -4.89% |   -4.76% | 41% |   +0.13% |   -2.73% /   -5.27% |   -0.92% |   -1.69% /   -4.17% |
| 60 sessions | not yet elapsed | | | | | | | |
| sell on validation | 1961 | 41 |   -2.85% |   -2.50% |   -3.62% | 31% |   -0.06% |   -2.79% /   -2.39% |   -0.30% |   -2.55% /   -2.12% |

## The 20-session horizon, in words

These 1048 trades were entered on 24 mornings, 2026-08-14 to 2026-09-18, so this is one window of market rather than a track record. It will read differently every month until the ledger covers several.
The average one lost to SPY by 2.73 points; the median one lost to it by 5.27.

## Every entry day at 20 sessions

One row here is one morning's worth of signals, which is one market move. Read the number of rows, not the number of trades, when judging how much any average above is worth.

| entry day | trades | mean | median | SPY itself | excess vs SPY |
|---|---:|---:|---:|---:|---:|
| 2026-08-14 | 94 |  -13.70% |  -15.28% |   -2.27% |  -11.43% |
| 2026-08-17 | 98 |  -15.32% |  -18.31% |   -2.42% |  -12.90% |
| 2026-08-18 | 105 |  -12.28% |  -15.15% |   -1.91% |  -10.37% |
| 2026-08-19 | 35 |   -7.50% |  -10.38% |   -1.01% |   -6.49% |
| 2026-08-20 | 28 |   -0.44% |   +1.97% |   -0.31% |   -0.13% |
| 2026-08-21 | 28 |   -1.85% |   -3.87% |   +1.22% |   -3.08% |
| 2026-08-24 | 30 |   +1.97% |   -0.72% |   +1.38% |   +0.60% |
| 2026-08-25 | 23 |   -2.21% |   -4.23% |   +0.46% |   -2.67% |
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
| 2026-09-14 | 52 |   +8.42% |   +7.30% |   +2.52% |   +5.90% |
| 2026-09-15 | 15 |   +6.01% |   +5.12% |   +2.98% |   +3.03% |
| 2026-09-16 | 19 |   -0.67% |   -3.24% |   +2.32% |   -2.99% |
| 2026-09-17 | 24 |   -4.17% |   -5.91% |   +1.46% |   -5.62% |
| 2026-09-18 | 45 |  -12.41% |  -12.36% |   +0.20% |  -12.62% |

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
| 2026-09-11 | 42 |   -4.98% |   -5.41% |   -0.46% |   -4.52% |
| 2026-09-14 | 52 |   +1.71% |   +1.19% |   -0.02% |   +1.73% |
| 2026-09-15 | 15 |   +1.87% |   +1.60% |   +0.77% |   +1.10% |
| 2026-09-16 | 19 |   +5.24% |   +1.68% |   +1.99% |   +3.25% |
| 2026-09-17 | 24 |   +2.02% |   +0.20% |   +1.07% |   +0.94% |
| 2026-09-18 | 45 |   +2.84% |   +1.47% |   +1.01% |   +1.83% |
| 2026-09-21 | 50 |   -0.16% |   -0.89% |   -0.44% |   +0.28% |
| 2026-09-22 | 68 |   -2.11% |   -1.97% |   -0.48% |   -1.63% |
| 2026-09-23 | 75 |   +0.31% |   -0.27% |   +0.24% |   +0.06% |
| 2026-09-24 | 67 |   -0.15% |   +0.46% |   +0.37% |   -0.52% |
| 2026-09-25 | 53 |   -1.28% |   -0.70% |   -0.08% |   -1.20% |
| 2026-09-28 | 65 |   +0.47% |   +1.29% |   +0.74% |   -0.27% |
| 2026-09-29 | 60 |   -0.42% |   +0.32% |   +1.02% |   -1.44% |
| 2026-09-30 | 61 |   -0.91% |   -0.05% |   +1.26% |   -2.17% |
| 2026-10-01 | 58 |   -2.36% |   -1.06% |   +1.26% |   -3.62% |
| 2026-10-02 | 48 |   -6.67% |   -6.46% |   +0.63% |   -7.30% |
| 2026-10-06 | 81 |   -6.23% |   -5.50% |   -0.50% |   -5.74% |
| 2026-10-07 | 83 |   -4.63% |   -2.72% |   -0.25% |   -4.38% |
| 2026-10-08 | 48 |   -2.85% |   -1.54% |   +0.21% |   -3.05% |
| 2026-10-09 | 40 |   -6.18% |   -5.46% |   -0.41% |   -5.77% |
| 2026-10-13 | 33 |   -5.12% |   -3.49% |   -0.84% |   -4.28% |
| 2026-10-14 | 17 |   -1.37% |   -2.78% |   -0.11% |   -1.25% |
| 2026-10-15 | 6 |   +0.39% |   -0.13% |   +0.19% |   +0.20% |

## Data check: are these the prices the digest printed?

**Yes.** 1950 of 1964 signals match the close the digest recorded on the same date, within 0.5%. 0 could not be checked because the signal date is not in the returned history.

14 exceptions, which at this rate means a corrected bar rather than a broken join:

| ticker | date | digest said | bars say | gap |
|---|---|---:|---:|---:|
| HMY | 2026-08-13 | 19.26 | 18.84 | -2.18% |
| AUGO | 2026-08-14 | 76.02 | 75.32 | -0.92% |
| HMY | 2026-08-14 | 19.44 | 19.02 | -2.16% |
| HMY | 2026-08-17 | 20.03 | 19.60 | -2.15% |
| HMY | 2026-08-19 | 21.09 | 20.64 | -2.13% |
| HMY | 2026-08-20 | 22.02 | 21.55 | -2.13% |
| HMY | 2026-08-21 | 23.54 | 23.03 | -2.17% |
| HMY | 2026-08-24 | 22.81 | 22.32 | -2.15% |
| HMY | 2026-08-25 | 22.95 | 22.45 | -2.18% |
| HMY | 2026-09-09 | 20.80 | 20.35 | -2.16% |

## By screen, at 20 sessions

Descriptive. A screen looking better here is not a reason to promote it: these are overlapping subsets of one small sample, and choosing among them after the fact is the search that the September pre-registration exists to prevent.

| screen | n | mean | median | trim best 5% | excess vs SPY | excess vs VT |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 20 |   -5.75% |   -4.69% |   -7.44% |   -6.91% |   -5.33% |
| tradability | 515 |   +3.02% |   +3.63% |   +0.76% |   +1.54% |   +3.18% |
| trend | 1025 |   -2.52% |   -4.75% |   -4.69% |   -2.64% |   -1.60% |

---

Benchmarks: **SPY**, like for like: US large caps over the same sessions; **VT**, the tracker gate: buy the world instead, proxy for VWRP.

Nothing here is financial advice or a verdict on any screen. It is a record of what the tool claimed and what happened next.
