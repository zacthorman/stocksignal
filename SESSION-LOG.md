# stocksignal: session log

A running record of what got done, what was learned, and what the next session opens with. Append to the top. Written at the end of every session, before you close the laptop, because reconstructing this from memory three days later costs you half an hour.

---

## Session 6, Friday 14 August 2026

**Where it started:** the daily scan had gone silent, and Zac reported it as a
failure.
**Where it ended:** the scan had never failed. It ran green for two days with no
credentials and produced nothing, which is a worse outcome than failing. Plus
the phone digest was fixed, and the armed reclaim sequence was measured for
outcomes rather than counts.

### The scan was green and empty for two days

GitHub Actions fired on schedule on 12 and 13 August. Both runs completed
successfully in about 16 seconds. Every step passed. The digest for 13 August
reads:

```
Scanned 256. Passed 0. Rejected 0. Errors 256.
- AEHR: Alpaca credentials missing. Set ALPACA_API_KEY_ID and ...
```

Cause: the repository had **no Actions secrets at all**. The workflow shipped on
11 August, the four secrets it reads were never added. Every ticker failed on
auth, and Telegram delivery skipped quietly because its token was missing too,
so nothing arrived on the phone.

**The real defect is that this looked healthy.** `daily-scan.yml` says in its own
comments that the job should fail for "things that are genuinely your problem:
missing credentials". It does not. Missing credentials arrive disguised as N
per-ticker errors, the tolerant error handling swallows them, and the run exits
zero. Green tick, empty digest, no message, two days gone.

Not yet fixed. The rule that would catch it: if the error count equals the ticker
count, or one error string covers every ticker, that is systemic rather than a
provider hiccup, and the run should exit non-zero. Same for `--telegram` passed
with no token present: explicitly requesting delivery and silently not delivering
should be loud.

Also worth noting: re-running the workflow overwrote `digests/digest-2026-08-13.md`,
so the errored version of that day is gone. The digest folder is supposed to be
the record of what the tool claimed at the time. It is currently
last-write-wins.

### The phone digest was justifying every name with the hard gate

Zac's first real message listed eight candidates and gave all eight the same two
reasons: price clears the 15.00 swing floor, average volume clears the 100,000
floor. True of all 94 that passed, so it distinguished nothing.

Mechanism: `scanner.py` builds `results=(gate, *scoring)`, `Signal.reasons`
concatenates in that order, and `notify.py` took `reasons[:2]`. Tradability
always emits exactly two reasons, so the scoring screens could never reach the
message. The screen that made a ticker a candidate was the one thing never shown.

Fixed. `Signal.setup_reasons` returns the scoring screens' reasons, skipping the
hard gate; `render_telegram` uses it and falls back to the old behaviour if a
signal somehow has nothing else. Three regression tests added to
`tests/test_notify.py`. 365 tests passing.

### The armed reclaim sequence, measured for outcomes

Zac asked for the sequence run as a sequence rather than a coincidence, which is
the correction already made on 11 August, and then for something new: not how
often it completes, but what happened to the ones that did.

New script `scripts/reclaim_outcomes.py`. Sequence measured: RSI crosses under
30 arms the name, first later bar closing above both SMAs with fast above slow
is the signal, entry at the next open. **No ignition bar and no gate 1**, because
the rule as Zac states it has neither, and gate 1 is the thing under question.

Risk is the most recent CAUSALLY confirmed swing low, 5-bar lookback, not the
three-touch level. That is a rulebook change and it is recorded as one: the
three-touch definition is undefined too often to produce a readable count. Even
on the setups measured here it was defined only about 63% of the time.

Overlap rule: a new arm is skipped while an earlier setup on that ticker is
still inside its 20-session horizon. **This makes the counts NOT comparable to
the 11 August funnel table**, which counted every crossing. At unbounded arming
2,462 of 3,621 dips are dropped as overlapping.

Costs not deducted. No control arm, no percentile, no significance claim.

| Stay armed | Entries | Up @20 | Down @20 | Reached 2R | Stopped first |
| --- | --- | --- | --- | --- | --- |
| 21 sessions | 73 | 49.3% | 50.7% | 13.7% | 27.4% |
| **63 sessions** | **182** | **51.1%** | **48.9%** | **8.8%** | **22.0%** |
| 252 sessions | 370 | 51.4% | 48.6% | 9.5% | 18.4% |
| unbounded | 455 | 51.0% | 49.0% | 10.5% | 17.8% |

**Two readings, and the second matters more than the first.**

Direction is a coin flip. 51% up at 20 sessions, stable across every arming
window. Nothing here suggests the reclaim shifts which way the next month goes.
Without a control arm that is suggestive rather than settled, since roughly half
of all 20-session windows are up anyway.

The 2:1 target does not clear its own arithmetic. A 1R stop against a 2R target
needs better than a 33% hit rate to break even. At the realistic three-month
patience limit it hits 8.8% and stops out 22.0%. Counting only the resolved
trades that is 16 wins at +2R against 40 losses at -1R, so -8R before costs, with
126 trades finishing somewhere in between. The tighter the arming window the
better the hit rate looks and the worse the stop rate gets, which is the same
shape session 4 found: a close floor sits inside ordinary noise.

**Known limitation in the script, stated rather than buried.** Setups are dropped
when the most recent confirmed swing low sits at or above the entry price, which
means an already-broken floor. That drops 43 of 229 at the 63-session window, so
roughly a fifth of the sample. Walking back to the nearest swing low BELOW entry
instead would keep them and would change the numbers. Not done, because picking
the definition after seeing the result is exactly the thing this project refuses
to do. If it gets changed it gets changed as a pre-registered rerun.

### Same sequence, one rulebook factor at a time

Zac asked for the run again with the ignition bar and the other indicators from
the documents. New script `scripts/reclaim_factor_ablation.py`. Arming window
fixed at 63 sessions and horizon at 20 BEFORE the run, so the only thing varying
across rows is the factor. Every configuration printed, none promoted.

| configuration | n | up | down | hit 2R | stopped | net R |
| --- | --- | --- | --- | --- | --- | --- |
| base: arm + reclaim both SMAs | 182 | 51.1% | 48.9% | 8.8% | 22.0% | -8 |
| + SMA gap >= 3.6% (chop filter) | 55 | 49.1% | 50.9% | 14.5% | 29.1% | 0 |
| + ignition bar within 10 sessions | 159 | 52.8% | 47.2% | 9.4% | 19.5% | -1 |
| + RSI < 70 at signal | 128 | 46.9% | 53.1% | 9.4% | 27.3% | -11 |
| + volume >= 1.5x average | 39 | 53.8% | 46.2% | 12.8% | 17.9% | +3 |
| + gate 1: reward:risk >= 2 | 4 | n/a | n/a | n/a | n/a | unreadable |
| + full breakout screen fires | 10 | n/a | n/a | n/a | n/a | unreadable |
| all of gap, ignition, RSI<70, volume | 6 | n/a | n/a | n/a | n/a | unreadable |

Net R counts resolved trades only, +2R per target, -1R per stop.

**Nothing moved direction.** Up rate across every readable row sits between 46.9%
and 53.8%. Eight configurations, and the spread is noise around a coin flip.

**The ignition bar filters almost nothing, again.** 182 down to 159, an 87% pass
rate, and the outcome columns barely move. Session 5 measured the same thing
from a different script and got 85%. Two independently written implementations
agreeing on that number is the most reassuring thing in this table.

