"""Superseded by `scripts/fetch_all.py`. Kept as a signpost, not as a fallback.

The first version of this fetched revenue and share count from a market data
provider. `fetch_all.py` replaced it with SEC EDGAR, which is the primary source
that provider is itself reporting, and which additionally carries the cash flow
statement, the balance sheet, recent 424B5 and S-3 filings for the dilution
check, Form 4 counts and 8-K dates.

This file is a stub rather than a deletion so that anything still calling it
fails loudly with the right instruction instead of silently doing half the job.
"""

import sys

print(__doc__)
print("Run this instead:")
print('  .venv/bin/python scripts/fetch_all.py --contact "Your Name your@email.com"')
sys.exit(1)
