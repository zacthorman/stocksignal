# Build plan: stocksignal

The scaffold in this repo is deliberately incomplete. Two screens are built, five are not. The parts that are built exist to show you the shape: how a screen is written, how it is tested, how it plugs into the scanner. Everything after that is yours.

Read this once before you start, then work one session at a time.

## How to use each session

Each session below gives you four things:

- **Goal**, in a sentence.
- **Done when**, which is a concrete check. Not "it works". A command that passes or a thing you can see.
- **The prompt**, ready to paste into Claude Code. These are written properly on purpose. Read them, because learning to write prompts like this is half the value of the project.
- **What you should understand afterwards.** Read these and be honest with yourself. If you cannot explain a bullet in your own words, you did not learn it, you watched it happen. Ask Claude Code to explain that specific thing before moving on.

Commit at the end of every session. Small commits with real messages are the difference between a repo that reads like work and a repo that reads like a dump.

---

# Stage 0: get it running

## Session 0. Make it yours (30 minutes)

**Goal.** Get the scaffold running on your machine and confirm every check passes before you change a thing.

**Done when.** `make test` shows 50 passing, `make lint` is clean, and `make scan` prints a table.

```bash
cd project-1-stocksignal
make setup
source .venv/bin/activate
make test
make lint
make scan
git init
git add -A
git commit -m "Initial scaffold: tradability and trend screens, signal log, CLI"
```

Then create an empty repo on GitHub and push it. Do this now, not at the end. A repo you push to from day one has a history that shows how you work. A repo you dump in one commit at the end shows nothing.

```bash
gh repo create stocksignal --public --source=. --push
```

**What you should understand afterwards.**

- What a virtual environment is and why the project has its own.
- What `pip install -e .` does differently from a normal install.
- Why `.gitignore` has `signals.db` and `cache/` in it.

---

## Session 1. Read the code you were given (1 hour)

**Goal.** Understand the scaffold well enough to extend it. No new code.

This session has no prompt to paste. Open the files in this order and read them: `models.py`, `config.py`, `indicators.py`, `screens/trend.py`, `scanner.py`, `cli.py`. Then open `tests/test_screens.py` and match each test to the rule it is checking.

Then break something on purpose and watch what happens:

```bash
# Change min_avg_volume in config.py to 50_000_000 and run the tests.
# Which tests fail? Do they fail with a message that tells you why?
# Put it back.
```

When you hit something you do not understand, ask:

> In this repo, explain what `Protocol` is doing in `data.py` and why `scanner.py` never imports yfinance. Use the actual code in front of you, not a generic example. Then show me what would have to change if I wanted to add a third data provider.

**What you should understand afterwards.**

- Why a frozen dataclass is used for `Config` rather than a dict.
- What "pure function" means and why every screen is one.
- How `scanner.py` would change if you added a screen (it is one line).

---

# Stage 1: build the missing screens

## Session 2. Support and resistance levels (2 hours)

**Goal.** Turn swing highs and lows into levels, apply the three-touch rule, and flip a broken level from resistance to support.

**Done when.** `levels.py` exists with tests that assert a hand-built chart produces the levels you expect, including a break that flips one.

**The prompt.**

> Context: read CLAUDE.md and `src/stocksignal/indicators.py`, particularly `swing_points`. The trading rulebook says: mark support and resistance for long term and short term; three confirmations of a level makes it the level; a break above resistance makes it new support, and a break below support makes it new resistance.
>
> Task: add `src/stocksignal/levels.py` with a `Level` dataclass (price, kind, touch count, first and last touch dates) and a function that clusters swing points into levels. Prices that are within a tolerance of each other are the same level, and the tolerance should be a percentage from `Config` rather than an absolute number, because a 1 point band means something different on a 20 dollar stock and a 400 dollar one. A cluster counts as a level only at three or more touches. Add a function that, given levels and current price, marks each level as support or resistance and flags any level broken in the last N sessions as flipped.
>
> Constraints: pure functions only, no I/O. New thresholds go in `Config`. Write the tests first, using hand-built frames in the style of `tests/helpers.py`, and show me the tests before the implementation.
>
> Before you start: tell me how you plan to cluster, and what happens to a level that is touched three times over two years versus three times in a fortnight. I want to decide that behaviour, not discover it later.

**What you should understand afterwards.**

- Why the tolerance is a percentage and not a fixed amount.
- What clustering is doing, in your own words, without saying "it groups them".
- Why writing the test first changed what the function ended up looking like.

**Commit.** `Add support and resistance level detection with the three-touch rule`

---

## Session 3. The breakout screen (2 to 3 hours)

**Goal.** The hardest screen in the rulebook, and the one worth the most.

**Done when.** `screens/breakout.py` passes a chart you built to look like a textbook breakout and rejects one with a fat wick on the small bar.

**The prompt.**

