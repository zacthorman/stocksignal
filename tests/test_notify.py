"""Delivery tests. None of them touch the network.

The interesting cases here are all failure cases, because delivery is the part
of the system that runs unattended and therefore the part where a silent failure
costs the most.
"""

from __future__ import annotations

from datetime import date

import pytest

from stocksignal import notify
from stocksignal.models import ScreenResult, Signal
from stocksignal.scanner import ScanReport


def signal(ticker: str, score: float = 0.5, reasons: tuple[str, ...] = ("trend is up",)):
    return Signal(
        ticker=ticker,
        as_of=date(2026, 8, 11),
        close=100.0,
        score=score,
        results=(ScreenResult(name="trend", passed=True, score=score, reasons=reasons),),
    )


def report(signals=(), rejected=(), errors=()):
    return ScanReport(
        as_of=date(2026, 8, 11),
        signals=tuple(signals),
        rejected=tuple(rejected),
        errors=tuple(errors),
    )


class TestASilentDayIsStillAMessage:
    """The design decision this module exists to defend."""

    def test_an_empty_scan_still_produces_a_message(self):
        # Silence is indistinguishable from a crashed runner, an expired token,
        # a rate limit, or a cron that stopped matching when the clocks changed.
        # A quiet day has to look different from a broken one.
        text = notify.render_telegram(report(rejected=[("AAPL", "no trend")]))
        assert "Nothing passed today" in text
        assert "2026-08-11" in text

    def test_errors_are_named_in_the_message_rather_than_failing_the_run(self):
        # A job that goes red whenever a free API hiccups is a job you learn to
        # ignore, and an ignored alert is worse than none.
        text = notify.render_telegram(report(errors=[("NVDA", "rate limited")]))
        assert "NVDA" in text and "rate limited" in text

    def test_the_message_says_it_is_candidates_only(self):
        assert "your decision" in notify.render_telegram(report([signal("NVDA")]))


class TestTheMessageItself:
    def test_signals_appear_ranked_with_their_reasons(self):
        text = notify.render_telegram(report([signal("NVDA", 0.8), signal("AMD", 0.4)]))
        assert "1. NVDA" in text and "2. AMD" in text
        assert "trend is up" in text

    def test_only_the_first_few_reasons_survive(self):
        many = tuple(f"reason {i}" for i in range(10))
        text = notify.render_telegram(report([signal("NVDA", reasons=many)]))
        assert "reason 0" in text
        assert "reason 9" not in text, "a phone message is not the full digest"

    def test_a_long_list_is_summarised_rather_than_dumped(self):
        text = notify.render_telegram(report([signal(f"T{i}") for i in range(20)]), limit=5)
        assert "and 15 more" in text

    def test_html_special_characters_are_escaped(self):
        # An unescaped < turns the whole message into a Telegram parse error,
        # which arrives as no message at all.
        text = notify.render_telegram(report([signal("A&B", reasons=("gap < 5%",))]))
        assert "A&amp;B" in text and "gap &lt; 5%" in text

    def test_a_huge_scan_is_truncated_below_the_api_limit(self):
        wordy = tuple([" ".join(["verbose"] * 60)] * 2)
        big = report([signal(f"TICK{i}", reasons=wordy) for i in range(200)])
        text = notify.render_telegram(big, limit=200)
        assert len(text) <= notify.MESSAGE_LIMIT
        assert "truncated" in text
        assert "your decision" in text, "the caveat must survive truncation"


class TestDelivery:
    def test_missing_credentials_skip_rather_than_fail(self):
        # The same command has to work on a laptop with no secrets configured.
        out = notify.deliver(report([signal("NVDA")]), token="", chat_id="")
        assert not out.sent
        assert "not set" in out.reason

    def test_an_empty_token_does_not_fall_through_to_the_environment(self, monkeypatch):
        # `token or os.environ.get(...)` treats "" as "go and look at the
        # environment", so a deliberately blank setting silently picks up
        # whatever is exported. That exact bug cost an evening on the Alpaca
        # source, so it is asserted here rather than trusted.
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-the-environment")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        sent: list[str] = []
        notify.deliver(
            report([signal("NVDA")]),
            token="",
            chat_id="123",
            transport=lambda url, payload: sent.append(url),
        )
        assert not sent, "an explicit empty token was overridden by the environment"

    def test_credentials_are_read_from_the_environment_when_not_passed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
        seen: dict = {}

        def transport(url, payload):
            seen["url"] = url
            seen["payload"] = payload

        out = notify.deliver(report([signal("NVDA")]), transport=transport)
        assert out.sent
        assert seen["payload"]["chat_id"] == "chat"
        assert seen["payload"]["parse_mode"] == "HTML"

    def test_a_network_failure_is_reported_not_raised(self):
        def transport(url, payload):
            raise TimeoutError("too slow")

        out = notify.deliver(report([signal("NVDA")]), token="t", chat_id="c", transport=transport)
        assert not out.sent
        assert "telegram" in out.reason.lower()

    def test_an_http_rejection_never_puts_the_token_in_the_reason(self):
        import urllib.error

        def transport(url, payload):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

        out = notify.deliver(
            report([signal("NVDA")]), token="SECRET-TOKEN", chat_id="c", transport=transport
        )
        assert not out.sent
        assert "401" in out.reason
        assert "SECRET-TOKEN" not in out.reason, "the token leaked into an error message"

    def test_a_delivery_failure_does_not_raise(self):
        def transport(url, payload):
            raise OSError("no route to host")

        # The scan already succeeded. Losing the message must not lose the run.
        assert not notify.deliver(
            report([signal("NVDA")]), token="t", chat_id="c", transport=transport
        ).sent


@pytest.mark.parametrize("count", [0, 1, 5])
def test_every_report_shape_renders_without_error(count):
    text = notify.render_telegram(report([signal(f"T{i}") for i in range(count)]))
    assert text and len(text) <= notify.MESSAGE_LIMIT