**The RSI ceiling actively hurts.** The only row clearly worse than base: 46.9%
up and -11 net R. After an oversold dip and a reclaim of both SMAs, the names
reading above 70 are the ones that have run hardest, and excluding them removes
winners. This is session 4's finding arriving by a second route, where adding the
RSI gate to gate 1 more than halved the effect. Twice now an RSI filter has
removed trades the rest of the system correctly wanted. Worth treating as a
pattern rather than two coincidences.

**Gate 1 is still unmeasurable.** 182 setups down to 4. Harsher than the 92%
figure from session 5, because gate 1 needs a three-touch level on both sides at
the reclaim bar specifically. The finding replicates on a different entry
definition, which is the useful part.

**The two best-looking rows are the two smallest, and that is the whole story of
this table.** Volume at n=39 is 5 targets against 7 stops; one trade either way
flips the sign. With eight configurations run, one landing marginally positive is
the expected outcome of running eight configurations. Neither row is a finding
and neither should be built on.

**What no filter fixed.** Best readable 2R hit rate is 14.5% against the 33%
needed to break even. Every configuration fails the target geometry by a factor
of two or more. The problem is not a missing filter. A 2R target measured off a
close stop does not clear its own arithmetic on this sequence, which is the same
conclusion session 4 reached about gate 1 and the page 234 stop.

**What could not be tested, and why it matters.** `min_float` needs shares
outstanding, `growth_template.py` needs fundamentals, and `opportunity.py` needs
a growth direction from a research pass. The cache holds OHLCV only. So every
factor in the table above reads the same six years of the same price series, and
their agreeing with each other is close to guaranteed. The only genuinely
independent axis the project has is the one that cannot be backtested from this
data at all.

### Zac's exit rule: close below the 9 SMA

Zac rejected the 2:1 format outright. His rule: sell on price rejection, when the
candle holds below the short-term SMA. New script `scripts/reclaim_sma_exit.py`.

This is a THIRD exit rule, not a variant. `Config.exit_rule` knows "hold" (fixed
horizon) and "stops" (page 234 support stop plus trail). This is neither: no
target, no fixed floor, and it needs no level to be defined, which is what made
gate 1 unmeasurable. It is the mirror of the entry, exiting on the first candle
that stops holding above the 9.

Entry unchanged. Exit at the first close below the 9 SMA, filled at the next
open. **SPY measured over each trade's own window**, because a hit rate without
a comparator is not readable once the output is returns rather than counts. That
comparator is the project's original honesty gate, not something invented here.

| configuration | n | hit | mean | median | trim5% | SPY | excess | hold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base: arm + reclaim both SMAs | 215 | 37.7% | +1.57% | -1.92% | -1.60% | +0.43% | +1.15% | 5d |
| + SMA gap >= 3.6% | 80 | 41.2% | +2.64% | -1.50% | -0.14% | +0.43% | +2.21% | 5d |
| + ignition bar | 179 | 35.2% | +1.22% | -1.68% | -1.46% | +0.39% | +0.83% | 5d |
| + RSI < 70 | 161 | 38.5% | +0.72% | -2.21% | -1.78% | +0.40% | +0.32% | 5d |
| + volume >= 1.5x | 50 | 42.0% | +6.88% | -1.60% | +0.74% | +0.66% | +6.22% | 6d |
| + gate 1 | 4 | n/a | n/a | n/a | n/a | n/a | n/a | unreadable |
| + full breakout screen | 11 | n/a | n/a | n/a | n/a | n/a | n/a | unreadable |
| all four stacked | 10 | n/a | n/a | n/a | n/a | n/a | n/a | unreadable |

Sensitivity on what "holds below" means, base configuration only:

| closes below | n | hit | mean | median | trim5% | excess | hold |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 215 | 37.7% | +1.57% | -1.92% | -1.60% | +1.15% | 5d |
| 2 | 215 | 43.7% | +3.73% | -0.89% | -1.12% | +3.02% | 7d |
| 3 | 215 | 42.8% | +3.51% | -1.70% | -1.85% | +2.68% | 9d |

**Zac was right that the 2:1 format was wrong.** It is not close. The 2R target
was -8 net R and structurally broken; this produces a positive mean that beats
the tracker on every readable row. Discarding it was the correct call.

**And it is the same shape as everything else in this project.** Positive mean,
negative median, negative trimmed mean. Session 5 found precisely this signature
on the breakout screen. Three different exits have now been measured on this
universe and all of them are carried by a handful of trades.

To be fair to the rule: for a trend-following exit, a 37.7% hit rate with a
negative median and a positive mean is the DESIGN, not a defect. Cut losers in
five days, let the winners run. Nothing here refutes the method, exactly as
nothing in session 5 refuted the breakout method.

What cannot be waved away is the trimmed mean. Remove the best 5% of trades and
the base row goes to -1.60%, which loses to a tracker returning +0.43%. The
entire edge is in a dozen trades out of 215, and 215 trades across six years
cannot settle whether that tail is real or a lucky draw. **Underpowered, not
negative. The third time this project has reached that verdict by a new route.**

**The volume row is a trap and it is worth naming before anyone builds on it.**
+6.88% mean is the best number produced by any run today. Its trimmed mean is
+0.74% against SPY's +0.66%, so an excess of roughly eight basis points before
costs, negative after. On 50 trades, essentially the whole +6.88% is two or three
names. It is the most impressive-looking and least substantial row in the table.

**Do not select 2 consecutive closes because it looks best.** It was run as a
sensitivity check on an ambiguous phrase, not as a parameter search. Its median
and trimmed mean are both still negative, so the improvement over 1 close is
once again entirely tail. Picking it now would be choosing the definition after
seeing the result, which is the one move this project has refused throughout.

**Costs.** Not deducted anywhere above. The CLI's standing assumption is 0.2%
round trip, which takes the base excess from +1.15% to +0.95% and the trimmed
mean to -1.80%. It does not change any conclusion, but at a five-day median hold
this is the configuration where omitting costs flatters a result most, and the
number should be run with them before it is quoted anywhere.

### The factor ledger, and reading the notes properly

Zac asked for the course read end to end and the rules followed as written. Done
against `02 Projects/Trading Bot/ZipTraderU Course - OCR Transcript.md`, all 256
pages. Three things came out of it and two of them invalidated work done earlier
the same day.

**1. Confirmation and validation are OPEN-based, and every script today used the
close.** p116: "FIRST CANDLESTICK HOLDING (OPENING) ABOVE THE BLUE SMA LINE."
p111, on AMRN: the candle "did go below the short-term SMA line but it didn't
open below the line. That means it was not a Validation." This was already an
open item in the README and it got reproduced anyway.

Rerun as `scripts/reclaim_sma_exit_open.py`:

| | n | hit | mean | median | trim5% | excess |
| --- | --- | --- | --- | --- | --- | --- |
| close-based | 215 | 37.7% | +1.57% | -1.92% | -1.60% | +1.15% |
| open-based | 214 | 41.1% | +1.30% | -1.27% | -1.72% | +0.99% |

Verdict unchanged. Worth recording: the "2 consecutive closes looks better"
effect flagged as not-to-be-chased DISAPPEARS on opens (+0.99% against +0.92%).
It was an artefact of the wrong price field, which is a decent argument for the
rule about not selecting on a number you have just seen.

