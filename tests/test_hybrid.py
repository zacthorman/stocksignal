"""HybridSource: bars from one provider, float from another, float cached hard.

The behaviour that matters is that the float lookup happens once a month rather
than once a scan, and that a fundamentals provider having a bad day costs you the
float rather than the whole run.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from stocksignal.sources import HybridSource


def frame(n: int = 5) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-08-07", periods=n)
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1e6] * n,
        },
        index=idx,
    )


class Bars:
    """A bars provider that cannot batch."""

    def __init__(self):
        self.history_calls = 0

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        self.history_calls += 1
        return frame()

    def shares_float(self, ticker: str) -> float | None:
        return None


class BatchBars(Bars):
    """A bars provider that can."""

    def histories(self, tickers: list[str], days: int = 250) -> dict[str, pd.DataFrame]:
        return {t.upper(): frame() for t in tickers}


class Fundamentals:
    def __init__(self, value: float | None = 50_000_000.0, explode: bool = False):
        self.value = value
        self.explode = explode
        self.calls = 0

    def history(self, ticker: str, days: int = 250) -> pd.DataFrame:
        raise AssertionError("bars must never come from the fundamentals provider")

    def shares_float(self, ticker: str) -> float | None:
        self.calls += 1
        if self.explode:
            raise RuntimeError("provider had a moment")
        return self.value


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "floats.json"


class TestDelegation:
    def test_bars_come_from_the_bars_provider(self, cache):
        bars = Bars()
        source = HybridSource(bars, Fundamentals(), cache_path=cache)
        assert len(source.history("AAPL")) == 5
        assert bars.history_calls == 1

    def test_batching_is_advertised_only_when_the_inner_source_can_batch(self, cache):
        # The scanner decides whether to prefetch with hasattr, so claiming
        # `histories` for a provider that cannot batch would break the scan.
        assert not hasattr(HybridSource(Bars(), cache_path=cache), "histories")
        assert hasattr(HybridSource(BatchBars(), cache_path=cache), "histories")

    def test_the_batch_call_passes_through(self, cache):
        source = HybridSource(BatchBars(), cache_path=cache)
        assert set(source.histories(["AAPL", "MSFT"])) == {"AAPL", "MSFT"}


class TestFloat:
    def test_float_comes_from_the_fundamentals_provider(self, cache):
        source = HybridSource(Bars(), Fundamentals(1_234.0), cache_path=cache)
        assert source.shares_float("AAPL") == 1_234.0

    def test_no_fundamentals_provider_means_unknown_not_an_error(self, cache):
        assert HybridSource(Bars(), None, cache_path=cache).shares_float("AAPL") is None

    def test_a_second_lookup_is_served_from_cache(self, cache):
        fundamentals = Fundamentals()
        source = HybridSource(Bars(), fundamentals, cache_path=cache)
        source.shares_float("AAPL")
        source.shares_float("AAPL")
        assert fundamentals.calls == 1, "float must not be refetched within the window"

    def test_the_cache_survives_a_new_instance(self, cache):
        first = Fundamentals(999.0)
        HybridSource(Bars(), first, cache_path=cache).shares_float("AAPL")
        second = Fundamentals(111.0)
        assert HybridSource(Bars(), second, cache_path=cache).shares_float("AAPL") == 999.0
        assert second.calls == 0

    def test_an_expired_entry_is_refetched(self, cache):
        clock = [1_000_000.0]
        fundamentals = Fundamentals(1.0)
        source = HybridSource(
            Bars(), fundamentals, cache_path=cache, cache_days=30, clock=lambda: clock[0]
        )
        source.shares_float("AAPL")
        clock[0] += 31 * 86_400
        source.shares_float("AAPL")
        assert fundamentals.calls == 2

    def test_a_cached_none_is_an_answer_and_is_not_retried(self, cache):
        # Plenty of symbols have no float on any given provider. Retrying a
        # known miss every scan spends a rate limit to learn nothing.
        fundamentals = Fundamentals(None)
        source = HybridSource(Bars(), fundamentals, cache_path=cache)
        assert source.shares_float("NOPE") is None
        assert source.shares_float("NOPE") is None
        assert fundamentals.calls == 1

    def test_a_failing_provider_does_not_break_the_scan(self, cache):
        source = HybridSource(Bars(), Fundamentals(explode=True), cache_path=cache)
        assert source.shares_float("AAPL") is None

    def test_a_failing_provider_falls_back_to_a_stale_value(self, cache):
        clock = [1_000_000.0]
        good = Fundamentals(42.0)
        HybridSource(Bars(), good, cache_path=cache, clock=lambda: clock[0]).shares_float("AAPL")
        clock[0] += 90 * 86_400
        broken = HybridSource(
            Bars(), Fundamentals(explode=True), cache_path=cache, clock=lambda: clock[0]
        )
        assert broken.shares_float("AAPL") == 42.0, "stale beats nothing when the provider is down"

    def test_tickers_are_cached_case_insensitively(self, cache):
        fundamentals = Fundamentals()
        source = HybridSource(Bars(), fundamentals, cache_path=cache)
        source.shares_float("aapl")
        source.shares_float("AAPL")
        assert fundamentals.calls == 1

    def test_an_unreadable_cache_file_is_survivable(self, cache):
        cache.write_text("{ this is not json")
        source = HybridSource(Bars(), Fundamentals(7.0), cache_path=cache)
        assert source.shares_float("AAPL") == 7.0

    def test_the_cache_is_written_in_a_readable_shape(self, cache):
        HybridSource(Bars(), Fundamentals(5.0), cache_path=cache).shares_float("AAPL")
        written = json.loads(cache.read_text())
        assert written["AAPL"]["value"] == 5.0
        assert "at" in written["AAPL"]
