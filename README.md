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
| 2. Trend (price above both SMAs, fast above slow, gap as strength) | Built |
| 3. Breakout (3-touch resistance, volume spike, ignition bar, dip-and-reject) | Yours |
| 4. Support and resistance levels (swing clustering, break flips the level) | Yours |
| 5. Dilution and insider red flags (SEC EDGAR 424B5, S-3, Form 4) | Yours |
| 6. Red-day module (breadth trigger, inverse and volatility ETF list) | Yours |
| 7. Exit alerts on open positions (open below slow SMA, trailing stop) | Yours |

`indicators.py` already ships `swing_points`, `true_range` and `body_and_wick`, which are the raw material for screens 3 and 4. `BUILD-PLAN.md` has the session-by-session route.

## Open question, still unanswered

`Config.sma_fast` and `Config.sma_slow` default to 10 and 20. Those are placeholders. The rulebook says "only take trades above BOTH the red and blue SMA lines", and the actual periods of the red and blue lines on the charting setup have never been written down. Confirm them, change the two numbers in `config.py`, and rerun the tests. Nothing else needs to move, which is the whole point of keeping numbers in one place.