**2. "Two or three elevating factors and no deprecating factors" is not in the
course.** Searched specifically. There is no list of elevating factors (p45
defines them open-endedly: "Every indicator that is in your favor is an
elevating factor"), no required count (p47's "a moderate amount" is the maximum
precision available), and deprecating factors explicitly do not disqualify
(p131: "Even good trades can have some deprecating factors"; p132: "A big
elevating factor can counter a deprecating factor"; p205 takes a UVXY position
while overbought). The ledger is deliberately unscored, weighted by factor size
and by timeframe.

Zac's call, recorded as his: **at least 2 elevating AND zero deprecating.**
Stricter than the rulebook on the deprecating side, and a number the rulebook
does not contain on the elevating side. Implemented in `scripts/factor_ledger.py`
with every factor carrying its page citation.

**3. The result, and it is about the rule rather than the returns.**

Entry: first candle OPENING above the 9 SMA where the ledger passes. Exit: first
candle OPENING below it. Page 142 universe. 267 stocks, six years.

```
confirmations                                7563
  blocked by a deprecating factor            6208
  blocked by too few elevating factors          0
  TRADES TAKEN                               1044
```

**The "2 or more elevating" half of the rule never fires once.** Zero. It is
entirely absorbed by the zero-deprecating half, and the reason is structural:
direction and MACD are both two-sided factors, so anything that avoids being
deprecating on them is automatically elevating on both, which is already two.
The threshold Zac specified cannot bind at any value up to 2, and the
zero-deprecating rule is doing one hundred percent of the filtering.

| n | hit | mean | median | trim5% | SPY | excess | hold |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1044 | 43.9% | +2.09% | -1.05% | -0.91% | +0.44% | +1.65% | 4d |

Same signature for the fourth time today: positive mean, negative median,
negative trimmed mean. This run matters more than the others because the sample
is 1,044 rather than 214, and removing the best 5% (52 trades) STILL turns it
negative against a tracker that made +0.44%. A larger sample has not rescued the
shape, it has sharpened it.

What actually blocks entries: MACD 3,948, direction 2,923, over-expanded
volatility 1,293, reward:risk 419, at-resistance 255, overbought RSI 219. So the
ledger in practice is a MACD-and-above-the-180-SMA filter with a volatility
overlay, and the rest of the factors are close to decorative at this threshold.

**Still not measured on the instruments Zac actually trades.** All of the above
is 267 high-beta stocks from the page 142 scanner. The course's ETF content is
one module, p203-212, on TVIX, UVXY and JNUG. TVIX was delisted in 2020 and
Credit Suisse terminated the ETNs in 2023, so it cannot be fetched or traded.
`scripts/fetch_cache.py` was written for Zac to pull a mainstream ETF universe;
the fetch has to be his because the credentials are on his machine.

Note for that run: **page 142's beta >= 2 filter must come off for ETFs.** It is
a stock-selection filter, SPY is beta 1.0 by construction, and the course never
applies a scanner to its ETF module at all, it uses a hand-picked watchlist.
`--no-beta-filter` does this and the change is deliberate, not a convenience.

One limit of the whole ledger, stated because it will not show up in any table:
of roughly 22 elevating factors the course names, only the price-derived ones are
implemented. Analyst targets, insider buying, catalysts and overreaction news are
absent, as are dilution, delisting threat and insider selling on the other side.
A ledger built from price bars alone cannot see the reasons a stock is cheap, and
those absences are not symmetric.

### Two fixes shipped: open-based confirmation, and fail-loud on the scan

**1. `screens/trend.py` now tests the OPEN against the short SMA.** Page 116:
"FIRST CANDLESTICK HOLDING (OPENING) ABOVE THE BLUE SMA LINE". Until today the
live scanner tested the close on both averages, which admitted any bar that
opened under the 9 and recovered by the bell. That is not the bar the course
names, and it was going out on the phone every day. `backtest.trend_mask` was
changed in the same commit, because a test asserts the two agree condition for
condition and they must not drift apart.

The LONG SMA still tests the close. Page 115 item 4 asks only whether you are
"trading above the long-term SMA line" and names no price field, so there was
nothing to correct.

Three fixtures in `test_backtest.py` failed on the change. All three pinned
`open` below the fast SMA while testing something else entirely (the RSI gate,
gate 1, confirmation-as-an-event), using the open only as a distinct fill price.
Updated to sit above the fast SMA while staying distinct from the close, with a
comment saying why, so the next person does not read it as arbitrary.

**Expect the candidate count to move.** Yesterday's 94 was computed on closes.
This is a real change to what the daily message contains, not a refactor.

**2. The scan now fails loudly on systemic errors.** Two checks in `cli.py`:

- If 90% or more of the universe fails with ONE identical message, that is not a
  provider hiccup. It is missing credentials, a dead endpoint or a broken build.
  The threshold is not 100%, because a couple of tickers can be delisted while
  the real fault takes down everything else.
- If `--telegram` is requested and the token is absent, that is a
  misconfiguration rather than a lost convenience, and it now exits non-zero.
  A genuine HTTP failure still does not fail the run: the numbers are the
  product and a job that goes red on every rate limit is a job you ignore.

Verified end to end rather than only in unit tests, because the tests assert the
predicates and the bug would have been in the wiring:

```
scan --offline                          exit 0   (no false positive)
scan --offline --telegram, no token     exit 1   FAILED --telegram was requested but ...
scan --source alpaca, no credentials    exit 1   FAILED 4 of 4 tickers failed with one identical error
```

The third is the 12 and 13 August failure reproduced exactly. It now exits 1.

369 tests passing.

### Open items

1. ~~Make the scan fail loudly on systemic errors.~~ **DONE**, see above.
2. **Digest history is last-write-wins.** A re-run overwrites the record of what
   the tool claimed that day. Consider writing re-runs to a suffixed filename.
3. **The 92% problem is still the live question.** Three touches makes support
   sparse enough that gate 1 usually cannot be evaluated. The swing-low
   definition used in this session's script always answers. Choosing between
   them is a rulebook change that needs pre-registering, not tuning.
4. **The breakout screen still has the page 77 to 81 fidelity faults**, and the
   0-100 scorecard from page 115 is still unbuilt.
5. **Nothing has been measured on ETFs yet.** Zac trades ETFs; every number in
   this session is stocks. Blocked on him running `scripts/fetch_cache.py`.
6. ~~Open versus close in the live scanner.~~ **DONE**, see above.
7. **The elevating-factor threshold is inert at 2.** Measured: it blocks zero
   entries, because direction and MACD are two-sided, so clearing the
   zero-deprecating rule already supplies two elevating factors. If the count is
   meant to bind it has to be 3 or higher, or the two-sided factors have to come
   out of the count. Zac's call, not a bug.

### Next session opens with

The two-week review of the daily scan is scheduled for 25 August. It now has
eleven days of digests worth reading, since the first two were empty. Before
then, item 1 above, because a review of a scan that can fail silently is a review
of the wrong thing.

---

## Session 5, Tuesday 11 August 2026

**Where it started:** a breakout screen rebuilt against the course and never
measured, sitting uncommitted in the tree.
**Where it ended:** measured, on terms fixed before the run, with the best mean
in the project and the least trustworthy reason for it. Plus a crash bug in the
screen that had been silently deleting its own best signals.

### What was built

**`breakout_path.py`, the screen at every bar.** The trend screen is a
coincidence — four numbers from bar t in the right order — so it vectorises into
`trend_mask`. The breakout screen is a sequence: a level exists, breaks, is
pulled back to, is closed above, and the breaking bar has to stay identifiable
afterwards so its volume and its three-bar setup can be read. None of that
survives being flattened into column comparisons.

