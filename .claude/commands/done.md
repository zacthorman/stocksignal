---
description: End the session properly. Tests, run it, then a real commit message.
---

Close this session out. In this order, and stop at the first thing that fails.

1. **Run the tests.** Show me the output, do not summarise it.
2. **Run the actual thing**, not just the tests. "The tests pass" and "the tool does something sensible" are different claims and only one of them is checked by the tests. Show me the real output.
3. **Show me `git status` and the full `git diff`.** I read every diff. Do not summarise it for me.
4. **Propose a commit message**, or several if this session touched more than one concern. Say what changed, and why when the why is not obvious. Never "updates", "fixes" or "wip".
5. **List anything I nodded at without really following**, so it can go in `Questions.md`. Be honest here, this list is where the learning actually happens and an empty one is usually a lie.

Do not run `git add`, `git commit` or `git push` yourself. I run those.
