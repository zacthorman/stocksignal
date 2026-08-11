# stocksignal

A mechanical stock and ETF screener. It takes a written trading rulebook, turns each rule into a testable screen over daily price data, and prints a ranked digest of the tickers that pass with the numbers that made them pass attached.

Every signal is logged to SQLite so the calls can be scored later against what actually happened.

Candidates only. Nothing this produces is advice, and every entry and exit is a human decision.

## Why this exists

Most retail trading rules live in a notebook or a head, get applied inconsistently, and are never checked. This turns them into code, which forces every rule to become precise, and into a log, which makes the rules answerable to evidence.

## Quick start

```bash
# One-time setup
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run it. Offline mode uses deterministic synthetic data, no network, no keys.
stocksignal scan-cmd --tickers AAPL,MSFT,NVDA,SPY

# Real market data
uv pip install -e ".[live]"
stocksignal scan-cmd --live --watchlist data/watchlist.txt --save --log

# See what you have claimed so far
stocksignal history

# Tests
pytest
pytest --cov=stocksignal --cov-report=term-missing
```

## How it is put together

```
src/stocksignal/
  config.py       every tunable number, in one frozen dataclass
  models.py       Quote, ScreenResult, Signal: the shapes that move between modules
  data.py         PriceSource protocol + a synthetic source and a yfinance source
  indicators.py   pure maths on a price frame, no I/O and no opinions
  screens/        one module per rule, each returning a pass/fail plus reasons
  scanner.py      knows only the order of operations
  digest.py       rendering, terminal and markdown
  signal_log.py   append-only SQLite record of every claim made
  cli.py          argument parsing, nothing else
```

Three structural ideas hold it up, and they are the ideas worth carrying into every project after this one.

**The data source is behind a protocol.** `scanner.py` never imports yfinance. It holds something that satisfies `PriceSource`, so swapping provider, adding a cache or faking data in a test is a change at the edge instead of a rewrite through the middle.

**Screens are pure functions.** A screen takes a frame, a quote and a config, and returns a result. It does no I/O and never prints, so testing one is a matter of building a frame with a deliberate shape and asserting on the verdict.

**Reasons travel with the verdict.** A `ScreenResult` carries the strings that explain it. That is not logging. A signal you cannot interrogate is a signal you cannot trust, so the explanation is part of the product.

## What is built and what is not

| Screen | Status |
| --- | --- |
| 1. Tradability gate (volume floor, float floor, history) | Built |
| 2. Trend (price above both SMAs, fast above slow, gap as strength) | Built, and backtested |
| 3. Breakout (3-touch resistance, volume spike, ignition bar, dip-and-reject) | Built, never backtested, and it fails a fidelity check — see below |
| 4. Support and resistance levels (swing clustering, break flips the level) | Built, and backtested |
| 5. Dilution and insider red flags (SEC EDGAR 424B5, S-3, Form 4) | Yours |
| 6. Red-day module (breadth trigger, inverse and volatility ETF list) | Yours |
| 7. Exit alerts on open positions (open below slow SMA, trailing stop) | Yours |

Screen 3 carries a known problem. An audit against the course transcript found
that the ignition-bar rules live on pages 77 to 81, not 72 to 76 as the code
claimed, and that the course's 3-bar setup puts the **baby bar after the ignite
bar** as the small test candle. This screen compares the breaking bar to the bar
*before* it, which is a different comparison from the one the course makes. The
wick disqualifier is also measured as a percentage of the bar's own range, where
page 80 describes a positional test — the baby bar's wick passing below the
ignition bar. Both are recorded in `screens/breakout.py` and neither is fixed.
Nothing in the backtest depends on this screen, so no published number is
affected.

`indicators.py` already ships `swing_points`, `true_range` and `body_and_wick`, which are the raw material for screens 3 and 4. `BUILD-PLAN.md` has the session-by-session route.

## Does any of it work? (session 4, the backtest)

The project overview committed to an honesty gate before a line of the backtest
was written: **if the screens do not beat a tracker after costs, buy the tracker
and keep this as a monitor.** That deal was not renegotiated when the numbers
came back. What follows is the result, including the parts that are unflattering
to the rules and the parts that are unflattering to the code.

### The short version

Six years of daily bars, 252 US equities, walk-forward, next-open fills, costs
deducted. Eight configurations tested across three horizons. One finding survived, and it is not the
one anyone was looking for.