Brute force is `screen_breakout(df.iloc[: t + 1])` at every bar, which measured
at 41 seconds per ticker, about five hours for the universe, per run. The
incremental version carries the level set forward instead of rebuilding it and
does the universe in 8 seconds.

The saving rests on two facts that make it exact rather than approximate.
Truncating a frame is a prefix filter on swings, because `swing_points` uses a
centred window and a swing at bar i is unknowable until bar i + lookback prints.
And a collapsed run of adjacent swing bars is a prefix extremum, so the touch a
run contributes moves as the run fills in. `nearest_levels` takes the shortcut on
that second one — it collapses over the full series once — which is harmless
there and would have been fatal here.

**The equivalence test is the point.** A fast path nobody checks is a second,
secret strategy: the backtest measures one thing, the digest runs another, and
the README describes something nobody trades. `tests/test_breakout_path.py`
asserts the two return identical passes and identical scores, bar for bar.
Verified against 46,320 bar-by-bar comparisons on 40 real tickers with zero
mismatches, then pinned in CI on seeded random walks shaped to hit the case most
likely to diverge — flat runs, where the collapsed representative moves.

**`run(screen=...)` was the only change to the harness**, because signal
generation was already a seam. The breakout arm reuses the count-matched,
gap-thinned, permutation-tested control unchanged, which matters: that control
took an outside review to get right and reimplementing it would have thrown that
away.

### Two bugs in the screen, found by running it over everything

**A `ZeroDivisionError` on a baby bar with no body.** `_three_bar_setup` divides
the ignition body by the largest baby body, and a bar closing exactly where it
opened makes that zero. The snapshot contains 6,380 such bars across 251 of 272
tickers, so this is an ordinary shape.

Worth recording how it hid, because the mechanism generalises. `scan` catches
per-ticker exceptions and files them as data errors, so this never looked like a
bug — it looked like a handful of tickers with bad feeds. **A crash inside a
`try` that logs and continues is invisible exactly in proportion to how well the
error handling works.** And the bias pointed the wrong way: a zero-body baby is
the largest possible ignition-to-baby contrast, so this was discarding precisely
the setups that would have scored highest.

**A duplicated `_normalise`**, second definition silently shadowing the first.
Identical apart from clamp order, so no behaviour change, but two definitions of
one name is a merge waiting to be resolved the wrong way round.

### The measurement

Terms written into `PRE-REGISTRATION.md` and committed **before** the run:
hypothesis, universe, statistic, decision rule, 6,000 replicates so the corrected
bar is resolvable at all, and the commitment that no second breakout variant gets
run against this snapshot whatever comes back. `TESTS_RUN` went 24 to 27 in the
same commit as the harness, before the run rather than after.

Sample size was counted first with a `--count-only` pass that stops before any
return is computed, because the power statement needs the sample size and the
sample size gives away nothing about the answer.

**178 out-of-sample trades across 93 names.**

| 20-session horizon | screens | random |
| --- | --- | --- |
| mean | +5.18% | +1.55% |
| median, the typical trade | -0.04% | +0.31% |
| hit rate | 49.7% | 54.3% |
| mean, best 5% removed | +0.13% | -0.20% |

The best 5% of trades supply 5.05 of the 5.18 points. The typical breakout trade
loses, and loses by more than a random name from the same universe would have.
The screen wins less often than chance at all three horizons and wins bigger when
it wins.

Both halves of that are worth holding at once. It is the shape a breakout
strategy is *supposed* to have — many small losses waiting for the move that
runs — so the skew is not evidence against the method. It is also the shape a
mean cannot measure and 178 trades cannot resolve, because everything rests on a
dozen trades in the tail and how many of those a five-year window caught is
mostly luck. At 20 sessions the run could only have certified 4.68 points and
1.65 was on offer: **underpowered, not negative**, same verdict as gate 1 by a
different route.

The trimmed-mean statistic was built to ask whether an apparent edge is really a
few outsized winners. First time the answer has been yes, and first time that
question has changed how a result reads.

In sample the screens lose badly to the control (-0.35% against +2.65% at 20
sessions, 54 trades). Small, fitted, no weight either way — recorded rather than
dropped, because it is not a number that would have been left out if it had gone
the other way.

### What was decided, and what it forecloses

- **No further breakout variants against this snapshot.** A 5.18% mean invites
  exactly one more slice to find the subset producing the tail. That is the move
  the pre-registration exists to prevent, and the temptation is the evidence it
  was needed.
- **The breakout screen stays in the daily digest.** Nothing here says it is
  broken. It says this data cannot tell.
- **Added to the February 2027 test**, which now has a family of two and a bar of
  97.5% rather than one and 95%. Gate 1 pays for that and it is the right price.
  Stated in advance: six months of fresh data is roughly 20 breakout trades and
  will probably also come back underpowered. The answer then is to keep waiting,
  not to lower the bar. Two years is the realistic horizon for a tail question.

### Open items

1. **The asymmetry in `_three_bar_setup` is real and was deliberately not
   fixed.** A fat baby found while testing the 3-bar shape returns immediately,
   so the 4-bar shape never gets tested. It is not obviously intended. It was
   left alone because `breakout_path` has to match the screen exactly for the
   equivalence test to mean anything, and fixing it in one place and not the
   other would put a silent difference between the digest and the backtest.
   Fix both together or neither.
2. **`breakout_retest_window` is dead config.** It is 15, but
   `level_break_lookback` is 5 and the retest has to happen after the break, so
   the retest never gets more than 5 bars. Either the break window should widen
   or the retest window should be honest about being 5.
3. **The measurement bypasses the provider layer.** `scripts/measure_from_cache.py`
   reads `cache/*_1500d.csv` directly, because `YFinanceSource` expires its cache
   after 12 hours and a result quoted in the README should not move under you.
   That is the right property for a measurement and a wrong one to have arrived
   at by accident — the cache expiry and the watchlist provenance are still the
   open items they were.

### Two findings from talking it through afterwards

Both came out of Zac describing how he actually reads a chart, and both are
measurements rather than opinions.

**The breakout result is one quarter.** 2026Q2 supplied 75% of all P&L, 2026Q1
and Q2 together 93%. Over the first two years of the hold-out — 118 trades — the
screen returned +0.54% a trade against the control's +0.61%, so it slightly
underperformed. The top 10 of 175 trades account for the entire total, and the
biggest (MXL, +329%) gapped 59% on news eleven sessions after entry. Bars
checked; it is real data, not a split artefact. This belongs next to the
percentile, because "underpowered" understates it: a result concentrated in the
last four months of the sample is the shape of something that will not repeat.

**Gate 1 cannot be evaluated 92% of the time — and getting to that took being
corrected.**

First attempt claimed the entry sequence produces ZERO signals in five years.
That was wrong, and the error is instructive: it implemented Zac's rule as a
coincidence at one bar, requiring the RSI dip within 10 sessions of the SMA
reclaim. He pushed back — the dip ARMS the name, it stays armed, and the rest of
the setup completes whenever it completes. He was right. Exactly the mistake
this project already documented once, when CONFIRMATION was found to be an event
rather than a state.

Rebuilt as a state machine from 3,621 RSI crossings below 30:

