"""Scoring the ledger. The arithmetic is simple and every one of these is a trap.

The traps, in order: buying a price you could not have bought (the signal day's
own open or close), counting an unfinished trade as flat, and comparing a trade
against a benchmark held for a different length of time.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocksignal.outcomes import (
    RULEBOOK,
    Scored,
    entry_index,
    rulebook_exit_return,
    score_signal,
    summarise,
)


def bars(opens: list[float], closes: list[float] | None = None, start="2026-01-05") -> pd.DataFrame:
    closes = closes if closes is not None else list(opens)
    index = pd.bdate_range(start, periods=len(opens))
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "volume": [1_000_000.0] * len(opens),
        },
        index=index,
    )


class TestEntryIsAPriceYouCouldHaveBought:
    def test_entry_is_the_next_session_not_the_signal_day(self):
        frame = bars([100.0] * 5)
        # Signal is dated the second bar. The scan read that day's CLOSE, so the
        # earliest fill is the third bar's open.
        assert entry_index(frame, frame.index[1].date()) == 2

    def test_a_signal_on_the_last_bar_has_no_entry_yet(self):
        frame = bars([100.0] * 3)
        assert entry_index(frame, frame.index[-1].date()) is None

    def test_a_signal_dated_before_the_data_starts_enters_on_the_first_bar(self):
        frame = bars([100.0] * 3)
        assert entry_index(frame, date(2020, 1, 1)) == 0


class TestHorizons:
    def test_return_is_entry_open_to_the_close_that_many_sessions_later(self):
        opens = [100.0] * 10
        closes = [100.0] * 10
        closes[7] = 110.0  # five sessions after the entry at position 2
        scored = score_signal("T", bars(opens, closes).index[1].date(), bars(opens, closes), {})
        assert scored is not None
        assert scored.returns[5] == pytest.approx(10.0 - 0.2)

    def test_an_unfinished_horizon_is_absent_rather_than_zero(self):
        frame = bars([100.0] * 10)
        scored = score_signal("T", frame.index[1].date(), frame, {})
        assert scored is not None
        assert 5 in scored.returns
        assert 20 not in scored.returns
        assert 60 not in scored.returns

    def test_costs_are_deducted_once(self):
        opens = [100.0] * 10
        closes = [100.0] * 10
        scored = score_signal("T", bars(opens, closes).index[1].date(), bars(opens, closes), {})
        assert scored.returns[5] == pytest.approx(-0.2)


class TestTheRulebookExit:
    def _falling(self):
        # Rises for 20 bars so the 9 SMA is well below price, then gaps down so
        # one bar OPENS below the line.
        opens = [100.0 + i for i in range(20)] + [80.0, 81.0, 82.0]
        closes = list(opens)
        return bars(opens, closes)

    def test_sells_at_the_open_after_the_first_open_below_the_fast_sma(self):
        frame = self._falling()
        out = rulebook_exit_return(frame, entry_pos=10)
        assert out is not None
        pct, held = out
        # The gap-down bar is position 20; the fill is position 21's open, 81.
        assert held == 21 - 10
        assert pct == pytest.approx((81.0 / 110.0 - 1.0) * 100.0 - 0.2)

    def test_a_dip_that_does_not_open_below_the_line_is_not_an_exit(self):
        opens = [100.0 + i for i in range(30)]
        closes = list(opens)
        closes[20] = 50.0  # a deep wick and a red close, but the OPEN held
        frame = bars(opens, closes)
        out = rulebook_exit_return(frame, entry_pos=10)
        # It does eventually exit, because that close drags the SMA, but not on
        # bar 20 itself: p111 says the candle has to OPEN below to count.
        assert out is None or out[1] != 20 - 10

    def test_still_open_at_the_end_of_the_data_returns_none(self):
        frame = bars([100.0 + i for i in range(30)])
        assert rulebook_exit_return(frame, entry_pos=25) is None


class TestTheBenchmarkIsHeldForTheSameSessions:
    def test_benchmark_uses_the_same_hold_length_as_the_rulebook_exit(self):
        opens = [100.0 + i for i in range(20)] + [80.0, 81.0, 82.0]
        frame = bars(opens)
        spy = bars([200.0 + i for i in range(len(opens))])
        scored = score_signal("T", frame.index[9].date(), frame, {"SPY": spy})
        assert scored is not None
        assert RULEBOOK in scored.benchmarks["SPY"]
        # Eleven sessions held, so the benchmark is eleven sessions of SPY.
        held = scored.held
        entry = 200.0 + 10
        expected = ((200.0 + 10 + held) / entry - 1.0) * 100.0
        assert scored.benchmarks["SPY"][RULEBOOK] == pytest.approx(expected)

    def test_no_costs_are_deducted_from_the_benchmark_leg(self):
        frame = bars([100.0] * 10)
        spy = bars([100.0] * 10)
        scored = score_signal("T", frame.index[1].date(), frame, {"SPY": spy})
        assert scored.benchmarks["SPY"][5] == pytest.approx(0.0)
        assert scored.returns[5] == pytest.approx(-0.2)


def scored_row(ret: float, bench: float = 0.0) -> Scored:
    return Scored(
        ticker="T",
        as_of=date(2026, 1, 5),
        entry_date=date(2026, 1, 6),
        returns={20: ret},
        benchmarks={"SPY": {20: bench}},
    )


class TestSummaryRefusesToPrintOnlyTheMean:
    def test_trimmed_mean_drops_the_best_five_percent(self):
        rows = [scored_row(-1.0) for _ in range(19)] + [scored_row(100.0)]
        out = summarise(rows, 20, ("SPY",))
        assert out.mean == pytest.approx(4.05)
        assert out.median == pytest.approx(-1.0)
        assert out.trimmed == pytest.approx(-1.0)
        assert not out.survives_trimming

    def test_top_five_percent_share_names_the_concentration(self):
        rows = [scored_row(-1.0) for _ in range(19)] + [scored_row(100.0)]
        out = summarise(rows, 20, ("SPY",))
        # 100 of a total of 81, so the best trade is worth more than everything.
        assert out.top_5pct_share > 100

    def test_excess_is_reported_as_mean_and_median(self):
        rows = [scored_row(3.0, bench=1.0), scored_row(5.0, bench=1.0)]
        out = summarise(rows, 20, ("SPY",))
        assert out.excess_mean["SPY"] == pytest.approx(3.0)
        assert out.excess_median["SPY"] == pytest.approx(3.0)
        assert out.benchmark_mean["SPY"] == pytest.approx(1.0)

    def test_a_horizon_nothing_has_finished_at_returns_nothing(self):
        assert summarise([scored_row(1.0)], 60, ("SPY",)) is None
