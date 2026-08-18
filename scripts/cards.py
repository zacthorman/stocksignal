"""Build opportunity cards for the tickers that passed, and push them to the phone.

Run this AFTER a scan. The scan says which names are worth looking at; this says
what the case for each one actually is.

    # See the shape, no network, no keys.
    PYTHONPATH=src python scripts/cards.py --offline --tickers AAPL,MSFT

    # Real bars, on the names that passed today's scan.
    PYTHONPATH=src python scripts/cards.py --live --watchlist data/watchlist.txt

    # Same, delivered to Telegram.
    PYTHONPATH=src python scripts/cards.py --live --watchlist data/watchlist.txt --telegram

WHY THIS IS A SCRIPT AND NOT A CLI SUBCOMMAND. `cli.py` is the tested entry
point that the daily scheduled run depends on, and a card is a different unit of
work from a scan: it is slower, it needs research input the scan does not, and
it is worth running on a handful of names rather than 256. Keeping it out here
means a mistake in card rendering cannot take down the scan that feeds it. Fold
it into `cli.py` once the format has stopped changing.

THE DIRECTION FILE IS THE POINT OF THE WHOLE THING. `data/directions.json` holds
the growth-direction calls, which are the one input that cannot be computed and
the one page 233 calls "the most important step in this process". Without an
entry for a ticker, its card prints with no price target and says why. That is
the design working, not a failure: a target placed on chart geometry alone would
look exactly like a researched one and mean nothing.

    {
      "NVDA": {
        "call": "positive",
        "basis": [
          "Q2 revenue +122% YoY, data centre segment +154%",
          "guidance range entirely above consensus",
          "investor presentation: three new product lines named for FY26"
        ],
        "researched_on": "2026-08-11",
        "source": "IR quarterly + 6 analyst write-ups"
      }
    }

Calls go stale. Page 232: "Price targets always need to be subjected to change
so don't be afraid to change them if you are wrong." Anything older than
`--stale-days` is reported as stale on the card and stops placing a target.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocksignal.card_render import (  # noqa: E402
    render_card_markdown,
    render_cards_telegram,
)
from stocksignal.config import DEFAULT_CONFIG, OUT_DIR  # noqa: E402
from stocksignal.data import DataError, get_source  # noqa: E402
from stocksignal.opportunity import (  # noqa: E402
    CardConfig,
    GrowthDirection,
    OpportunityCard,
    build_card,
)

DIRECTIONS = ROOT / "data" / "directions.json"
DEFAULT_STALE_DAYS = 90
"""A quarter. The direction call is read off the last quarterly report (pages
220 to 222), so it has a natural shelf life of exactly one reporting cycle."""

HISTORY_DAYS = 420
"""Deliberately more than the 250 the sources default to, and the number is
forced by two separate requirements that both bite silently.

The slow SMA is 180 periods, so a 250-bar frame leaves only 70 bars where it is
not NaN, and every level and swing computed before that point is being judged
against a moving average that does not exist yet. Separately, the median anchor
asks for a full year (252 sessions) and quietly shortens itself when handed
less, which turns "the median price for the last year" into "the median price
for however much I was given" with only a line in the basis to say so.