> Context: read CLAUDE.md, `src/stocksignal/screens/trend.py` as the pattern to follow, `src/stocksignal/levels.py`, and `body_and_wick` in indicators.
>
> The rulebook on breakouts, verbatim: the best breakouts show a dip and reject first, so it breaks out, dips, the dip gets rejected, and it continues up. The igniting bar must be big, and bigger than the baby bar before it. Massive wicks on the baby bar disqualify it. After a struggle period, a break above the moving averages counts only if the follow-through is strong, and a red second candle means it is still being beaten down rather than a play. Ask whether it has broken the resistance from the previous run-up, and whether the ignition bar is strong.
>
> Task: implement `screen_breakout(df, quote, cfg) -> ScreenResult`. It should require a three-touch resistance level broken in the last few sessions, a volume spike on the breaking bar against the recent average, an ignition bar test comparing the breaking bar's body against the prior bar's, a wick disqualifier on the prior bar, and a follow-through check that fails on a red second candle. The dip-and-reject pattern should be a bonus that raises the score rather than a hard requirement, because it does not always appear.
>
> Constraints: every threshold in `Config`. Every pass and every failure populates `reasons` with the actual numbers, not just the verdict. Tests first, one test per rule above, each with a hand-built frame that isolates that rule. Register the screen in `screens/__init__.py` and add it to `SCORING_SCREENS` in the scanner.
>
> Before you start: this screen has five separate conditions. Propose how you want to combine them into one score and wait for me to agree, because there are several defensible ways and I want to pick.

**What you should understand afterwards.**

- Why the dip-and-reject is a bonus rather than a gate, and what it would cost you to make it a gate.
- How you would explain the ignition bar test to someone who does not trade.
- Why a screen with five conditions needs five tests, not one.

**Commit.** `Add breakout screen: resistance break, volume spike, ignition bar, follow-through`

---

## Session 4. Backtest the screens honestly (3 hours)

**Goal.** Answer the only question that matters. Do these screens beat just buying the index?

This is the session that turns the project from a toy into evidence, and it is the one you will talk about in an interview. Do not skip it because it is less fun than building features.

**Done when.** `stocksignal backtest --from 2020-01-01` prints hit rate, average return at 5, 10 and 20 days, and the same numbers for buying SPY on the same dates.

**The prompt.**

> Context: read CLAUDE.md and `scanner.py`. The project overview says the honesty gate for this whole thing is a backtest against a tracker benchmark, and that if the screens do not beat it after costs, the correct outcome is to buy the tracker and keep the tool as a monitor. I want that answer, not a flattering one.
>
> Task: add `src/stocksignal/backtest.py`. Walk a historical window forward one session at a time, run the scanner using only data available up to that session, record every signal it would have produced, and then measure what actually happened over the next 5, 10 and 20 sessions. Report hit rate, mean and median return, worst drawdown, and the same measures for buying SPY on every signal date as the benchmark.
>
> Constraints, and these are the whole point of the session: no lookahead. The scanner must never see a bar dated after the day being simulated. Write a test that deliberately tries to leak future data and asserts that the backtest refuses it. Include a fixed cost assumption per trade and state it in the output, because a strategy that wins before costs and loses after is a losing strategy.
>
> Before you start: list every way lookahead bias could creep into this design, then tell me how each one is prevented. I want to see that list before you write code.

**What you should understand afterwards.**

- What lookahead bias is and the three specific ways it sneaks in.
- Why a hit rate on its own is close to meaningless without the return distribution.
- What the benchmark comparison actually told you, and what you are going to do about it.

**Commit.** `Add walk-forward backtest with benchmark comparison and lookahead guards`

---

## Session 5. Exit alerts and the red-day module (2 hours)

**Goal.** Screens 6 and 7 from the rulebook, which are the ones that watch rather than hunt.

**Done when.** You can register a holding, and a scan tells you when the rulebook says to consider selling. A breadth trigger switches the digest into red-day mode.

**The prompt.**

> Context: read CLAUDE.md and `signal_log.py`. Two more screens from the rulebook.
>
> Exits, verbatim from the rulebook: the first red candle under the moving average is a warning; only hold trades above both averages; the hard rule is to sell when a candle opens below the slow average; winners get a 5 percent trailing stop; on a sell signal ask whether you would open a position at this new low, and if not, sell. That last one is judgment and the tool must not pretend to do it, so it becomes a prompt in the output, not a decision.
>
> Red day, verbatim: keep a list of ETFs that trade well on red days, including inverse and leveraged; form a hypothesis, list the ETFs, set alerts, evaluate whether the confirmation is good.
>
> Task: add a `holdings` table to the signal log with ticker, entry price, entry date and size, plus CLI commands to add, list and close a holding. Add `screens/exits.py` producing alerts against open holdings. Add `screens/red_day.py` with a breadth trigger, defaulting to SPY or QQQ down more than 1.5 percent, that switches the digest to a separate red-day watchlist.
>
> Constraints: the trailing stop needs the high water mark since entry, so think about whether you store it or recompute it, and tell me which you chose and why. Exit alerts are alerts only, the tool never says sell as an instruction. Tests for each rule.
>
> Before you start: ask me anything about the trailing stop that is ambiguous in the rules above. There is at least one real ambiguity in there.

