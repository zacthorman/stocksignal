---
type: build-note
project: "Trading Bot"
date: 2026-08-30
module: balance_sweep.py
status: complete
tags: [project/trading-bot, type/build-note]
---

# The sweep, and what 220 balance sheets said about the layer

`balance.py` had only ever been run on two names. Two is enough to show a module
works and nowhere near enough to show it is useful. This is the whole watchlist.

## The bar, set before the run and written into the script

The failure mode to rule out was Gate 1's, not a bad number. A filter that
abstains nine times in ten is not filtering, and one that flags four names in
five is not filtering either. So `analyse()` carries the thresholds above the
results:

- over 50% UNKNOWN reads ABSTAINS
- over 60% flagged hard reads TOO LOOSE
- under 3% reads TOO TIGHT

## The distribution, on 220 read and 36 failed

| Verdict | Count | Share |
| --- | ---: | ---: |
| SOLID | 86 | 39.1% |
| WATCH | 60 | 27.3% |
| CONCERN | 50 | 22.7% |
| AVOID | 5 | 2.3% |
| UNKNOWN | 19 | 8.6% |

**25% flagged hard, 8.6% unreadable.** Inside every threshold, so on its own
terms the layer discriminates. Three findings say what that is worth.

## 1. Forty-four per cent of CONCERN is one fact counted twice

The two receivables flags are the two most common on the board, at 27.7% and
21.4% of names. They share a numerator. Receivable growth against payables and
receivable growth against revenue are two readings of one number, and 30 of the
47 names that trip the payables flag trip the revenue one as well.

Two SERIOUS flags is the rule that promotes WATCH to CONCERN. So:

> **22 of the 50 CONCERN verdicts have no other serious flag at all.** Their
> entire case is fast-growing receivables, stated twice, and the second
> statement is what moved them up a band.

That is not a wrong reading. Receivables outrunning both payables and revenue is
worse than outrunning one of them. But the verdict ladder counts flags, and
counting two views of one fact as two independent facts is arithmetic the module
elsewhere refuses to do. Page 131 is quoted in `balance.py` to justify not
summing the elevating and deprecating ledger, and the verdict property sums
flags anyway.

## 2. Thirty-six names are structurally invisible, and the reason is not one reason

> [!warning] This section said something false when first written, and the fix
> for it is what proved it false. Corrected below the rule.

**What I wrote, and it was a guess dressed as a finding.** Every one of the 35
"no Assets series" failures was a foreign issuer, so I concluded the cause was
uniform: `annual_series` reads `facts["facts"]["us-gaap"]` and nothing else, a
20-F filer reports under IFRS, therefore 14% of the watchlist is excluded on
domicile. The list of names supported it. ASML, TSM, ARM, STM, CCJ, TECK, the
Israeli and Taiwanese semis, the Canadian miners.

**What the honest message actually returned, on its first run.** Making the
error report which taxonomies the payload carries, rather than asserting the
company files no balance sheet, split the 36 in two:

| Cause | Count | Names |
| --- | ---: | --- |
| Files no us-gaap facts at all | 17 | ADUR, AG, ARQQ, ASX, AUGO, BBAR, CCJ, ENLT, ERO, GFS, HBM, HMY, IPX, MT, NBTX, TECK, TSM |
| Files us-gaap facts but no `Assets` tag | 18 | ARM, ASML, BRUN, CAMT, CSIQ, FUTU, HIMX, HSAI, IAG, IMOS, NBIS, NVMI, SA, SILC, SIMO, STM, TSAT, TSEM |
| CIK returns 404 | 1 | AYA |

**ASML and ARM do file us-gaap facts.** So the message was changed again, to
report the other accounting taxonomies in the payload alongside `us-gaap`, and
the 36 were reread. That splits them a third time, and this one is definitive:

| Cause | Count | Names |
| --- | ---: | --- |
| No us-gaap facts at all, accounts under `ifrs-full` | 17 | ADUR, AG, ARQQ, ASX, AUGO, BBAR, CCJ, ENLT, ERO, GFS, HBM, HMY, IPX, MT, NBTX, TECK, TSM |
| us-gaap facts, no `Assets`, but `ifrs-full` also present | 5 | HIMX, IAG, IMOS, SA, TSAT |
| us-gaap facts, no `Assets`, **no other accounting taxonomy** | 13 | ARM, ASML, BRUN, CAMT, CSIQ, FUTU, HSAI, NBIS, NVMI, SILC, SIMO, STM, TSEM |
| CIK returns 404 | 1 | AYA |

