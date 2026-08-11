"""Delivery. Getting the digest off the machine and onto your phone.

WHY THIS SENDS SOMETHING EVEN WHEN NOTHING PASSED, which is the first design
question and the one most likely to be got wrong. A scan that finds no
candidates and stays silent is indistinguishable from a scan that crashed, a
runner that never started, a rate limit, an expired token, or a cron expression
that stopped matching when the clocks changed. All six look identical from the
outside: no message. So a quiet day gets a short message saying it was quiet.
The cost is one line on your phone. The benefit is that silence becomes
unambiguous evidence that something is broken, which is the only way an
automated job earns any trust.

The same reasoning drives the error line. A provider hiccup does not fail the
run and does not suppress the message; it is reported inside it. A job that goes
red every time a free API rate limits you is a job you learn to ignore, and an
ignored alert is worse than no alert because it is a false sense of coverage.

CREDENTIALS COME FROM THE ENVIRONMENT AND ARE NEVER LOGGED. The bot token is
read from `TELEGRAM_BOT_TOKEN` and the destination from `TELEGRAM_CHAT_ID`. If
either is missing, delivery is SKIPPED rather than failed, so the same command
works unchanged on a laptop with no secrets configured. Note the precedence:
`token if token is not None else os.environ.get(...)`, not `token or ...`. An
empty string is a configured-but-blank value and must not silently fall through
to the environment. That exact bug cost an evening earlier in this project.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from stocksignal.scanner import ScanReport

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram rejects anything longer, with an unhelpful error. Truncating here
# beats discovering the limit on the one day the scan finds forty candidates.
MESSAGE_LIMIT = 4096
REASONS_PER_SIGNAL = 2
DEFAULT_LIMIT = 8
TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Delivery:
    """What happened when we tried to send. Never raises at the caller."""

    sent: bool
    reason: str

    def __str__(self) -> str:
        return f"{'sent' if self.sent else 'not sent'}: {self.reason}"


def escape(text: str) -> str:
    """Telegram's HTML parse mode only cares about these three."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_telegram(report: ScanReport, limit: int = DEFAULT_LIMIT) -> str:
    """A phone-sized digest: the headline, the top few names, and the caveat.

    Deliberately not the markdown digest. That one is written to be read on a
    screen with the rejections and every reason attached; this one is read
    standing up, and its job is to answer "is there anything worth opening the
    laptop for" rather than to explain itself fully.
    """
    header = (
        f"<b>stocksignal</b> · {report.as_of.isoformat()}\n"
        f"scanned {report.scanned} · passed {len(report.signals)} · "
        f"rejected {len(report.rejected)} · errors {len(report.errors)}"
    )

    if not report.signals:
        body = "\nNothing passed today."
    else:
        chunks = []
        for i, signal in enumerate(report.signals[:limit], start=1):
            lines = [
                f"\n<b>{i}. {escape(signal.ticker)}</b> "
                f"{signal.close:,.2f} · score {signal.score:.2f}"
            ]
            lines += [f"  · {escape(r)}" for r in signal.reasons[:REASONS_PER_SIGNAL]]
            chunks.append("\n".join(lines))
        body = "\n".join(chunks)
        if len(report.signals) > limit:
            body += f"\n\n<i>and {len(report.signals) - limit} more, see the digest.</i>"

    footer = "\n\n<i>Candidates only. Every entry and exit is your decision.</i>"
    if report.errors:
        # Named, not just counted. "3 errors" tells you nothing actionable;
        # "AAPL: rate limited" tells you whether to care.
        shown = ", ".join(f"{escape(t)}: {escape(why)}" for t, why in report.errors[:3])
        footer = f"\n\n<i>Errors — {shown}</i>" + footer

    message = header + body + footer
    if len(message) > MESSAGE_LIMIT:
        keep = MESSAGE_LIMIT - len(footer) - 20
        message = message[:keep].rstrip() + "\n<i>… truncated.</i>" + footer
    return message


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        response.read()


def deliver(
    report: ScanReport,
    token: str | None = None,
    chat_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    transport: Callable[[str, dict], None] = _post,
) -> Delivery:
    """Send the digest to Telegram. Reports failure, never raises.

    A delivery failure must not take down a scan that already succeeded: the
    numbers are the product, and the message is a convenience on top of them.
    The digest is still written to disk and still logged whatever happens here.

    `transport` exists so the tests never touch the network. That is not
    ceremony — a test suite that makes real HTTP calls is a test suite that
    fails on a train.
    """
    token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        missing = "TELEGRAM_BOT_TOKEN" if not token else "TELEGRAM_CHAT_ID"
        return Delivery(False, f"{missing} not set, skipping")

    payload = {
        "chat_id": chat_id,
        "text": render_telegram(report, limit=limit),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        transport(API.format(token=token), payload)
    except urllib.error.HTTPError as exc:
        # The token is in the URL, so the URL never goes near a log line.
        return Delivery(False, f"telegram rejected it: HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Delivery(False, f"could not reach telegram: {exc.__class__.__name__}")
    return Delivery(True, f"{len(report.signals)} signal(s) delivered")