420 business days is about twenty months: a full year for the anchor, with 180
sessions of warm-up in front of it."""


def load_directions(path: Path, stale_days: int) -> dict[str, GrowthDirection]:
    """Read the research file, ageing out anything past its reporting cycle.

    A stale call is downgraded to UNKNOWN rather than deleted, and the reason
    travels with it. Silently keeping a six-month-old POSITIVE would be the
    worst of the available options: the card would look fully researched and be
    quoting a thesis two earnings reports out of date.
    """
    if not path.exists():
        return {}

    raw = json.loads(path.read_text())
    cutoff = date.today() - timedelta(days=stale_days)
    out: dict[str, GrowthDirection] = {}

    for ticker, entry in raw.items():
        stamp = entry.get("researched_on")
        researched = date.fromisoformat(stamp) if stamp else None
        basis = tuple(entry.get("basis", ()))
        source = entry.get("source", "")

        if researched is not None and researched < cutoff:
            out[ticker.upper()] = GrowthDirection(
                basis=basis
                + (
                    f"call was {entry.get('call', 'unknown')} on {researched}, now stale "
                    f"(older than {stale_days} days), so no target is placed",
                ),
                researched_on=researched,
                source=source,
            )
            continue

        out[ticker.upper()] = GrowthDirection(
            call=entry.get("call", "unknown"),
            basis=basis,
            researched_on=researched,
            source=source,
        )
    return out


def rank(cards: list[OpportunityCard]) -> list[OpportunityCard]:
    """Best first, and "best" needs defining because the obvious answer is wrong.

    Sorting by upside alone would put every unresearched name with a wild
    momentum projection above a researched one with a modest, defensible target.
    So the order is: cards with a target first, then by reward-to-risk, then by
    upside. Reward-to-risk leads because page 133 makes it step 2, ahead of the
    factors, and page 23 treats a poor ratio as disqualifying rather than as a
    low score.

    Cards carrying a big deprecating factor are pushed below those without one,
    whatever their numbers. Page 131 will not let them be netted off, but it is
    explicit that they count.
    """

    def key(card: OpportunityCard) -> tuple:
        return (
            card.has_target,
            not card.big_deprecating,
            card.reward_risk if card.reward_risk is not None else -1.0,
            card.upside_pct if card.upside_pct is not None else -1.0,
        )

    return sorted(cards, key=key, reverse=True)


def read_watchlist(path: Path) -> list[str]:
    """One ticker a line, `#` starts a comment, inline comments allowed."""
    out = []
    for line in path.read_text().splitlines():
        symbol = line.split("#", 1)[0].strip().upper()
        if symbol:
            out.append(symbol)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma separated, overrides --watchlist.")
    parser.add_argument("--watchlist", type=Path)
    parser.add_argument("--live", action="store_true", help="Real bars via the live source.")
    parser.add_argument("--offline", action="store_true", help="Synthetic bars, no network.")
    parser.add_argument("--telegram", action="store_true", help="Deliver the top cards.")
    parser.add_argument("--account", type=float, default=None, help="Account size, for sizing.")
    parser.add_argument("--limit", type=int, default=3, help="Cards per Telegram message.")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--directions", type=Path, default=DIRECTIONS)
    args = parser.parse_args()

    if args.tickers:
        symbols = [s.strip().upper() for s in args.tickers.split(",") if s.strip()]
    elif args.watchlist:
        symbols = read_watchlist(args.watchlist)
    else:
        symbols = list(DEFAULT_CONFIG.default_watchlist)

    provider = "yfinance" if args.live else "synthetic"
    try:
        source = get_source(provider=provider)
    except DataError as exc:
        print(f"data source unavailable: {exc}", file=sys.stderr)
        return 1

    directions = load_directions(args.directions, args.stale_days)
    if not directions:
        print(
            f"no research file at {args.directions}. Every card will print without a "
            "price target, which is the intended behaviour, not a bug.",
            file=sys.stderr,
        )

    card_cfg = CardConfig(account_size=args.account)
    cards: list[OpportunityCard] = []
    errors: list[tuple[str, str]] = []

    for symbol in symbols:
        try:
            df = source.history(symbol, days=HISTORY_DAYS)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not end the run
            errors.append((symbol, exc.__class__.__name__))
            continue
        if df is None or df.empty:
            errors.append((symbol, "no bars"))
            continue
        cards.append(
            build_card(
                symbol,
                df,
                DEFAULT_CONFIG,
                card_cfg,
                directions.get(symbol, GrowthDirection()),
            )
        )

    ordered = rank(cards)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = ordered[0].as_of.isoformat() if ordered else date.today().isoformat()
    out = OUT_DIR / f"cards-{stamp}.md"
    body = "\n\n---\n\n".join(render_card_markdown(card) for card in ordered)
    if errors:
        body += "\n\n## Errors\n\n" + "\n".join(f"- {t}: {why}" for t, why in errors)
    out.write_text(body)
    print(f"written {out} ({len(ordered)} card(s), {len(errors)} error(s))")

    researched = sum(1 for c in ordered if c.has_target)
    print(f"{researched} of {len(ordered)} have a researched growth direction")

    if args.telegram:
        import os

        from stocksignal.notify import _post  # noqa: PLC0415

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping", file=sys.stderr)
            return 0
        payload = {
            "chat_id": chat_id,
            "text": render_cards_telegram(ordered, limit=args.limit),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            _post(f"https://api.telegram.org/bot{token}/sendMessage", payload)
            print(f"delivered top {min(args.limit, len(ordered))} card(s)")
        except Exception as exc:  # noqa: BLE001 - delivery must never fail the run
            print(f"delivery failed: {exc.__class__.__name__}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