| Stay armed | Reclaims both SMAs | Then ignition | Then R:R >= 2 |
| --- | --- | --- | --- |
| 21 sessions | 130 | 110 | 1 |
| 63 sessions | 307 | 257 | **10** |
| 252 sessions | 1,031 | 852 | 32 |
| unbounded | 3,088 | 2,636 | **67** |

The sequence completes readily — 257 setups at a realistic three-month patience
limit, comparable to the breakout screen's 246, so it is entirely measurable.

What kills it is gate 1, and not for the reason first supposed. Of 2,636
completed setups only **212 have a measurable reward:risk at all**; 92% have no
three-touch level above or below, so the ratio is undefined. Of the 212 that can
be computed the median is 0.74 against a required 2.0.

That is a fact about the level definition, not the market. Three confirmations is
the rulebook's rule, faithfully implemented, and it makes levels sparse enough
that the gate resting on them usually abstains. **A gate that declines to answer
nine times in ten is not filtering.**

The ignition bar is genuinely absent as a gate — `trend.py` never mentions it,
the breakout screen only scores it — but it is not the binding constraint either:
2,636 of 3,088 reclaims produce a valid setup, an 85% pass rate.

**What counts as support** is the live question. Three touches leaves the gate
blind 92% of the time; an eye marks the recent swing low and always has an
answer. Written up in the workspace notes under section E.

Recorded but NOT acted on. Changing the level definition is a change to the
rulebook and needs pre-registering, not tuning until signals appear.

### Next session opens with

Nothing, deliberately. The daily scan is being left alone until the **25 August
review**, so that the next thing built is aimed at a real complaint rather than a
guess. A scheduled task will open that review.

Two candidates now sit ahead of the scorecard, both from the conversation above:
settling the support definition, and building a control arm that randomises
DATES rather than names — because the current design holds dates fixed by
construction and is therefore blind to any timing edge, which is exactly what an
RSI rule is.

If something gets built anyway, the **0-100 scorecard from page 115** is the one
item that makes the digest more useful without making any new claim about whether
the signal works.

---

## Session 4, Monday 10 to Tuesday 11 August 2026

**Where it started:** three unmeasured screens and a hope.
**Where it ended:** one candidate the data cannot certify, one rule of the
rulebook that contradicts another, and a backtest that has been attacked six
times.

This entry replaces an earlier version written mid-session that reported a
"rigorous null result". That conclusion was wrong and the reason it was wrong is
the most useful thing in this log. See **The error that mattered most**.

### The result

Out of sample, 2024-01-01 onward, 0.2% round-trip costs, entry at the
session-after open, universe rebuilt every simulated session from bars dated on
or before it. Every figure below is a percentile against 5,000 random controls
that took the same number of names on the same dates.

| configuration | 20d percentile | screens | control |
| --- | --- | --- | --- |
| trend only, state entry | ~50 | — | — |
| confirmation entry | ~50 | — | — |
| confirmation + RSI ≤ 30 | 76 | — | — |
| confirmation + RSI ≤ 50 | 95 | 3.18% | 2.36% |
| gate 1 at 1:1 | 76 | — | — |
| **gate 1 at 2:1, held** | **96** | **7.01%** | **2.69%** |
| confirmation + stops | 86 | 0.49% | 0.26% |
| **gate 1 at 2:1 + stops** | **10** | **0.22%** | **1.56%** |

Two rows matter and they are the same screen picking the same names on the same
dates. Only the exit differs.

**Gate 1 held to a horizon is the one live candidate.** 96th percentile, +4.32
points, the median improved as well as the mean, and it survived deleting its
best 5% of trades. A separate control — the same backtest on real bars with the
time ordering destroyed — put it above all twenty shuffles, p ≈ 0.048.

**Gate 1 with the course's own stop is worse than random**, and the mechanism is
mechanical rather than statistical:

```
                stopped out    worst trade
screens             77%           -9.5%
random control      57%          -20.9%
```

A 2:1 reward-to-risk ratio means a close floor by definition. Putting the stop
on that floor puts it inside daily noise for a stock chosen for beta above 2, so
four trades in five are stopped before the idea can be right or wrong. The
losses are individually smaller — the stop is working — and there are so many
more of them that the mean dies.

**The rule: never place the stop at the support level that earned the setup its
ratio.** Page 115 and page 234 are in different chapters and the course never
puts them side by side. A human reading a chart resolves the tension without
noticing. Code cannot, which is how it surfaced.

### The error that mattered most, and it was mine

A Bonferroni bar of 99.7% was declared, results were measured against it, and
failing it was written up as a finding — **without first checking whether the
data could reach that bar.**

It could not. Working from the spread of the control distribution:

| bar | effect needed per 20-day trade |
| --- | --- |
| 95% | 1.15pp |
| ~98.3% (corrected for correlated tests) | 1.48pp |
| **99.7% (declared)** | **1.91pp** |

The observed effect was 1.22pp at the time, 4.32pp against a 6.43pp bar after
the level rule was fixed. Either way the design had roughly a one-in-six chance
of certifying the effect it actually measured. **A test that answers "no" five
times out of six when the answer is yes is not evidence of absence.**

Failing an unreachable bar is an absent result, not a negative one. The report
now prints its own minimum detectable effect beside every number, and the
verdict says UNDERPOWERED in words rather than leaving it to be inferred.

### Three artefacts, each of which read as a discovery

Not bugs in the ordinary sense. Each produced a plausible, quotable, wrong
answer, and each was caught by deliberately trying to break the control.

1. **The control drew a flat three names per date** while the screens recorded
   however many fired. Signal breadth peaks when the market is extended, so the
   arms were averaged over different date weightings and the comparison measured
   the weighting. Worked example in `backtest.py`'s docstring.
2. **Under stops, trend-screened names more often had no resistance above them.**
   No target means the trailing stop never arms, so their winners ran uncapped
   while the control's were trimmed. On a feed with no predictive signal in it,
   that alone put the screens at the 96th percentile.
3. **The median is unreadable under stops.** Stopped-out trades pile into a lump
   just below zero and the median sits inside it, so a small change in stop-out
   frequency moves it enormously. On the same signal-free feed the median beat
   99–100% of controls. Now printed with a warning; the verdict ignores it.

### Six audits, and what each round still found

Every round found something. That is the point worth carrying forward.

| Round | Found |
| --- | --- |
| 1 | Flat control draw (artefact 1); single-seed control reported as evidence |
| 2 | Trailing stop could undercut the hard stop; a test that tested nothing |
| 3 | Raw proportion could print 100%, i.e. p = 0; control never thinned; `resolvable` demanded one exceedance rather than ten |
| 4 | Synthetic feed not signal-free; breakout screen could never fire on it; watchlist cache never expires |
| 5 | Fidelity: three fabricated citations; levels departing from the three-touch rule; baby bar inverted |
| 6 | Three-touch rule counting a flat plateau as eight touches; a lookahead in the universe mask; synthetic feed *still* not signal-free via Jensen curvature |

