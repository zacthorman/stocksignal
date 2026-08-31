# stocksignal: project context

Claude Code reads this file at the start of every session in this repo. Keep it current. If a convention here stops being true, change the file rather than letting the code and the doc drift apart.

## What this is

A mechanical stock and ETF screener. It turns a written trading rulebook into testable screens over daily price data and produces a ranked digest of candidates with the reasoning attached. Every signal is logged to SQLite so the calls can be scored later against what actually happened.

It surfaces candidates. It does not trade, it does not recommend, and every entry and exit is a human decision. Keep that framing in the code, the docs and the output.

## Stack

| Thing | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | Where the data tooling lives |
| Data | pandas, numpy | Standard for time-series work |
| CLI | typer | Type hints become the argument parser |
| Output | rich | Readable terminal tables for near-zero effort |
| Prices | yfinance, behind a protocol | Free, no key, and swappable when it inevitably annoys us |
| Storage | SQLite via the stdlib `sqlite3` | One file, no server, plenty for a signal log |
| Tests | pytest | Fixtures and parametrisation |
| Lint | ruff | Fast, and it does formatting as well |
| Env | uv | Fast, and it handles the venv and installs together |

## Layout

```
src/stocksignal/
  config.py       every tunable number, in one frozen dataclass
  models.py       Quote, ScreenResult, Signal
  data.py         PriceSource protocol, SyntheticSource, YFinanceSource
  indicators.py   pure maths on a frame, no I/O
  levels.py       support and resistance: cluster swing points, three-touch rule, flips
  screens/        one module per rule from the rulebook
  scanner.py      order of operations, nothing else
  digest.py       rendering, terminal and markdown
  signal_log.py   append-only SQLite
  cli.py          argument parsing, nothing else
tests/
  helpers.py      frame builders with a deliberate shape
  conftest.py     fixtures
```

## Conventions, in priority order

1. **Numbers live in `config.py`.** If a screen contains a bare threshold, that is a bug. The test suite should be able to prove a screen reads its config by passing a deliberately silly value.
2. **Screens are pure functions.** Signature is `(df, quote, cfg) -> ScreenResult`. No I/O, no printing, no network. If a screen needs new data, the source fetches it and the scanner passes it in.
3. **Reasons travel with the verdict.** A `ScreenResult` that passes or fails without populating `reasons` is incomplete. The reasoning is the product, not logging.
4. **Nothing imports yfinance except `data.py`.** The protocol exists so the rest of the codebase does not know where prices come from.
5. **Type hints everywhere**, including tests.
6. **A behaviour change comes with a test.** Not "add tests later". In the same commit.
7. **The offline path must always work.** `stocksignal scan` with no arguments and no network has to produce a digest. CI enforces this.
8. **The record is `signals/YYYY-MM-DD.jsonl`, committed, and `signals.db` is a derived cache.** This changed on 31 August 2026 and the reason is worth keeping: the scheduled scan wrote its log to `signals.db` on a GitHub runner, `signals.db` is gitignored, and the runner is destroyed a minute later, so thirteen trading days of signals were written and deleted. The `outcomes` table had never held a row. Git history is now the append-only guarantee: a day is written as a whole file, so a rerun shows as a diff rather than a second copy. Rebuild the cache with `import_ledgers` and never treat it as the source of truth.
9. **An error message reports what was observed, or it proves the cause it names.** Never both halves guessed. `"AssetsCurrent is absent"` is a fact. `"no CIK: foreign issuer, ETF, or delisted"` is a guess wearing the clothes of a finding, and a guess in an error string is the one kind of claim that never gets tested. If the cause matters, check it and then say it; if it cannot be checked, say what was looked for and what was found instead. Naming one plausible reason out of four is worse than naming none, because it stops the reader looking.

   This is a review discipline and not a lint. There is no word list that catches it: none of the six below used a hedge word, and every one of them was true as far as it went.

   > **30 August 2026, six in one day.** "no CIK: foreign issuer, ETF, or delisted" on all 256 names, when the watchlist parser was reading inline comments as tickers. "no Assets series, cannot read a balance sheet" on 36 companies that file full balance sheets. "the intangibles are NOT mostly goodwill, so they were largely self-generated" on a company reporting no intangibles. "files no us-gaap facts", true of 17 names and false of 18. "no total-assets figure under any of these tags", true, and pointing away from a one-line form filter. And `make: ruff: No such file or directory` with the binary present and executable, because the venv's `VIRTUAL_ENV` still pointed at a folder that had been moved.
   >
   > Each cost real time, because a wrong explanation that fits every case is more expensive than no explanation. The three that were rewritten to report what the code had actually looked at disproved themselves on their first run.

## Commands

```bash
make setup     # venv plus install
make test      # pytest
make cov       # pytest with coverage
make lint      # ruff check and format check
make fmt       # ruff fix and format
make scan      # offline scan of data/watchlist.txt
make live      # real data, saved and logged
```

## Standing rules for anything written here

- **Never use an em dash.** Not in code comments, docstrings, docs, commit messages or output. Use commas, full stops, colons or hyphens.
- **British English everywhere.** Colour, organise, behaviour, normalise, licence as a noun.
- No padding. Say the thing.

## How to work with me

Zac is learning to code properly, not just shipping features. That changes how you should behave in this repo.

- **Explain non-obvious choices as you make them.** One or two sentences in the response, and a comment in the code where the reason is not visible from the code itself. Skip the explanation for obvious things.
- **Propose a plan before any change that touches more than two files.** Short bullets, then wait.
- **Keep diffs small.** One idea per commit. If you find yourself changing six files, stop and split it.
- **Never leave the repo in a state where `make test` fails.** If a change is half done at the end of a session, say so explicitly and note what is missing.
- **Push back.** If the request is a bad idea, say why and offer the better version. Do not just build it.
- **Do not gold-plate.** No abstractions for a second case that does not exist yet.
- **When a test is hard to write, that is information.** It usually means the code is doing two things. Say so rather than writing a convoluted test.

## Open questions

- `Config.sma_fast` and `Config.sma_slow` are 10 and 20, which are placeholders. The rulebook says "only take trades above BOTH the red and blue SMA lines", and the real periods on the charting setup have never been written down. When Zac confirms them, change the two numbers and rerun the tests.
- Float data from yfinance is patchy. `screen_tradability` currently warns rather than rejecting on unknown float. If a better free source turns up, revisit.