22 of the 36 do have their balance sheet in `ifrs-full`, so the domicile story
was right about those and only those. The 13 are a different problem, and it is
not a taxonomy problem: those companies report us-gaap and nothing else, and
still have no `Assets` tag. That third group turned out to have nothing to do
with taxonomies at all, and the next section is how long it took to find out.

**First guess at the 13: wrong.** Total assets equals total liabilities plus
equity, so `LiabilitiesAndStockholdersEquity` is the same number under another
element name and some filers tag only that. Added it, plus `AssetsNet`, with two
tests. It recovered nothing. But the diagnostic printed alongside it gave the
answer away: **ASML reports 623 us-gaap tags. STM 700. NBIS 520. CAMT 477.**
Those are not companies missing a balance sheet.

**The actual cause, found on the fourth attempt.** `annual_series`, one line:

```python
if not str(row.get("form", "")).startswith("10-K"):
    continue
```

A foreign private issuer files its annual report on a **20-F**, or a 40-F under
the Canadian MJDS, and never files a 10-K in its life. All 13 report under US
GAAP in full. Every row is stamped 20-F, so the filter dropped every fact they
have ever filed.

The filter's own docstring says its purpose is "annual, not quarterly", and the
exclusion of foreign filers was never a decision, just a side effect of writing
one form name for a document that has three. `ANNUAL_FORMS = ("10-K", "20-F",
"40-F")`, three tests, and it is fixed.

**The result, and it is the whole of the 13.** Unreadable falls from 36 to 23.
ASML comes back SOLID on 4 of 4 checks, STM SOLID on 4 of 4, ARM SOLID on 3,
along with TSEM, HIMX, HSAI and SILC SOLID, NBIS, NVMI, CAMT and CSIQ on WATCH,
and SIMO and FUTU as UNKNOWN.

**This is a scope change, not only a bug fix.** It widens every EDGAR-derived
reading in the project, not just the balance layer: revenue, share count, cash
flow, the growth template. Thirteen foreign filers that previously returned
nothing now return numbers everywhere. Reverting is one line.

**The point is not the taxonomy.** A plausible cause fitted all 36 names, was
consistent with every one of them, and was wrong. Then the second explanation
was wrong. Then the third. Each was true as far as it went and each pointed away
from a one-line form filter, and the only reason the loop terminated is that
every wrong message was replaced with one that reported what the code had
actually looked at. "14% excluded on domicile" was four wrong answers away from
"the filter names one form and there are three".

## 3. CORZ is a confirmed false AVOID

Core Scientific returns AVOID on a CRITICAL negative-NTAV flag reading:

> "the intangibles are NOT mostly goodwill, so they were largely
> self-generated. Strip them and the equity is worth less than nothing."

**Core Scientific reports no intangibles at all.** `intangible_pct` is null,
soft assets are zero, and NTAV equals NAV at -963m. Its equity is negative
because liabilities exceed assets, which is a serious finding and a completely
different one from the mining company that capitalised its drilling.

The rule reaches AVOID through `acquisitive`, which needs `goodwill / soft_assets
> 0.5`. With no goodwill and no intangibles that test is false, so the branch
that fires is the one written for self-generated intangibles. The CRITICAL
branch needs to require that intangibles exist before blaming them.

The other four AVOIDs (CMCO, IART, NX, WW) are all acquisitive companies with
real goodwill, which is precisely the case the 18 August patch was written to
downgrade from CRITICAL to SERIOUS. Whether that patch is working on them cannot
be checked from this output, because **`to_dict` records `intangible_pct` but not
goodwill or intangibles separately**, and the CRITICAL-versus-SERIOUS split turns
on exactly that ratio. A reading that cannot be audited from its own record is
the thing this project keeps deciding not to accept.

## Coverage, and the check that is quietly weakest

| Check | Answered | |
| --- | ---: | ---: |
| 1 cash | 215/220 | 97.7% |
| 2 current and tangible | 212/220 | 96.4% |
| 3 debt | 134/220 | 60.9% |
| 4 receivables | 179/220 | 81.4% |