| What was tested | Result |
| --- | --- |
| Trend screens alone (state entry) | Indistinguishable from a random pick |
| Confirmation entry (the course's actual rule) | Indistinguishable |
| RSI gate at 30, and at 50 | Indistinguishable |
| **Gate 1 (reward/risk ≥ 2:1), held to horizon** | **96th percentile, +4.32 points, not certifiable** |
| **Gate 1 with the course's own stop** | **10th percentile — worse than random** |

The last two rows are the same screen picking the same names on the same dates.
Only the exit differs. That is the finding.

### Gate 1 and the stop rule cancel each other out

Gate 1 (page 115) says take trades with more room above than below. The exit
rules (page 234) say put a hard stop at the previous support level. Both are
sensible. Applied together, mechanically, they destroy each other:

```
                stopped out    worst trade    percentile
screens             77%            -9.5%          10th
random control      57%           -20.9%           --
```

A 2:1 reward-to-risk ratio means, by definition, a **close floor**. Putting the
stop on that floor puts it inside ordinary daily noise for a stock selected for
beta above 2, so four trades in five are stopped out before the idea has a
chance to be right or wrong. The individual losses are smaller — the stop is
doing its job — but there are so many more of them that the average dies.

One caveat on that comparison: requiring a three-touch level on both sides, on
top of the page-142 filter, thins the eligible universe to about four tickers a
day. At that width the control is drawing from nearly the same handful of names
as the screens, which makes the two arms more alike than the design intends.

**The rule that falls out: never place the stop at the support level that earned
the setup its ratio.** The tighter the ratio makes the floor look, the more
certain that floor sits inside the noise.

The course teaches these two rules in different chapters and never puts them
side by side. A human reading a chart resolves the tension without noticing they
have done it. Code cannot, which is how the conflict surfaced.

### The one live candidate, and why it is not a claim

Gate 1 at 2:1, held to a 20-session horizon, scored the 96th percentile against
5,000 matched random controls, with a mean of 7.01% against the control's 2.69%.
The median improved too, and the result survived having its best 5% of trades
deleted. A separate control — the same backtest run on **shuffled** real bars,
which keeps volatility and price level while destroying every time-series
relationship — put the real result above all twenty shuffles, p ≈ 0.048.

It still is not a claim, for a reason that has nothing to do with the market:

> **The declared bar demanded 6.43 points per trade. The observed effect was
> 4.32. This design had roughly a one-in-six chance of certifying the effect it
> actually measured.**

Failing a bar the data cannot reach is not a negative result, it is an absent
one. The report now prints its own minimum detectable effect next to every
number so this cannot be misread again. Setting a bar without first checking
whether the data could clear it was the single worst methodological error in the
project.

Correct treatment of a result like this is not another slice of the same data.
It is to **pre-register it** — gate 1 at 2:1, held, 20-session mean, family of
one, bar 95% — and test it on data that did not exist when the threshold was
chosen.

### How the test is built

Three arms, and the third is the one that matters:

- **screens** — every ticker that passed, entered at the next open.
- **random from universe** — the same number of names, on the same dates, from
  the same reconstituted universe. Carries the identical survivorship bias, so
  the difference between the arms measures the screens rather than the universe.
- **SPY** — bought on every signal date.

The headline statistic is a **permutation test**: the control is redrawn
thousands of times and the report states what share of controls the screens
beat. A single random arm is one roll of the dice; the percentile is the result.
Three statistics are reported per horizon — mean, median, and mean with the best
5% of trades removed — because a mean that passes while the trimmed mean
collapses is a different finding from one where both hold.

Six lookahead vectors are addressed explicitly in `backtest.py`'s docstring. The
strongest guarantee is structural: nothing in the module is handed a full frame
plus a date, so no future bar is reachable even by mistake. Where that was not
possible — `nearest_levels` needs an answer at every bar — the shift is explicit
and a test proves it agrees exactly with recomputing on a truncated frame.

### What this design cannot see

Stated here rather than buried, because it materially narrows the claim.

**Timing.** The control trades the same dates as the screens, so any edge that
lives in *when* to be in the market scores 50 by construction. This measures
which **names** were picked, never when. A large share of what trend-following
actually earns is thought to be timing, so this may be measuring the smaller half.

**The universe filter itself.** The candidate pool already passed the course's
own scan filter (price ≥ $15, volume ≥ 100k, beta ≥ 2). So "random from
universe" is already the course's base strategy. The honest claim is *no
incremental edge over the page-142 filter*, not *no edge over random stocks*.

**Survivorship, and it is not arm-symmetric.** Delisted names are absent. A
random control would have drawn some death spirals and eaten them; the screens
structurally cannot pick a stock below both its moving averages. Deleting those
names flatters the control, so the measured gap is probably an understatement.

**Multiplicity.** Twenty-four tests share trades, dates and horizons. Bonferroni
assumes independence they do not have, so the 99.7% bar overshoots — the
defensible bar is somewhere between 95% and 99.7%. It is left at the
conservative end deliberately, because choosing a correction after seeing the
number is how people fool themselves.

### Three artefacts that each read as a discovery

The most useful output of this session was not a number. It was the discovery
that a backtest will manufacture convincing results if you let it, and that the
only defence is a control you have deliberately tried to break.

1. **The control drew a flat three names per date** while the screens recorded
   however many fired. Signal breadth peaks when the market is extended, so the
   two arms were averaged over different date weightings. The comparison was
   measuring the weighting.
2. **Under stops, trend-screened names more often had no resistance above them**
   — no target, so no trailing stop, so their winners ran uncapped while the
   control's were trimmed. On a feed with no predictive signal in it, that alone
   put the screens at the 96th percentile.
3. **The median is unreadable under stops.** Stopped-out trades pile into a lump
   just below zero and the median sits inside it, so a small change in stop-out
   frequency moves it enormously. On the same signal-free feed the median beat
   99–100% of controls. It is now printed with a warning and the verdict ignores it.

Two independent adversarial audits found six further defects, including a real
trading-logic bug where arming the trailing stop could move the exit level
*below* the pre-committed hard stop. Each fix is documented in the code at the
point it matters, including what was wrong before, because a correction is more
useful than a clean file.

Three of the code's own docstrings were found to be **misquoting the rulebook**,
each time in the direction that justified what the code already did. Those are
corrected and the record of them is kept.

### Reproducing the numbers

```bash
# The one live candidate.
stocksignal backtest --from 2020-01-01 --fit-end 2023-12-31 \
  --entry confirmation --min-rr 2.0 --replicates 5000

# The same screen with the course's own stop.
stocksignal backtest --from 2020-01-01 --fit-end 2023-12-31 \
  --entry confirmation --min-rr 2.0 --exits stops --replicates 5000

# The null control: real bars, time ordering destroyed. Run several seeds.
stocksignal backtest --from 2020-01-01 --fit-end "" \
  --entry confirmation --min-rr 2.0 --replicates 2000 --shuffle --shuffle-seed 1
```

Every figure above was produced after six rounds of adversarial review. The
numbers did not move materially through the last three of them, which is the
only reason they are quoted here.

### The honest bottom line

The trend and RSI screens do not pick better stocks than chance, within a day,
out of a universe already filtered by the course's own rules.

Gate 1 is a real candidate that this dataset cannot certify, and it is actively
harmful when combined with the stop placement the same course recommends.

SPY beat every variant on hit rate and worst trade at every horizon.

So the honesty gate fires: **buy the tracker.** This stays a monitor and a
shortlist generator, which is worth having — 256 candidates down to a handful a
day is real work saved — and it is not sold as an edge, because it has not
earned that description.

## Open questions, still unanswered

**The RSI settings are an assumption.** 14 / 30 / 70 are the Thinkorswim
defaults the charts would have been using. The course never prints a number.
Confirm them against the actual platform setup and change them in `config.py`.

**CONFIRMATION is tested on the close, and page 116 says the open.** The exact
words are "the first candlestick holding *(OPENING)* above the blue SMA line".
Every result in this README used the close. It is a one-word difference in the
rulebook and a real difference on every signal.

**The candidate pool is not reproducible.** `data/watchlist.txt` is not in the
repo, `build_watchlist.py` defaults to a 500-symbol sample of the market, and
its cache never expires, so a rebuild spread across two days can mix
as-of dates. Fix before publishing any number that depends on the pool.

**The breakout screen has never been measured**, and it fails the fidelity check
described above. It is the centrepiece of the rulebook and the largest remaining
gap.

