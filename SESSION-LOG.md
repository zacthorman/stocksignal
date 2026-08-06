# stocksignal: session log

A running record of what got done, what was learned, and what the next session opens with. Append to the top. Written at the end of every session, before you close the laptop, because reconstructing this from memory three days later costs you half an hour.

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
2. **The SMA periods are still placeholders.** `Config.sma_fast` and `sma_slow` are 10 and 20. The rulebook says "only take trades above BOTH the red and blue SMA lines" and the real periods on the charting setup have never been written down. One line in `config.py` once known.
3. **A Claude Code allowlist has not been written.** Approval prompts are noisy because nothing has been deliberately allowed yet. Worth writing `.claude/settings.local.json` with a short list of genuinely safe commands (`pytest`, `ruff`, `git status`, `git diff`, `make test`) rather than accumulating permissions by clicking "don't ask again" when tired.

### Next session opens with

Ten minutes on open item 1, timeboxed. If it is not obvious, note it in the README as a known quirk and move on, because a manual trigger is a perfectly workable fallback and the CI does its actual job either way.

Then **Session 2 of BUILD-PLAN.md: support and resistance levels.** That is the first real feature, roughly two hours, and it unlocks the breakout screen after it. The prompt is written out in full in the build plan, so it is a matter of opening Claude Code in the project and pasting it.

Before that, five minutes re-reading `src/stocksignal/screens/trend.py` and `tests/test_screens.py`, since `levels.py` gets built in the same shape.