**What you should understand afterwards.**

- The difference between storing a derived value and recomputing it, and when each is right.
- Why "would I buy at this new low" cannot be automated, and why saying so in the output is better than faking it.
- How a schema change to an existing SQLite database is handled.

**Commit.** `Add exit alerts against open holdings and the red-day breadth module`

---

# Stage 2: make it a real tool

## Session 6. Fill the coverage gaps (1 hour)

**Goal.** `digest.py` and `cli.py` are at zero coverage. Fix that.

**Done when.** `make cov` shows every module above 80 percent, and you can explain why the remaining misses are acceptable.

**The prompt.**

> Context: run `make cov` and read the report. `digest.py` and `cli.py` are untested.
>
> Task: add `tests/test_digest.py` asserting on the markdown renderer's output for a report with signals, one with none, and one with errors. Add `tests/test_cli.py` using typer's `CliRunner` to check exit codes, that `--tickers` and `--watchlist` both work, that an empty watchlist exits non-zero, and that `--save` writes a file to a tmp_path.
>
> Constraints: no test may write to the real `signals.db` or to `out/`. Use pytest's `tmp_path` fixture. Do not test the rich terminal output character by character, because that is testing rich rather than testing your code. Test the markdown, which is yours.
>
> After: tell me which lines are still uncovered and which of those genuinely do not need a test.

**What you should understand afterwards.**

- Why chasing 100 percent coverage is usually a waste, and what number is actually useful.
- The difference between testing your code and testing your dependency.
- What `tmp_path` gives you that a hardcoded temp directory does not.

**Commit.** `Cover the digest renderer and CLI`

---

## Session 7. Ship it on a schedule (1 to 2 hours)

**Goal.** The scan runs every weekday morning without you.

**Done when.** A GitHub Actions workflow runs the scan on a cron, and the digest reaches you.

**The prompt.**

> Context: read `.github/workflows/ci.yml` for the pattern.
>
> Task: add `.github/workflows/daily-scan.yml` that runs on a weekday cron shortly after the US market opens, installs the project with the live extra, runs the scan against `data/watchlist.txt`, and delivers the digest. For delivery, start with committing the markdown digest to a `digests/` folder in the repo, because it is the simplest thing that works and gives me a dated history for free. Then add an optional Telegram delivery step behind a repository secret, skipped when the secret is absent.
>
> Constraints: no secrets in the repo, ever. The workflow must not fail the run when yfinance is rate limited, it should report the errors in the digest and exit zero, because a red tick every time a free API hiccups trains you to ignore red ticks. Explain cron syntax in the file as a comment, including the timezone GitHub uses.
>
> Before you start: tell me what happens if the scan finds nothing, and make sure that case still produces an artefact rather than silence.

**What you should understand afterwards.**

- How GitHub Actions secrets work and why an environment variable beats a config file.
- What UTC does to a cron schedule when British Summer Time ends.
- Why a workflow that fails on a flaky dependency is worse than one that reports and continues.

**Commit.** `Add scheduled weekday scan with digest history and optional Telegram delivery`

---

## Session 8. The README and the honest write-up (1 to 2 hours)

**Goal.** Make the repo readable by someone who has thirty seconds.

**Done when.** The README shows what it does, a real terminal screenshot, the backtest result including if it was bad, and how to run it.

**The prompt.**

> Context: read the current README.md. It was written for the scaffold and is now out of date.
>
> Task: rewrite it for the finished project. Include a screenshot of real terminal output, the actual backtest numbers from session 4 including the benchmark comparison, a short architecture section, and a limitations section that is honest about what a daily-bar screener cannot see.
>
> Constraints: no invented numbers, ever. If the backtest said the screens underperform the benchmark, the README says that and says what you concluded. A portfolio project that reports a bad result and reasons about it is worth more than one that quietly omits it, and any interviewer worth working for knows that.

**What you should understand afterwards.**

- Why the limitations section is the part an experienced engineer reads first.
- How to describe a negative result without either hiding it or apologising for it.

**Commit.** `Rewrite the README for the finished tool`

---

# If you get stuck

**yfinance returns an empty frame or nothing at all.** It rate limits aggressively and quietly. Check the cache first, wait a few minutes, and fall back to `--offline` to confirm the problem is the provider and not your code. This is exactly why the protocol exists.

**A test passes locally and fails in CI.** Almost always one of three things: a date that only works today, a file path that only exists on your machine, or a package you installed globally months ago and forgot. Run `make clean`, recreate the venv from scratch, and run the tests again.

**pandas gives you a `SettingWithCopyWarning`.** You have a view where you thought you had a copy. Use `.copy()` explicitly when you slice a frame you intend to modify. Better still, do not modify frames at all, return new ones.

**A screen passes everything or nothing.** Print the intermediate values on one ticker before you touch the logic. Nine times out of ten a threshold is off by a factor of a hundred because one side is a percentage and the other is a fraction.

**The moving average is NaN when you expected a number.** `min_periods=window` means the first window minus one values are NaN by design. Check you have enough history before you index into `.iloc[-1]`.
