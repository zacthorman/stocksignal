---
type: build-note
project: "Trading Bot"
date: 2026-08-18
module: balance.py
status: complete
tags: [project/trading-bot, type/build-note]
---

# The balance sheet layer, and what it said about TEM

Built from the UK small-cap balance sheet talk. Four spot checks, the red flags
he names along the way, and no score.

## Why this module and not another scorecard

The growth template is a price-to-sales model. It cannot see costs, margins,
debt or cash, and every card it produces says so at the bottom. Printing that
limitation on eight cards is not the same as answering it. This is the answer.

His own framing, kept in the module docstring because it is the whole argument:

> I've seen more investors do their dough buying cheap stocks without checking
> the balance sheet than any other mistake.

## The four checks

1. Does the company have enough cash to conduct its normal operations?
2. How much of the company's assets are current and tangible?
3. Does the company have debt, and if so how much?
4. Are trade receivables growing faster than trade payables?

**Not scored, deliberately.** One disqualifying flag should stop you regardless
of how the other three read. That is the same argument page 131 makes about the
elevating and deprecating ledger: it is weighed, not summed. The output is a
list of flags with severities and the numbers behind each one, plus a verdict
that is a state rather than a rating: SOLID, WATCH, CONCERN, AVOID, UNKNOWN.

**Missing is not zero and it is not a pass.** A company that does not report a
current-asset split has not passed the current ratio test, it has declined to
answer it. Every check returns nothing when it cannot be computed and says so.

## The result, on real filings

Both pulled from SEC EDGAR, 10-K facts only, keyed on period end.

### TEM, Tempus AI, fiscal 2025: **CONCERN**

| Check | Reading |
| --- | --- |
| 1 cash | 604.8m, covering 162% of current liabilities. Fine |
| 2 current and tangible | 51% of assets current, **36% goodwill and intangibles**, current ratio 3.13 |
| 3 debt | Not reported separately |
| 4 receivables | **+101.0%** against payables **+52.4%** and revenue **+83.4%** |

NAV 491.3m. **NTAV -334.1m.**

Three SERIOUS flags:

- **Negative NTAV.** Strip the 825m of goodwill and intangibles and the equity is worth less than nothing.
- **Receivables against payables, a 49 point gap.** Cash is leaving faster than it arrives.
- **Receivables against revenue, an 18 point gap.** Sales are booked faster than they are collected. 89 days of revenue outstanding, up from 81.

### SEZL, Sezzle, fiscal 2025: **SOLID**

| Check | Reading |
| --- | --- |
| 1 cash | 64.1m, covering 71% of current liabilities |
| 2 current and tangible | **88% current, 1% soft**, current ratio 3.92 |
| 3 debt | 140.0m drawn, 64.1m cash, net debt 75.9m |
| 4 receivables | **Cannot be answered.** No trade receivable line is filed |

NAV 169.8m. NTAV 166.5m, which is 98% of NAV. No flags.

## The finding

**The name the growth template rated most generously is the one the balance
sheet flags.** Tempus cleared every band on the growth card, with Scalability at
21 out of 25. The balance sheet reads CONCERN on the strength of three separate
SERIOUS flags. Sezzle, which the growth card treated more cautiously, comes back
with 88% of its assets current, 1% soft, and nothing to flag.

That is the layer doing exactly the job it was added for. The two instruments
disagree, and the disagreement is the output. A price-to-sales model looks at
Tempus and sees revenue compounding at 83%. The balance sheet looks at the same
company and sees that receivables compounded at 101%, which is to say that a
growing share of that revenue has not turned into money yet.

Not a sell signal and not a verdict on the company. It is the question the
growth card structurally cannot ask, now asked.

## What the real data forced, which is the part worth reading

Three changes, all made because a live filing broke the first version. This is
the fourth time this pattern has repeated in this project, after the `ocf_trend`
fix, the `growth_deceleration` median, and the EDGAR `fy` bug.

**1. Negative NTAV was one rule doing two jobs.** The first version fired
CRITICAL and returned AVOID on Tempus. That was the rule misfiring rather than a
finding. The trap in the source is a mining company that spent 30m drilling
holes and booked the spend as an asset: an intangible the company created out of
its own costs. Tempus's 825m is mostly goodwill from buying Ambry and Paige,
which is a business someone paid cash for. `intangible_pct` cannot tell those
apart. Goodwill can, because goodwill only arises on acquisition. Mostly
goodwill now reads SERIOUS with an explanation, mostly self-generated stays
CRITICAL and still returns AVOID. Two tests pin both sides.

**2. A drawn revolving facility was not being counted as debt.** Sezzle reports
139,991,000 drawn under `LongTermLineOfCredit` and files nothing under any
`LongTermDebt` tag, so check 3 abstained on a company carrying real borrowings.
Abstaining was at least not wrong, since the code returns nothing rather than
zero, but abstaining on a number that is printed in the filing is a poor result.
`LongTermLineOfCredit` and `LinesOfCreditCurrent` added, ordered after the named
debt tags so a company reporting both does not count the same borrowing twice.

**3. SOLID could be earned by silence.** Every flag needs a number to fire, so a
company that reports almost nothing collects no flags and walked away with the
best verdict on the board. That is missing-is-not-zero failing at the headline,
which is the one place it matters most. There is now a `coverage` property
recording which of the four checks actually ran, and under three of four with no
flags returns UNKNOWN. Sezzle answers three, so it keeps SOLID, but its check 4
abstention is now printed rather than absorbed.

On that abstention: Sezzle is a lender, and the nearest thing it has to trade
receivables sits in its consumer loan book. Those are different things and the
loan book was deliberately not substituted. Reporting "no trade receivable line
is filed" is the honest answer. Quietly filling the field with a loan balance
would have produced a receivables growth figure that meant nothing.

## Thresholds, and which of them are actually his

| Number | Value | Source |
| --- | --- | --- |
| Current ratio floor | 1.0 | **His.** The only threshold he states numerically |
| Intangible-heavy | 50% of assets | **Not his.** A prompt to read the NTAV, never a verdict |
| Receivable growth gap | 15 points | **Not his.** He gives the direction and no number |

The two invented ones are reporting triggers rather than rules, and the raw
figures print alongside every flag so the trigger can be disagreed with.

## Files

- `src/stocksignal/balance.py`, the module
- `tests/test_balance.py`, 20 tests, all passing
- `scripts/balance_sheet.py`, the command, so a reading can be re-derived from the filings rather than trusted because it appeared in a chat
- `src/stocksignal/sources/edgar.py`, the two debt tags added, with two tests

Full suite 414 passing. `entry_sequence_funnel.py` has 13 pre-existing lint
errors that predate this work and were left alone.

Nothing here is financial advice, and every entry and exit is your decision.
