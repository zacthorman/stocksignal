"""Delivery tests. None of them touch the network.

The interesting cases here are all failure cases, because delivery is the part
of the system that runs unattended and therefore the part where a silent failure
costs the most.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from stocksignal import notify
from stocksignal.digest import publication_line
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


class TestThePhoneMessageExplainsWhyAName:
    """The gate is not the reason. Fixed 2026-08-14.

    Every candidate clears the tradability gate by definition, so its reasons
    are identical across the whole shortlist. The first version of the phone
    digest took `reasons[:2]`, which is gate-first, so eight different names
    arrived on the phone carrying the same two lines about the price floor and
    the volume floor. The message was well formed and completely uninformative.
    """

    def _two_screen_signal(self, ticker: str = "AEHR"):
        gate = ScreenResult(
            name="tradability",
            passed=True,
            score=1.0,
            reasons=(
                "price 123.30 clears the 15.00 swing floor",
                "avg volume 2,805,720 clears the 100,000 floor",
            ),
        )
        trend = ScreenResult(
            name="trend",
            passed=True,
            score=1.4,
            reasons=(
                "close 123.30 is above both averages (118.02 / 96.41)",
                "SMA gap 22.41% scored against the fixed 67.9% ceiling",
            ),
        )
        return Signal(
            ticker=ticker,
            as_of=date(2026, 8, 11),
            close=123.30,
            score=1.5,
            results=(gate, trend),
        )

    def test_the_message_shows_the_scoring_screen_not_the_hard_gate(self):
        text = notify.render_telegram(report([self._two_screen_signal()]))
        assert "above both averages" in text
        assert "swing floor" not in text
        assert "clears the 100,000 floor" not in text

    def test_two_candidates_do_not_read_identically(self):
        # The actual symptom: the whole shortlist justified by one liquidity
        # filter, so nothing distinguished the first name from the eighth.
        a = self._two_screen_signal("AEHR")
        b = Signal(
            ticker="TWST",
            as_of=date(2026, 8, 11),
            close=125.29,
            score=1.5,
            results=(
                a.results[0],
                ScreenResult(
                    name="breakout",
                    passed=True,
                    score=1.4,
                    reasons=("broke a 3-touch resistance at 121.40 on 2.8x volume",),
                ),
            ),
        )
        text = notify.render_telegram(report([a, b]))
        assert "above both averages" in text
        assert "broke a 3-touch resistance" in text

    def test_it_falls_back_to_the_gate_when_nothing_else_passed(self):
        # Defensive: a signal with only a gate result should still say
        # something rather than render a bare ticker with no reasoning.
        gate_only = Signal(
            ticker="ONLY",
            as_of=date(2026, 8, 11),
            close=50.0,
            score=0.1,
            results=(
                ScreenResult(
                    name="tradability", passed=True, score=1.0, reasons=("price clears the floor",)
                ),
            ),
        )
        text = notify.render_telegram(report([gate_only]))
        assert "price clears the floor" in text


# --------------------------------------------------------------------------
# With memory: new names get cards, continuing names get one line
# --------------------------------------------------------------------------


def _memory(new_names, runs, dismissed=()):
    from stocksignal.memory import Dismissal, Recurrence, ScanMemory

    today = date(2026, 1, 2)
    recs = {t: Recurrence(t, 1, today) for t in new_names}
    recs.update({t: Recurrence(t, n, date(2025, 12, 1)) for t, n in runs.items()})
    dis = {t: Dismissal(t, today, "no setup") for t in dismissed}
    return ScanMemory(recurrences=recs, dismissals=dis, as_of=today)


class TestTelegramWithMemory:
    def test_new_names_get_cards_and_old_ones_get_a_line(self):
        rep = report([signal("DELL", 1.5), signal("CHYM", 1.1), signal("SMTC", 0.9)])
        text = notify.render_telegram(rep, memory=_memory(["CHYM"], {"DELL": 12, "SMTC": 8}))
        assert "New today (1)" in text
        assert "<b>1. CHYM</b>" in text
        assert "<b>1. DELL</b>" not in text and "2. DELL" not in text
        assert "Still passing (2)" in text
        assert "DELL ×12, SMTC ×8" in text

    def test_a_day_with_nothing_new_says_so(self):
        rep = report([signal("DELL")])
        text = notify.render_telegram(rep, memory=_memory([], {"DELL": 3}))
        assert "Nothing new today" in text
        assert "DELL ×3" in text

    def test_dismissed_names_are_counted_not_carded(self):
        rep = report([signal("TXG"), signal("CHYM")])
        text = notify.render_telegram(rep, memory=_memory(["CHYM", "TXG"], {}, dismissed=["TXG"]))
        assert "TXG" not in text
        assert "1 dismissed by you" in text

    def test_the_new_list_is_still_capped(self):
        names = [f"T{i}" for i in range(12)]
        rep = report([signal(t) for t in names])
        text = notify.render_telegram(rep, limit=5, memory=_memory(names, {}))
        assert "and 7 more new" in text

    def test_deliver_passes_memory_through(self):
        sent = {}
        rep = report([signal("DELL")])
        notify.deliver(
            rep,
            token="t",
            chat_id="c",
            transport=lambda url, payload: sent.update(payload),
            memory=_memory([], {"DELL": 4}),
        )
        assert "DELL ×4" in sent["text"]


# --------------------------------------------------------------------------
# The message says when it was sent, because the scheduler stopped being early
# --------------------------------------------------------------------------


class TestPublicationTime:
    """Four weeks of digests arrived after the open without saying so."""

    def test_before_the_bell_promises_the_open(self):
        line = publication_line(datetime(2026, 9, 18, 11, 17, tzinfo=UTC))
        assert "before the New York open" in line and "today's open" in line

    def test_after_the_bell_says_the_open_has_gone(self):
        line = publication_line(datetime(2026, 9, 18, 15, 58, tzinfo=UTC))
        assert "after the New York open" in line and "today's close" in line

    def test_the_boundary_is_the_bell_itself(self):
        assert "before" in publication_line(datetime(2026, 9, 18, 13, 29, tzinfo=UTC))
        assert "after" in publication_line(datetime(2026, 9, 18, 13, 30, tzinfo=UTC))

    def test_the_phone_message_carries_it(self):
        text = notify.render_telegram(report([signal("NVDA")]))
        assert "New York open" in text