**The three misquotes are the ones to remember.** In three places the code
quoted the rulebook in the direction that justified what it already did:
`"bigger than the baby bar before it"` (the words "before it" appear in no
source, and they invert the course's 3-bar setup), `"the rulebook says the
pattern does not always appear"` (no such sentence exists anywhere), and the
`(OPENING)` dropped from page 116's definition of CONFIRMATION. All three are
corrected and the record of what was wrong is kept in the code.

**The lookahead was mine, introduced on day two.** The universe mask at bar t
required levels to bracket `open[t+1]` — tomorrow's open, in a mask indexed by
today. A live scanner running at the close could never reproduce that signal set.

### What was built

- `backtest.py` — walk-forward simulation, three arms, permutation test with the
  add-one estimator, three statistics per horizon, Bonferroni-corrected bar,
  minimum-detectable-effect reporting, and a `verdict` that distinguishes
  underpowered from negative.
- `levels.nearest_levels` — causal support and resistance at every bar, applying
  the three-touch rule, with the swing window shifted explicitly rather than by
  truncation. A test proves it agrees exactly with recomputing on a truncated
  frame.
- `exit_returns` — the rulebook's exits: hard stop at previous support frozen at
  entry, 5% trail after the target, four conservative fill decisions documented.
- `data.shuffle_returns` — real bars with the time ordering destroyed. The null
  control that does not have to be proved neutral.
- 277 tests. Every artefact above is encoded as one, so none can come back
  silently.

### What this design cannot see

- **Timing.** The control trades the same dates, so an edge in *when* scores 50
  by construction. This measures which names, never when.
- **The universe filter itself.** The pool already passed the page-142 screen, so
  the honest claim is "no incremental edge over the course's own filter".
- **Survivorship, asymmetrically.** Delisted names are absent. A random control
  would have drawn some death spirals; the screens structurally cannot pick a
  stock below both its averages. That flatters the control.

### Open items

1. **CONFIRMATION is tested on the close; page 116 says the open.** "The first
   candlestick holding *(OPENING)* above the blue SMA line". Every number in this
   log used the close.
2. **The breakout screen has never been measured, and it fails the fidelity
   check.** The baby bar is the bar before the break; the course's 3-bar setup
   puts it after the ignite bar. The wick disqualifier is a percentage of range;
   page 80 describes a positional test. It is the centrepiece of the rulebook and
   the largest remaining gap.
3. **The candidate pool is not reproducible.** `data/watchlist.txt` is not in the
   repo, `build_watchlist.py` defaults to a 500-symbol sample, and its cache never
   expires, so a rebuild across two days can mix as-of dates.
4. **RSI 14/30/70 is still an assumption**, not confirmed against Thinkorswim.
5. **The stops universe is about four tickers a day.** Requiring a three-touch
   level on both sides on top of the page-142 filter is brutal, and at that width
   the control draws from nearly the same names as the screens.

### What you should understand afterwards

- Why a control that shares the screens' bias is worth more than SPY.
- Why a single random arm is an illustration and a percentile is evidence.
- Why setting a bar without a power calculation is worse than setting no bar.
- Why the median stops being readable the moment you add a stop loss.

### Next session opens with

**Not more backtesting.** The limit is sample size and this dataset is finite.

The one experiment left is pre-registered rather than exploratory: **gate 1 at
2:1, held, 20-session mean, family of one, bar 95%, on data from 2026-08
onwards.** Write it down now, run it in six months, and do not look before then.

Otherwise: Session 5 onwards. The daily scan over the full watchlist, the 0-100
scorecard from page 115, and Telegram delivery. None of it needs an edge to be
worth having — 256 candidates down to a handful a day is real work saved — and
none of it may be sold as one.

---

## Session 3, Sunday 9 August 2026

> Written up on 10 August, after the fact, reconstructed from the diff, the
> commit and the test scaffold rather than from notes taken at the time. The
> factual half is verifiable from the code. The three understanding questions at
> the bottom are deliberately left blank, because they are the half that only
> works if you answer them yourself.

**Where it started:** `levels.py` finished, the hardest screen in the rulebook still unbuilt.
**Where it ended:** `screens/breakout.py`, 20 tests, registered and firing in the scanner.

### The decision the prompt demanded before any code

The build plan's prompt refuses to let you start: "this screen has five separate
conditions. Propose how you want to combine them into one score and wait for me
to agree." What got agreed:

**Four hard gates and one bonus.**

1. A three-touch resistance level, broken within `level_break_lookback` (gate)
2. A volume spike on the breaking bar against the average before it (gate)
3. The ignition bar test, which is two sub-checks: bigger body than the baby
   bar, and big in absolute terms against its own close (gate)
4. The baby bar's wick disqualifier (gate)
5. Follow-through, where a red second candle fails it (gate)

Dip-and-reject is the bonus. It never gates, because the rulebook itself says
the pattern "does not always appear", and a gate on something optional would
mean the screen almost never fires.

**Score is a weighted sum of three continuous readings, not of five.** The gates
are pass or fail; only volume strength, ignition strength and level recency vary
once everything has already qualified. Each is normalised 0 at its own floor to
1.0 at a "strong" ceiling, the same shape `trend.py` uses for its SMA gap, so a
very strong ignition bar can offset a merely adequate volume spike. The
dip-and-reject bonus is added flat afterwards rather than being a fourth weighted
term, because it is a bonus on top of a setup that already qualified, not a
fourth thing the setup has to be good at.

The three weights are deliberately equal at one third each. There is no evidence
yet that any of the three matters more than the others, and session 4 is what
earns the right to move them apart.

### What the tests found that the design did not

**The flip check silently failed when the chart was the wrong length.**
`classify_levels` detects a broken level by comparing against an "earlier"
reference bar. On a short hand-built chart that reference landed exactly on one
of the 100.0 resistance touches, and the strict `<` in the flip comparison then
returned false: the level had plainly been broken, and the screen reported it
had not.

The fix is `buffer_bars` in `make_breakout_chart`, a run of flat bars between the
struggle and the baby bar so the reference always lands in dead space. It turned
out to be useful twice over, because varying it is also how the tests age a
level: more buffer means more sessions between the last confirmed touch and
today, without touching the baby, ignition or follow-through bars at all. That is
what `test_a_fresher_break_scores_higher_than_a_stale_one` runs on.

This is the same class of thing as session 2's `_collapse_runs`. Not a bug in the
rule, a bug in the assumption that a rule which reads correctly on a real chart
reads correctly on a nine-bar hand-built one.

**Follow-through had to become skippable rather than failable.** If the breakout
fires on the most recent bar there is no second candle yet. Failing that would
mean the freshest breakouts, the only ones still actionable, are exactly the ones
the screen rejects. It now passes with "no follow-through bar yet, breakout is
too recent to judge", which shows up in the real digest.

**Two failure reasons where one would have done.** A level that was never broken
and a level that broke 191 sessions ago are different situations and now say so
separately. Worth it: in the first live scan over 256 tickers, those two reasons
account for most breakout rejections, and being able to tell them apart is what
shows the 5-session window is doing the work rather than the three-touch rule.

### The test scaffold, and the numbers that were worked by hand

Every chart shares one shape: a three-touch struggle at resistance 100 built by
`zigzag`, the same builder proven in `test_levels.py`, then flat buffer bars,
then baby, ignition and follow-through. Each test overrides exactly the one bar
carrying the rule under test. A failing test then points at a rule, not at a
chart shape.

The default bars, chosen so each gate sits clearly on one side of its floor with
enough headroom that a small config change cannot flip a test by accident:

| Bar | OHLC | Body | Wick | Reading |
| --- | --- | --- | --- | --- |
| Baby | 97.0 / 99.5 / 96.5 / 99.0 | 2.0 | 1.0 of a 3.0 range | 33% wick, well under the 60% disqualifier |
| Ignition | 99.0 / 109.0 / 98.5 / 108.0 | 9.0 | 1.5 | 4.5x the baby body against a 3.0x strong ratio, and 8.3% of its own close against a 1.5% floor |
| Follow | 108.0 / 111.0 / 107.5 / 110.0 | green | | closes above its open |

Volume is 1.0m on the baby and 2.0m on the ignition, so the spike reads 2.0x
against a 1.5x floor and a 3.0x ceiling: comfortably passing, deliberately not
maxed, so `test_a_stronger_volume_spike_scores_higher` has room to move.

### What was built

| File | What |
| --- | --- |
| `src/stocksignal/screens/breakout.py` | new. `screen_breakout`, four gates, three-part score, dip-and-reject bonus |
| `src/stocksignal/screens/__init__.py` | registered |
| `src/stocksignal/scanner.py` | added to `SCORING_SCREENS` |
| `tests/test_breakout.py` | new, 20 tests across 8 classes, one class per rule |

Commit `c946bfe`, "Add breakout screen: resistance break, volume spike, ignition
bar, follow-through". Coverage on `breakout.py` is 98%; the two uncovered lines
are a stale-break branch and a guard in `_normalise` that config validation
already makes unreachable.

### How it behaved on real data, a day later

First live scan over the screened 256-ticker universe on 10 August: the breakout
screen fired three times. ERO, SSRM and HMY. SSRM hit the complete pattern
including the retest, "price dipped back to the 28.74 level and got rejected
before continuing, the rulebook's preferred pattern", which is exactly pages 75
and 76 of the course.

One in 256, and it found the textbook case. That is the behaviour you want from a
screen that is supposed to be rare.

### Open items

1. **The retest may be ranked too low.** Course pages 75 and 76 treat the
   post-breakout pushback holding as *the* tell for a quality breakout, where
   this screen treats it as a flat bonus on top. Not a defect, a design question,
   and session 4 is the place to settle it with evidence rather than by argument.
2. **`level_break_lookback` at 5 sessions may be too tight.** Across 256 real
   tickers the commonest rejection is a resistance that broke 60 to 260 sessions
   ago. That may be correct, since an old break is not a trade, or the window may
   be starving the screen. The backtest can tell you.
3. **The three score weights are still equal and still unearned.** Unchanged from
   the day they were written.

### What you should understand afterwards

Left blank on purpose. Answer these in your own words before session 4, and if
you cannot, that is the signal to go back and read the file rather than the
signal to skip it.

**Why is the dip-and-reject a bonus rather than a gate, and what would it cost
you to make it a gate?**

_(your answer)_

**How would you explain the ignition bar test to someone who does not trade?**

_(your answer)_

**Why does a screen with five conditions need five tests rather than one?**

_(your answer)_

### Next session opens with

**Session 4 of BUILD-PLAN.md: the backtest.** Read section D of
`02 Projects/Trading Bot/Trading Strategy & Screens.md` first, which lists the
lookahead and survivorship traps already identified, before pasting the prompt.

---

## Session 2, Sunday 9 August 2026

**Where it started:** a repo that would not run, for a reason nobody had noticed.
**Where it ended:** `levels.py` built test first, 76 passing tests, lint clean.

### The bug that was already there

`make test` and `make scan` both failed before a line of new code was written. Three
tests in `test_scanner.py` blew up with "Length of values (120) does not match length
of index (119)".

`SyntheticSource.history` builds its index with `pd.bdate_range(end=today, periods=days)`
and its columns from numpy arrays of length `days`. Hand `bdate_range` a Saturday or a
Sunday as `end` and it returns one row fewer than `periods` asked for. Every weekday it
returned exactly `days` and everything worked. It was Sunday.

Fixed by pulling the roll back into `last_business_day(day)`, a two line function with
five tests. It lives on its own rather than inline precisely so it can be tested without
having to pretend it is a different day, which is the only honest way to test something
that depends on the date.

**Worth keeping.** The build plan's "if you get stuck" section already lists "a date that
only works today" as one of three usual suspects for a test that passes locally and fails
in CI. It turned out to be sitting in the repo the whole time.

### Session 2 proper: support and resistance

Two decisions were made before any code, which is what the build plan's prompt was for.

1. **A level is a price zone, not a typed object.** Swing highs and swing lows go into
   one pool. Nothing is born a support or a resistance; the classification comes from
   which side of the level price is sitting on today. The flip rule is impossible to
   express any other way, because the same price cannot be permanently a ceiling and
   also become a floor.
2. **Ageing: window plus a recency score.** Only touches inside `level_lookback_days`
   (252, about a trading year) count. Inside that, three touches over a year and three
   over a fortnight are both real levels, but each carries a `recency` score of 1.0
   down to 0.0 so a screen can prefer the fresh one. A hard cutoff would have thrown
   away real multi-year levels; no ageing at all would let a level untested since 2024
   clutter the digest.

### What the tests found that the design did not

The three-touch rule was quietly broken by flat charts. `swing_points` compares with
`==`, so on a stretch of equal bars every single bar is both a swing high and a swing
low. Forty flat bars produced a level with seventy two touches. `test_a_flat_chart_has_no_levels`
caught it on the first run.

The fix is `_collapse_runs`: a run of consecutive swing bars is one touch, not one per
bar, taking the highest bar of the run for highs and the lowest for lows. The rulebook
means three separate occasions, not three days in a row. This was not in the plan and
would not have been noticed without writing the test first, which is the answer to the
build plan's question about what test-first changed.

### What was built

| File | What |
| --- | --- |
| `src/stocksignal/levels.py` | new. `Level` dataclass, `find_levels`, `classify_levels` |
| `src/stocksignal/config.py` | six new level thresholds plus validation |
| `src/stocksignal/data.py` | `last_business_day`, and the weekend fix |
| `tests/test_levels.py` | new, 21 tests |
| `tests/test_scanner.py` | 5 regression tests for the weekend bug |

50 tests to 76. `ruff check` and `ruff format --check` both clean.

### Open items

1. ~~**Push events still do not trigger CI.**~~ **RESOLVED, same evening.** Pushing this
   session's commit started CI run #2 on its own, 18 seconds, nobody pressed anything.
   Nothing was changed on this side between the four pushes that produced no run and the
   one that did, which makes the session 1 guess (a new-account restriction on automatic
   triggers, lifted after a few days) the only story that fits. Steps (b) through (d) of
   the escalation plan were never needed; step (a), "push anything and look", was the
   whole answer. The stale comment in `ci.yml` claiming the trigger was broken has been
   rewritten, because a confidently worded false comment is the exact thing session 1
   caught twice.
2. **The SMA periods are still placeholders**, unchanged from session 1.
3. **`level_lookback_days` at 252 is a guess, not a measurement.** It is a defensible
   default (roughly a trading year) but nothing has tested whether a level from ten
   months ago carries any predictive weight. Session 4's backtest is the thing that
   could answer it, and it is worth coming back here afterwards.

### Two mistakes worth recording, both in the commands rather than the code

**The two-commit plan collapsed into one.** `git add -A` stages everything, so the first
commit swallowed the bug fix and the feature together and the second had nothing left to
commit. Staging is a separate decision from committing, and `add -A` throws that decision
away. To split deliberately: `git add` the specific files, commit, then add the rest.

**zsh does not treat `#` as a comment.** Commands pasted with a trailing explanation ran
as `make test '#' expect 76 passed`. bash strips it, zsh interactive shells do not unless
`interactive_comments` is set, and macOS defaults to zsh. Paste commands without trailing
notes.

### Also fixed after the push

`ci.yml` ran `ruff check` but not `ruff format --check`, so CI was weaker than `make lint`
and a badly formatted file could earn a green tick and then fail locally. Both now run.

### Next session opens with

**Session 3 of BUILD-PLAN.md: the breakout screen.** It is the hardest screen in the
rulebook and it consumes `levels.py` directly, so the shape is already familiar. The
prompt asks you to propose how five separate conditions combine into one score and wait
for agreement before writing anything, so read that part before you paste it.

---

## Session 1, Thursday 6 August 2026

**Where it started:** nothing installed except node and a Python that was too new.
**Where it ended:** a public GitHub repo with a green CI pipeline, 50 passing tests, and a working tool.

### What got done

- Installed the toolchain: VS Code, uv, Homebrew, GitHub CLI, Claude Code. Pinned the project to Python 3.12 via `.python-version`, because the system Python 3.14 was too new for pandas.
- Ran `make setup`, `make test` (50 passed) and `make scan` (a real ranked digest with reasoning attached).
- Changed `min_sma_gap_pct` from 0.5 to 2.0, watched the digest go from 6 candidates to 3, then reverted it with `git checkout .`
- Created the GitHub account, pushed the repo public at github.com/zacthorman/stocksignal.
- Ran the first real Claude Code session: diagnosed and fixed a broken CI workflow.

### The CI job, in detail

Two separate problems that looked like one.

1. **Zero workflow runs.** Actions was enabled and the workflow parsed fine, but push events were not triggering runs. Manual `workflow_dispatch` runs work. **Cause still unknown.** This is the open item.
2. **The Python matrix was fake.** `uv pip install --system` ignores the version `uv python install` just fetched and falls back to whatever Python is already on the runner's PATH, so both the 3.11 and 3.12 legs were silently testing the same interpreter. Fixed by using `uv venv --python ${{ matrix.python-version }}` and writing `.venv/bin` into `$GITHUB_PATH`, which mirrors what `make setup` does locally.

Also bumped `actions/checkout` to v7 and `setup-uv` to v9.0.0 to clear the Node 20 deprecation warnings.

First green run: both legs passed in 23 seconds.

### What was actually learned

**Three separate versions of "a new command is invisible to an already-open terminal".** uv after install, brew after install, and the venv inside a GitHub Actions job. Same problem in three costumes: the shell reads its list of available commands at startup, so a command that arrives later needs either a restart or an explicit PATH update. That is what `echo "$PWD/.venv/bin" >> "$GITHUB_PATH"` is doing, and it is why `source .venv/bin/activate` would not have worked there.

**How to read a command containing `rm -rf`.** Look for whether the `cd` before it is guaranteed to have run. `&&` chaining means each step only executes if the previous one succeeded, so `cd /tmp/x && rm -rf .venv` cannot delete the wrong `.venv`. Read the chain, do not fear the word.

**Approval prompts: read the wildcard.** `gh --version` is safe to allow permanently. `gh auth *` is not, because that same wildcard covers `gh auth token`. Narrow and specific, yes. Broad with a `*`, case by case.

**Test the fix before pushing it.** Claude Code copied the project to `/tmp`, rebuilt it on Python 3.11 and ran the whole CI sequence locally before proposing a push. Nobody asked it to. That instinct, prove it where the feedback is instant, is worth stealing permanently.

**The big one: `git diff` is the only thing that does not lie.** In one twenty-minute stretch, Claude reasoned from a plausible story and got it wrong, Claude Code reported its own edits as rejected when they had actually landed, and the editor showed a preview that looked like the real file. All three were wrong at the same time. One `git status` settled it in ten seconds. When you want to know the state of something, go and look at it rather than reasoning about what it probably is.

**A confidently worded comment that is false is worse than no comment.** Two got caught tonight. One was in the file to begin with ("every push runs the same checks you run locally", which was not true), and one arrived in a proposed fix (a claim that `setup-uv` never publishes floating major tags, which was wrong: v1 to v7 exist, it stops before v8). Both read as authoritative. Neither was checked. This is the class of thing that survives review and misleads someone eighteen months later.

**When you ask for two fixes, count two fixes.** Reading the reply is not checking. Comparing the change against your list is checking.

### Commits

| Hash | Message |
| --- | --- |
| `2c6503a` | Initial scaffold: tradability and trend screens, signal log, CLI |
| `3f3b645` | Fix CI: real Python matrix via uv venv, add workflow_dispatch |
| `bc1d7f7` | Bump CI actions off deprecated Node 20 runtime |

### Open items

1. **Push events do not trigger CI. Investigated and parked, not a local problem.** Ruled out, with evidence: the workflow file on `main` is correct (pulled the raw file from GitHub and checked the `on: push` block); Settings, Actions, General has "Allow all actions" selected; the account email is verified; there is no branch protection and no second workflow. The decisive test was making a commit from the GitHub website, so the laptop, git and Claude Code were all out of the picture. That push did not trigger a run either. Conclusion: the cause is at the GitHub account or repository level and nothing local can fix it. Best remaining guess, stated as a guess: new accounts appear to have automatic workflow triggers suppressed while manual dispatch still works. Retest in a few days by pushing anything and checking whether a run appears on its own. Not blocking: the "Run workflow" button works and CI does its job.

   **How to settle it, cheapest first. Stop as soon as one of these answers it.**

   a. **Push anything and look.** One minute. If a run appears on its own, it has cleared by itself and there is nothing to fix. Delete the workflow_dispatch comment's explanation and this whole entry.

   b. **If not, test a second repo.** Create a throwaway public repo with one trivial workflow (`on: push`, one step that echoes hello) and push to it. This separates "something about the stocksignal repo" from "something about the account", which is the only split still unresolved.
      - The throwaway repo also fails to trigger, so it is account level. Go to (d).
      - The throwaway repo works, so it is specific to stocksignal. Go to (c).

   c. **Recreate the repo.** Cheap, because the entire history lives in the local `.git` folder. Delete the GitHub repo, run `gh repo create stocksignal --public --source=. --push` again, and every commit goes back up intact. Two minutes, nothing lost.

   d. **Contact GitHub Support** at support.github.com. An account-level restriction on automatic workflow triggers is something only they can see and lift, and it is a normal thing to ask about. Give them the facts already gathered: Actions enabled, workflow_dispatch runs succeed, four push events to the default branch produced zero runs, one of those pushes was a commit made in the GitHub web editor.
2. **The SMA periods are still placeholders.** `Config.sma_fast` and `sma_slow` are 10 and 20. The rulebook says "only take trades above BOTH the red and blue SMA lines" and the real periods on the charting setup have never been written down. One line in `config.py` once known.
3. **A Claude Code allowlist has not been written.** Approval prompts are noisy because nothing has been deliberately allowed yet. Worth writing `.claude/settings.local.json` with a short list of genuinely safe commands (`pytest`, `ruff`, `git status`, `git diff`, `make test`) rather than accumulating permissions by clicking "don't ask again" when tired.

### Next session opens with

Ten minutes on open item 1, timeboxed. If it is not obvious, note it in the README as a known quirk and move on, because a manual trigger is a perfectly workable fallback and the CI does its actual job either way.

Then **Session 2 of BUILD-PLAN.md: support and resistance levels.** That is the first real feature, roughly two hours, and it unlocks the breakout screen after it. The prompt is written out in full in the build plan, so it is a matter of opening Claude Code in the project and pasting it.

Before that, five minutes re-reading `src/stocksignal/screens/trend.py` and `tests/test_screens.py`, since `levels.py` gets built in the same shape.