Check 3 abstains on 86 names, and the leverage flag can only fire on the 134
that answer it. A company filing no debt tag this module reads is structurally
easier to clear. Half of all SOLID verdicts (43 of 86) rest on three checks
rather than four, which the verdict rule permits by design, the SEZL case.

## Verification

Both known answers reproduce, to the dollar.

- **TEM**: CONCERN, three SERIOUS flags, check 3 abstaining, NAV 491,326,000,
  NTAV -334,138,000, receivables +101.0% against revenue +83.4%.
- **SEZL**: SOLID, check 4 abstaining on a missing trade receivable line, NAV
  169,811,000, NTAV 166,480,000.

## What the real data forced, which is the fifth time

Two defects in `balance.py`, both live for twelve days, both invisible to 20
passing tests.

**The capitalised-costs guard read `(self.revenue_growth or 0) < 20`**, treating
a company with no comparable prior-year revenue as one growing at 0%. That is
missing-is-zero, the single rule the module is built around never breaking. It
surfaced only because the message then formatted that `None` and stopped the
sweep at TER, name 58. Had the message not needed the number, the flag would
have gone on firing on every company whose revenue growth is simply unknown and
nothing would have caught it. The flag compares two growth rates, so with one
missing it now abstains.

**The intangibles flag printed "NAV is 0m"** for a company reporting assets and
intangibles but neither liabilities nor equity. Same class, silent version.

Three tests added, 23 passing.

The sweep itself now wraps its loop in `finally: save(...)`. Deliberately not an
`except`: a defect inside `balance.py` should still take the run down loudly,
because per-ticker exception handling is how this project once hid a
`ZeroDivisionError` that was discarding its own best signals. Loud, but
resumable.

## What this says about wiring it into the daily scan

The layer discriminates, so the wiring job is worth doing, and three things
should be fixed first because each of them would otherwise be wired in too.

1. The CRITICAL branch blaming intangibles that do not exist.
2. The verdict ladder promoting on two views of one number.
3. `to_dict` not carrying the goodwill split its own verdict depends on.

The foreign-issuer gap is a scope decision rather than a fix, but a scan that
silently drops ASML, TSM and ARM should say so on the digest rather than in a
build note.

## Files

- `scripts/balance_sweep.py`, the sweep and the analysis, resumable
- `out/balance-sweep.json`, 220 readings and 36 named failures
- `src/stocksignal/balance.py`, two fixes
- `tests/test_balance.py`, three tests added, 23 passing

Nothing here is financial advice, and every entry and exit is your decision.

---

# Wired in, same day

The three defects above are fixed and the layer now reaches both surfaces.

## The three fixes, and what they move

| Verdict | Before | After |
| --- | ---: | ---: |
| SOLID | 86 | 86 |
| WATCH | 60 | 83 |
| CONCERN | 50 | 28 |
| AVOID | 5 | 4 |
| UNKNOWN | 19 | 19 |

Flagged hard falls from 25.0% to 14.5%, and every name that moves is one of the
23 identified as double-counted or falsely blamed. Nothing else shifts, which is
what a targeted fix should look like.

**These are the measured numbers, not the projection.** They were first
simulated from the recorded flags of the pre-fix run and then reproduced exactly
by a fresh 256-name sweep: 86 / 83 / 28 / 4 / 19, 14.5% flagged hard, CORZ at
WATCH on a lone negative-equity flag, TEM still CONCERN, SEZL still SOLID. The
four surviving AVOIDs are CMCO, IART, NX and WW.

1. **Negative equity is its own flag.** CORZ drops from AVOID to WATCH. It still
   reports that liabilities exceed assets by 963m, it just no longer says
   intangibles caused it when the company reports none. SERIOUS rather than
   CRITICAL, because CRITICAL returns AVOID and is reserved for the one trap the
   source describes. Making outright negative equity a disqualifier is a
   rulebook change and it is Zac's, not a bug fix's.
2. **The receivables pair votes once.** Both flags still print. A second,
   unrelated serious flag still promotes to CONCERN.
3. **`to_dict` carries `goodwill`, `intangibles`, `soft_assets` and
   `goodwill_share`,** so the remaining four AVOIDs can be audited from their own
   record.

Plus the foreign-issuer message, which now reports the taxonomies the payload
actually holds rather than claiming the company files no balance sheet.

## Where the reading now appears

