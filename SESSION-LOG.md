# stocksignal: session log

A running record of what got done, what was learned, and what the next session opens with. Append to the top. Written at the end of every session, before you close the laptop, because reconstructing this from memory three days later costs you half an hour.

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
