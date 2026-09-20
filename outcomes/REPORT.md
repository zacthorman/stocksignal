# Signal outcomes, as of 2026-09-20

1048 signals in the ledger, 957 with at least one finished horizon, 91 with nothing finished yet.

Every signal is scored as an equal-weight paper trade whether or not it was taken: the ledger records what the tool claimed, so this measures the tool. Costs of 0.2% are deducted once from the trade and never from the benchmark.

**Entry is the first price that existed after the digest did.** A signal published before the opening bell fills at the next open; one published after it fills at that session's close, which is the next price a reader could actually have paid. Here that is 533 trades filled at an open and 424 at a close. The split is computed per signal from the ledger's own clock, so it tracks whatever the scheduled scan actually does rather than what it is supposed to do.

**Read the median and the trimmed mean before the mean.** A mean that needs its best trades is a mean you cannot trade, because you do not know in advance which ones they are.

**No significance is claimed anywhere in this file.** Nothing here was pre-registered, no test was run, and the trades overlap heavily: dozens bought the same morning and held the same sessions are readings of one market move. Read it as a record of what happened, and look at the entry-day tables below before believing any average.

**The last row is a proxy and not your exit rule.** Page 107 says validation, the first candle holding below the 9 SMA, is not a concrete exit point: it is where you re-weigh the factors and decide. Selling on it is what can be scored without a person in the loop, so that is what the row measures. The rulebook's real exit needs a hard stop at a previous support level and a 5% trailing stop armed only after the price target is hit, and neither is decided yet: the support definition is the project's open question, and the tool deliberately publishes no price targets.

| horizon | trades | entry days | mean | median | trim best 5% | hit rate | SPY itself | excess vs SPY (mean / median) | VT itself | excess vs VT (mean / median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 sessions | 893 | 19 |   -4.23% |   -4.92% |   -5.37% | 31% |   -0.56% |   -3.66% /   -4.41% |   -0.52% |   -3.71% /   -4.39% |
| 20 sessions | 360 | 5 |  -12.09% |  -14.48% |  -13.84% | 17% |   -1.93% |  -10.16% /  -12.28% |   -2.12% |   -9.97% /  -12.18% |
| 60 sessions | not yet elapsed | | | | | | | |
| sell on validation | 937 | 23 |   -4.18% |   -4.04% |   -4.77% | 22% |   -0.45% |   -3.73% /   -3.42% |   -0.45% |   -3.72% /   -3.36% |

## The 20-session horizon, in words

These 360 trades were entered on 5 mornings, 2026-08-14 to 2026-08-20, so this is one window of market rather than a track record. It will read differently every month until the ledger covers several.
The average one lost to SPY by 10.16 points; the median one lost to it by 12.28.

## Every entry day at 20 sessions

One row here is one morning's worth of signals, which is one market move. Read the number of rows, not the number of trades, when judging how much any average above is worth.

| entry day | trades | mean | median | SPY itself | excess vs SPY |
|---|---:|---:|---:|---:|---:|
| 2026-08-14 | 94 |  -13.70% |  -15.28% |   -2.27% |  -11.43% |
| 2026-08-17 | 98 |  -15.32% |  -18.31% |   -2.42% |  -12.90% |
| 2026-08-18 | 105 |  -12.28% |  -15.15% |   -1.91% |  -10.37% |
| 2026-08-19 | 35 |   -7.50% |  -10.38% |   -1.01% |   -6.49% |
| 2026-08-20 | 28 |   -0.44% |   +1.99% |   -0.31% |   -0.13% |

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
| 2026-08-28 | 65 |   -6.40% |   -5.86% |   -1.03% |   -5.38% |
| 2026-08-31 | 59 |   -3.17% |   -2.49% |   -0.56% |   -2.62% |
| 2026-09-01 | 27 |   -1.45% |   -0.20% |   +0.27% |   -1.71% |
| 2026-09-02 | 13 |   -3.12% |   -0.93% |   +0.03% |   -3.15% |
| 2026-09-03 | 13 |   -1.57% |   -0.07% |   -1.23% |   -0.34% |
| 2026-09-04 | 26 |   -3.59% |   -2.57% |   -0.92% |   -2.67% |
| 2026-09-08 | 39 |   -4.36% |   -5.35% |   -0.58% |   -3.78% |
| 2026-09-09 | 61 |   -5.03% |   -4.55% |   -0.14% |   -4.88% |
| 2026-09-10 | 65 |   -1.95% |   -0.58% |   +0.55% |   -2.50% |
| 2026-09-11 | 38 |   -6.09% |   -6.13% |   -0.56% |   -5.53% |
| 2026-09-14 | 48 |   +1.03% |   +1.10% |   -0.10% |   +1.13% |
| 2026-09-15 | 10 |   +0.00% |   +1.54% |   +0.43% |   -0.42% |
| 2026-09-16 | 4 |   -0.38% |   -0.52% |   +1.21% |   -1.59% |
| 2026-09-17 | 2 |   -0.15% |   -0.15% |   +0.08% |   -0.23% |

## Data check: are these the prices the digest printed?

**Yes.** 1047 of 1048 signals match the close the digest recorded on the same date, within 0.5%. 0 could not be checked because the signal date is not in the returned history.

1 exception, which at this rate means a corrected bar rather than a broken join:

| ticker | date | digest said | bars say | gap |
|---|---|---:|---:|---:|
| AUGO | 2026-08-14 | 76.02 | 75.32 | -0.92% |

## By screen, at 20 sessions

Descriptive. A screen looking better here is not a reason to promote it: these are overlapping subsets of one small sample, and choosing among them after the fact is the search that the September pre-registration exists to prevent.

| screen | n | mean | median | trim best 5% | excess vs SPY | excess vs VT |
|---|---:|---:|---:|---:|---:|---:|
| breakout | 1 |  -33.08% |  -33.08% |  -33.08% |  -30.81% |  -30.73% |
| trend | 353 |  -12.02% |  -14.52% |  -13.80% |  -10.10% |   -9.91% |

---

Benchmarks: **SPY**, like for like: US large caps over the same sessions; **VT**, the tracker gate: buy the world instead, proxy for VWRP.

Nothing here is financial advice or a verdict on any screen. It is a record of what the tool claimed and what happened next.