**A committed store, not a live read.** `data/balance.json`, written by
`balance_sweep.py --store`. The scan runs every weekday against 256 tickers and
balance sheets change four times a year, so a live read would be 250 requests to
the SEC for an answer that changed on none of them, in a GitHub Actions job where
a slow EDGAR would take the digest down with it. The price is staleness, and
staleness is printed: the header carries the date and the age, and past 105 days
it says outright that a quarter of accounts has been filed which these readings
have never seen.

**The digest** stamps every candidate with one line. **The card** gets the whole
reading: the four spot checks in his order, then every flag with the figure
behind it, because a card is a page of working and "CONCERN" on its own is a
rating.

## Two design decisions that are the actual content

**It never filters.** An AVOID still appears in the digest and still gets a card.
The scan reports and Zac decides, which is the same position as the card refusing
to invent a price target and as `balance.py` refusing to sum its own flags. A
screener that silently dropped names on a fundamentals reading would be making
the decision and hiding the reason. The digest footer says so and a test pins it.

**On the card it sits outside the ledger, above it.** Appending the flags to
`deprecating` would have been one line and it would have been wrong. Page 131
lets a big elevating factor counter a deprecating one, so a negative-NTAV flag in
that table can be talked past by three good factors, which is exactly the mistake
the source is about. It is a separate section, printed before step 1, and nothing
in the card nets it off.

Missing is not a pass, in four states now: read, unreadable with the reason,
absent from the store, and no store at all. Four different sentences. A digest
that quietly stopped carrying the second reading would look identical to one
where every company came back clean.

## Files

- `src/stocksignal/balance_store.py`, the cache and its four states
- `src/stocksignal/digest.py`, `card_render.py`, `opportunity.py`, `cli.py`,
  `scripts/cards.py`, the wiring
- `tests/test_balance_store.py`, 14 tests. Full suite 502 passing, ruff clean

Nothing here is financial advice, and every entry and exit is your decision.

---

# The final numbers, after the form fix

| Verdict | Count | Share |
| --- | ---: | ---: |
| SOLID | 93 | 39.9% |
| WATCH | 87 | 37.3% |
| CONCERN | 28 | 12.0% |
| AVOID | 4 | 1.7% |
| UNKNOWN | 21 | 9.0% |

**233 read, 23 unreadable. 13.7% flagged hard, 9.0% unreadable.** Still inside
every threshold, on a universe 13 names larger than the one the layer was first
judged on.

The 23 that remain are, for the first time today, a scope question rather than a
bug: 17 file no us-gaap at all and keep their accounts in `ifrs-full`, four more
(TSAT, SA, IMOS, IAG) carry between one and seven stray us-gaap tags with the
real accounts in `ifrs-full`, BRUN reports 177 us-gaap tags and genuinely no
total-assets figure, and AYA's CIK returns 404. Reading IFRS would recover 21 of
those 23 and it is a real piece of work, not a fix.

## What today actually cost, and what it bought

Six wrong error messages, each naming a cause it had not checked.

1. "no CIK: foreign issuer, ETF, or delisted", on all 256 names, when the
   watchlist parser was reading inline comments as tickers.
2. "no Assets series, cannot read a balance sheet", on 36 companies that file
   full balance sheets.
3. "the intangibles are NOT mostly goodwill, so they were largely
   self-generated", on a company reporting no intangibles.
4. "files no us-gaap facts", which was true of 17 names and false of 18.
5. "no total-assets figure under any of [three tags]", true, and pointing away
   from a form filter.
6. `make: ruff: No such file or directory`, with the ruff binary present and
   executable, because the venv's `VIRTUAL_ENV` still pointed at the vault's old
   Desktop path and `activate` was prepending a directory that no longer exists.

Every one was true as stated. Every one attributed the failure to the wrong
thing. The pattern is not carelessness in any single case, it is that a message
which asserts a cause is a claim, and a claim in an error string never gets
tested. The three that were rewritten to report what the code had actually
looked at each disproved themselves on their first run.

That is the finding worth keeping from today, more than the distribution.

## Files

- `src/stocksignal/sources/edgar.py`, `ANNUAL_FORMS` and the widened
  `ASSETS_TAGS`
- `scripts/balance_sheet.py`, the two failure messages that report rather than
  assert
- `tests/test_edgar.py`, five tests added
- Full suite 507 passing, ruff check and ruff format both clean

Nothing here is financial advice, and every entry and exit is your decision.
