"""Scoring the ledger. The arithmetic is simple and every one of these is a trap.

The traps, in order: buying a price you could not have bought (the signal day's
own open or close), counting an unfinished trade as flat, and comparing a trade
against a benchmark held for a different length of time.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocksignal.backtest import forward_return
from stocksignal.outcomes import (
    CLOSE,
    OPEN,
    RULEBOOK,
    Scored,
    entry_index,
    entry_position,
    fill_basis,
    score_signal,
    span_return,
    summarise,
    validation_exit,
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


class TestTheValidationProxy:
    def _falling(self):
        # Rises for 20 bars so the 9 SMA is well below price, then gaps down so
        # one bar OPENS below the line.
        opens = [100.0 + i for i in range(20)] + [80.0, 81.0, 82.0]
        closes = list(opens)
        return bars(opens, closes)

    def test_sells_at_the_open_after_the_first_open_below_the_fast_sma(self):
        frame = self._falling()
        held = validation_exit(frame, entry_pos=10)
        # The gap-down bar is position 20; the fill is position 21's open, 81.
        assert held == 21 - 10
        pct = span_return(frame, 10, 10 + held, OPEN, OPEN, 0.2)
        assert pct == pytest.approx((81.0 / 110.0 - 1.0) * 100.0 - 0.2)

    def test_a_dip_that_does_not_open_below_the_line_is_not_an_exit(self):
        opens = [100.0 + i for i in range(30)]
        closes = list(opens)
        closes[20] = 50.0  # a deep wick and a red close, but the OPEN held
        frame = bars(opens, closes)
        held = validation_exit(frame, entry_pos=10)
        # It does eventually exit, because that close drags the SMA, but not on
        # bar 20 itself: p111 says the candle has to OPEN below to count.
        assert held is None or held != 20 - 10

    def test_still_open_at_the_end_of_the_data_returns_none(self):
        frame = bars([100.0 + i for i in range(30)])
        assert validation_exit(frame, entry_pos=25) is None


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


# --------------------------------------------------------------------------
# The fill: a price that existed when the signal did
# --------------------------------------------------------------------------


class TestWhichPriceYouCouldActuallyHavePaid:
    """The scan ran before the bell until 28 August 2026 and after it since."""

    def test_published_before_the_bell_fills_at_the_open(self):
        assert fill_basis("2026-09-18T11:59:00", date(2026, 9, 18)) == OPEN

    def test_published_after_the_bell_fills_at_the_close(self):
        # 15:58 UTC is 11:58 in New York. The open has been and gone.
        assert fill_basis("2026-09-18T15:58:15", date(2026, 9, 18)) == CLOSE

    def test_published_the_evening_before_fills_at_the_open(self):
        assert fill_basis("2026-09-17T22:10:00", date(2026, 9, 18)) == OPEN

    def test_a_reconstructed_row_with_no_clock_fills_at_the_open(self):
        assert fill_basis(None, date(2026, 8, 14)) == OPEN

    def test_an_afternoon_signal_is_scored_from_the_close_it_could_have_bought(self):
        opens = [100.0] * 10
        closes = [90.0] * 10
        closes[7] = 99.0
        frame = bars(opens, closes)
        late = score_signal("T", frame.index[1].date(), frame, {}, logged_at="2026-01-07T16:00:00")
        early = score_signal("T", frame.index[1].date(), frame, {}, logged_at="2026-01-07T11:00:00")
        # Entry is bar 2. Late pays that bar's close of 90, early pays its open
        # of 100, and both sell the same close of 99 five sessions later.
        assert late.basis == CLOSE
        assert late.returns[5] == pytest.approx((99.0 / 90.0 - 1.0) * 100.0 - 0.2)
        assert early.returns[5] == pytest.approx((99.0 / 100.0 - 1.0) * 100.0 - 0.2)


class TestTheBenchmarkIsPricedLikeTheTrade:
    def test_the_validation_exit_benchmark_is_open_to_open_too(self):
        opens = [100.0 + i for i in range(20)] + [80.0, 81.0, 82.0]
        frame = bars(opens)
        # SPY opens and closes differ, so pricing the benchmark to a close
        # instead of an open would show up here.
        spy = bars([200.0 + i for i in range(len(opens))], [300.0] * len(opens))
        scored = score_signal("T", frame.index[9].date(), frame, {"SPY": spy})
        held = scored.held
        expected = ((200.0 + 10 + held) / (200.0 + 10) - 1.0) * 100.0
        assert scored.benchmarks["SPY"][RULEBOOK] == pytest.approx(expected)


class TestTheConventionStillMatchesTheBacktest:
    def test_an_open_filled_horizon_equals_backtest_forward_return(self):
        opens = [100.0 + (i % 5) for i in range(30)]
        closes = [101.0 + (i % 7) for i in range(30)]
        frame = bars(opens, closes)
        for pos in (3, 10, 20):
            assert span_return(frame, pos, pos + 5, OPEN, CLOSE, 0.2) == pytest.approx(
                forward_return(frame, pos, 5, 0.2)
            )


class TestAScanThatLandsADayLate:
    """A delayed schedule, a rerun, a Friday signal scanned on Tuesday."""

    def test_entry_moves_to_the_session_the_reader_could_reach(self):
        frame = bars([100.0 + i for i in range(10)])
        signal_day = frame.index[1].date()
        # Published on the day of bar 4, so bars 2 and 3 had already closed.
        late = frame.index[4].date().isoformat() + "T15:00:00"
        assert entry_position(frame, signal_day, late) == 4
        assert entry_position(frame, signal_day, None) == 2

    def test_a_late_scan_before_the_bell_still_fills_at_that_open(self):
        frame = bars([100.0 + i for i in range(10)])
        signal_day = frame.index[1].date()
        stamp = frame.index[4].date().isoformat() + "T11:00:00"
        scored = score_signal("T", signal_day, frame, {}, logged_at=stamp)
        assert scored.entry_date == frame.index[4].date()
        assert scored.basis == OPEN

    def test_a_stamp_past_the_end_of_the_data_is_not_scored(self):
        frame = bars([100.0] * 5)
        assert entry_position(frame, frame.index[0].date(), "2099-01-01T09:00:00") is None


class TestClocksThatAreNotNaiveUtc:
    def test_a_tz_aware_stamp_is_converted_rather_than_read_off_the_wall(self):
        # 16:00+05:00 is 11:00 UTC, which is before the bell.
        assert fill_basis("2026-09-18T16:00:00+05:00", date(2026, 9, 18)) == OPEN
        # 09:00-05:00 is 14:00 UTC, which is after it.
        assert fill_basis("2026-09-18T09:00:00-05:00", date(2026, 9, 18)) == CLOSE

    def test_an_unparseable_stamp_falls_back_to_the_open_like_a_missing_one(self):
        assert fill_basis("not a date", date(2026, 9, 18)) == OPEN


class TestTheBenchmarkFollowsTheFillBasis:
    def test_a_close_filled_trade_gets_a_close_filled_benchmark(self):
        frame = bars([100.0] * 10, [50.0] * 10)
        spy = bars([200.0] * 10, [400.0] * 10)
        stamp = frame.index[2].date().isoformat() + "T16:00:00"
        scored = score_signal("T", frame.index[1].date(), frame, {"SPY": spy}, logged_at=stamp)
        assert scored.basis == CLOSE
        # Both legs run close to close, so both are flat rather than the +100%
        # an open-to-close benchmark would have invented for SPY.
        assert scored.benchmarks["SPY"][5] == pytest.approx(0.0)
        assert scored.returns[5] == pytest.approx(-0.2)
