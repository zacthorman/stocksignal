"""The backtest, and mostly the ways it could lie.

The build plan asks for a test that deliberately tries to leak future data and
asserts the backtest refuses it. `TestLookahead` is that test, and it is the most
important thing in this file: every other number the module produces is worthless
if a signal on Tuesday knew what happened on Friday.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import quote_from
from stocksignal import backtest as bt
from stocksignal.config import Config
from stocksignal.data import SyntheticSource
from stocksignal.screens import screen_trend


@pytest.fixture
def cfg() -> Config:
    return Config()


def synth(tickers: list[str], days: int = 700, seed: int = 23):
    source = SyntheticSource(seed=seed)
    frames = {t: source.history(t, days=days) for t in tickers}
    return frames, source.history("SPY", days=days)


def run_over(frames, bench, cfg, first: int = 400, last: int = -30, **kw):
    """Run the whole usable window of a synthetic fixture."""
    index = next(iter(frames.values())).index
    return bt.run(frames, bench, cfg, start=index[first].date(), end=index[last].date(), **kw)


class TestLookahead:
    """Can a signal see a bar dated after the day it fired?"""

    def test_future_bars_cannot_change_a_past_signal(self, cfg):
        # The headline test. Run once on history truncated at T, then again with
        # extra bars glued on, and demand the signals before T are identical.
        # Anything that peeked forward would produce different trades once the
        # future exists to be peeked at.
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        frames, bench = synth(tickers, days=700)

        cut = 600
        short = {t: df.iloc[:cut] for t, df in frames.items()}
        bench_short = bench.iloc[:cut]

        window = (frames["AAA"].index[400].date(), frames["AAA"].index[cut - 40].date())
        long_run = bt.run(frames, bench, cfg, start=window[0], end=window[1])
        short_run = bt.run(short, bench_short, cfg, start=window[0], end=window[1])

        def keys(report):
            return sorted(
                (t.arm, t.ticker, t.signal_date, round(t.entry_price, 6))
                for t in report.trades
                if t.arm == "screens"
            )

        assert keys(long_run) == keys(short_run), "a future bar changed a past signal"

    def test_tampering_with_the_future_does_not_move_earlier_returns(self, cfg):
        # Same idea, aimed at the return calculation rather than the signal.
        # Multiply the last fifty bars by ten. Trades that closed before that
        # stretch must be untouched.
        tickers = ["AAA", "BBB"]
        frames, bench = synth(tickers, days=700)
        window = (frames["AAA"].index[400].date(), frames["AAA"].index[600].date())
        clean = bt.run(frames, bench, cfg, start=window[0], end=window[1])

        tampered = {}
        for ticker, df in frames.items():
            copy = df.copy()
            copy.iloc[-50:] = copy.iloc[-50:] * 10.0
            tampered[ticker] = copy
        dirty = bt.run(tampered, bench, cfg, start=window[0], end=window[1])

        def by_key(report):
            return {
                (t.ticker, t.signal_date): t.returns
                for t in report.trades
                if t.arm == "screens" and t.signal_date < frames["AAA"].index[-70].date()
            }

        assert by_key(clean) == by_key(dirty), "future prices leaked into an earlier return"

    def test_the_module_never_reads_the_watchlist_file(self):
        # The watchlist was screened on beta as of today. A backtest that reads
        # it has picked 2020's stocks with 2026's knowledge.
        source = (bt.__file__,)
        text = open(source[0]).read()
        code = text.split('"""', 2)[-1]  # skip the module docstring, which discusses it
        assert "watchlist" not in code.lower()


class TestAgreesWithTheRealScreen:
    def test_the_vectorised_trend_matches_screen_trend(self, cfg):
        # The panel exists for speed. If it drifts away from the screen it stands
        # in for, the backtest measures something that never shipped.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, cfg)
        passes, _ = bt.trend_mask(panel, cfg)

        checked = 0
        for i, ticker in enumerate(panel.tickers):
            df = frames[ticker]
            for t in range(300, len(panel.dates), 17):
                stamp = panel.dates[t]
                if stamp not in df.index:
                    continue
                sliced = df.loc[:stamp]
                real = screen_trend(sliced, quote_from(sliced), cfg).passed
                assert bool(passes[t, i]) == real, f"{ticker} on {stamp.date()}"
                checked += 1
        assert checked > 50, "this test is only meaningful if it actually checked things"


class TestFills:
    def test_entry_is_the_next_open_not_the_signal_close(self, cfg):
        frames, bench = synth(["AAA", "BBB"], days=700)
        report = run_over(frames, bench, cfg)
        trades = [t for t in report.trades if t.arm == "screens"]
        assert trades
        for trade in trades[:20]:
            df = frames[trade.ticker]
            expected = float(df.loc[pd.Timestamp(trade.entry_date), "open"])
            assert trade.entry_price == pytest.approx(expected)
            assert trade.entry_date > trade.signal_date

    def test_costs_come_off_every_return(self, cfg):
        frames, bench = synth(["AAA"], days=400)
        panel = bt.build_panel(frames, bench, cfg)
        free = bt.forward_returns(panel, 5, cost_pct=0.0)
        charged = bt.forward_returns(panel, 5, cost_pct=0.25)
        finite = np.isfinite(free) & np.isfinite(charged)
        assert finite.any()
        assert np.allclose(free[finite] - charged[finite], 0.25)

    def test_a_trade_that_runs_past_the_data_is_excluded_not_flat(self, cfg):
        frames, bench = synth(["AAA"], days=400)
        panel = bt.build_panel(frames, bench, cfg)
        returns = bt.forward_returns(panel, 20, cost_pct=0.0)
        assert np.isnan(returns[-1, 0])
        assert np.isnan(returns[-20, 0])


class TestThinning:
    def test_repeat_signals_on_one_ticker_are_dropped(self):
        picks = [(t, 0, 1.0) for t in range(40)]
        assert len(bt._thin(picks, min_gap=20)) == 2

    def test_different_tickers_are_not_thinned_against_each_other(self):
        picks = [(5, 0, 1.0), (5, 1, 1.0), (5, 2, 1.0)]
        assert len(bt._thin(picks, min_gap=20)) == 3

    def test_a_zero_gap_keeps_everything(self):
        picks = [(t, 0, 1.0) for t in range(40)]
        assert len(bt._thin(picks, min_gap=0)) == 40


class TestArms:
    def test_all_three_arms_trade_on_the_same_dates(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=700)
        report = run_over(frames, bench, cfg)
        dates = {arm: set() for arm in ("screens", "random from universe", cfg.beta_benchmark)}
        for trade in report.trades:
            dates[trade.arm].add(trade.signal_date)
        assert dates["screens"], "no signals, this fixture proves nothing"
        # The controls exist to answer "what if I had not screened", so they have
        # to be measured over the same days the screens fired.
        assert dates["random from universe"] <= dates["screens"]
        assert dates[cfg.beta_benchmark] <= dates["screens"]

    def test_the_random_arm_draws_from_the_universe_not_the_signals(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], days=700)
        report = run_over(frames, bench, cfg)
        screened = {(t.ticker, t.signal_date) for t in report.trades if t.arm == "screens"}
        drawn = {
            (t.ticker, t.signal_date) for t in report.trades if t.arm == "random from universe"
        }
        assert drawn - screened, "the control must be able to pick names the screens rejected"


class TestReport:
    def test_the_report_states_its_caveats(self, cfg):
        frames, bench = synth(["AAA", "BBB"], days=700)
        report = run_over(frames, bench, cfg, fit_end=frames["AAA"].index[500].date())
        text = bt.render(report)
        assert "round trip" in text
        assert "calibrated on data up to" in text
        assert "adjusted" in text
        assert "random" in text.lower()

    def test_no_hold_out_says_so_loudly(self, cfg):
        day = pd.Timestamp("2020-01-01").date()
        report = bt.BacktestReport(
            start=day,
            end=day,
            fit_end=None,
            cost_pct=0.2,
            sessions=0,
            universe_days=0.0,
            arms=(),
            trades=(),
        )
        assert "NO HOLD-OUT" in report.in_sample_note


class TestPeriodSplit:
    """The hold-out has to be reported separately or it is not a hold-out."""

    def test_in_and_out_of_sample_are_reported_apart(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        index = frames["AAA"].index
        report = run_over(frames, bench, cfg, fit_end=index[500].date())
        assert report.arms_in_sample and report.arms_out_of_sample
        both = {a.name: a.trades for a in report.arms}
        split = {
            a.name: b.trades + c.trades
            for a, b, c in zip(
                report.arms, report.arms_in_sample, report.arms_out_of_sample, strict=True
            )
        }
        assert both == split, "every trade must land in exactly one period"

    def test_no_fit_end_means_no_split_and_the_report_says_so(self, cfg):
        frames, bench = synth(["AAA", "BBB"], days=700)
        report = run_over(frames, bench, cfg)
        assert not report.arms_out_of_sample
        assert "no hold-out" in bt.render(report).lower()

    def test_the_out_of_sample_table_is_the_headline(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        report = run_over(frames, bench, cfg, fit_end=frames["AAA"].index[500].date())
        text = bt.render(report)
        assert text.index("OUT OF SAMPLE") < text.index("in sample")
        assert "THIS IS THE RESULT" in text
        assert "Do not quote these" in text


class TestConfirmationEntry:
    """The course's actual rule: the FIRST candle holding above the line."""

    def test_confirmation_fires_far_less_often_than_state(self, cfg):
        # Compared at the SIGNAL level, not the recorded-trade level. The two
        # entry rules are thinned differently on purpose (see `run`), so trade
        # counts are not a like-for-like comparison and confirmation can end up
        # with more recorded trades despite firing on a small fraction of the
        # bars. Counting trades here would test the thinning policy and call it
        # a fact about the entry rule.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, cfg)
        state, _ = bt.trend_mask(panel, cfg)
        event, _ = bt.trend_mask(panel, Config(trend_entry="confirmation"))
        assert 0 < event.sum() < state.sum()

    def test_each_entry_rule_gets_the_thinning_it_needs(self, cfg):
        # State fires daily, so unthinned it would count one move many times.
        # Confirmation is already one signal per move, so thinning it would
        # delete genuine re-entries after a failed attempt.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        state = run_over(frames, bench, cfg)
        event = run_over(frames, bench, Config(trend_entry="confirmation"))
        assert state.trades and event.trades

        def gaps(report):
            seen = {}
            out = []
            for t in sorted(
                (t for t in report.trades if t.arm == "screens"),
                key=lambda t: (t.ticker, t.signal_date),
            ):
                if t.ticker in seen:
                    out.append((t.signal_date - seen[t.ticker]).days)
                seen[t.ticker] = t.signal_date
            return out

        assert min(gaps(state)) >= 20, "state entries must not overlap on one ticker"
        assert min(gaps(event)) < 28, "confirmation re-entries must survive"

    def test_every_confirmation_is_a_day_the_state_also_held(self, cfg):
        # A transition into the condition is a subset of the condition.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, cfg)
        state, _ = bt.trend_mask(panel, cfg)
        event, _ = bt.trend_mask(panel, Config(trend_entry="confirmation"))
        assert (event & ~state).sum() == 0
        assert event.sum() < state.sum()

    def test_a_run_of_passing_days_yields_exactly_one_confirmation(self):
        # The whole point. Sixty days above the line is one signal, not sixty.
        cfg = Config(trend_entry="confirmation")
        panel = bt.Panel(
            dates=pd.bdate_range("2026-01-01", periods=6),
            tickers=("X",),
            open=np.full((6, 1), 10.0),
            close=np.array([[9.0], [11.0], [12.0], [13.0], [14.0], [15.0]]),
            fast=np.array([[10.0], [10.0], [10.0], [10.0], [10.0], [10.0]]),
            slow=np.full((6, 1), 5.0),
            gap=np.full((6, 1), 100.0),
            avg_volume=np.full((6, 1), 1e6),
            rsi=np.full((6, 1), 55.0),
            rsi_low=np.full((6, 1), 55.0),
            beta=np.full((6, 1), 3.0),
        )
        state, _ = bt.trend_mask(panel, Config())
        event, _ = bt.trend_mask(panel, cfg)
        assert state.sum() == 5, "bars 1 to 5 are all above the line"
        assert event.sum() == 1, "only the crossing bar is a confirmation"
        assert bool(event[1, 0])

    def test_an_unknown_entry_mode_is_rejected_at_config_time(self):
        with pytest.raises(ValueError, match="trend_entry"):
            Config(trend_entry="vibes")


class TestRsiGate:
    """Gate 3: buy weakness inside strength, rather than strength."""

    def _panel(self, rsi_values):
        n = len(rsi_values)
        return bt.Panel(
            dates=pd.bdate_range("2026-01-01", periods=n),
            tickers=("X",),
            open=np.full((n, 1), 10.0),
            close=np.full((n, 1), 12.0),
            fast=np.full((n, 1), 11.0),
            slow=np.full((n, 1), 5.0),
            gap=np.full((n, 1), 100.0),
            avg_volume=np.full((n, 1), 1e6),
            rsi=np.array(rsi_values, dtype=float).reshape(n, 1),
            rsi_low=np.array(rsi_values, dtype=float).reshape(n, 1),
            beta=np.full((n, 1), 3.0),
        )

    def test_off_by_default_so_earlier_results_stay_comparable(self):
        panel = self._panel([80.0, 20.0, 55.0])
        live, _ = bt.trend_mask(panel, Config())
        assert live.sum() == 3

    def test_only_bars_at_or_under_the_ceiling_pass(self):
        panel = self._panel([80.0, 20.0, 55.0, 30.0])
        live, _ = bt.trend_mask(panel, Config(max_entry_rsi=30.0))
        assert [bool(x) for x in live[:, 0]] == [False, True, False, True]

    def test_a_missing_rsi_reading_fails_rather_than_passes(self):
        # No reading is not the same as a good deal.
        panel = self._panel([np.nan, 20.0])
        live, _ = bt.trend_mask(panel, Config(max_entry_rsi=30.0))
        assert [bool(x) for x in live[:, 0]] == [False, True]

    def test_the_gate_only_ever_removes_signals(self):
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, Config())
        loose, _ = bt.trend_mask(panel, Config())
        strict, _ = bt.trend_mask(panel, Config(max_entry_rsi=30.0))
        assert (strict & ~loose).sum() == 0
        assert strict.sum() < loose.sum()

    def test_an_impossible_ceiling_is_rejected_at_config_time(self):
        with pytest.raises(ValueError, match="max_entry_rsi"):
            Config(max_entry_rsi=150.0)


class TestRsiIsASequenceNotACoincidence:
    def test_a_recent_dip_qualifies_a_strong_bar_today(self):
        # The bug this fixes: requiring oversold ON the crossing bar asked for a
        # candle that is simultaneously breaking up and heavily sold off, which
        # produced zero trades in six years.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, Config(max_entry_rsi=30.0))
        # Skip the warm-up bars: RSI is NaN there, and NaN comparisons are
        # always False, so an unfiltered assertion fails for the wrong reason.
        both = np.isfinite(panel.rsi) & np.isfinite(panel.rsi_low)
        assert both.any()
        assert (panel.rsi_low[both] <= panel.rsi[both] + 1e-9).all()

    def test_the_window_widens_the_gate(self):
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        narrow = bt.build_panel(frames, bench, Config(rsi_lookback=1))
        wide = bt.build_panel(frames, bench, Config(rsi_lookback=20))
        assert np.nanmin(wide.rsi_low) <= np.nanmin(narrow.rsi_low)
        strict, _ = bt.trend_mask(narrow, Config(max_entry_rsi=30.0, rsi_lookback=1))
        loose, _ = bt.trend_mask(wide, Config(max_entry_rsi=30.0, rsi_lookback=20))
        assert loose.sum() >= strict.sum()


class TestTheControlIsAFairComparison:
    """The random arm has to differ from the screens in ONE respect: the names.

    Every other difference is a confound, and the first version had a large one.
    """

    def test_the_control_takes_the_same_number_of_names_on_each_date(self, cfg):
        # The bug this replaced: a flat three draws per signal date, against a
        # screens arm that recorded however many fired. Signal breadth peaks
        # when the market is extended, so the two arms were averaged over
        # different date weightings and the comparison measured the weighting.
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], days=700)
        report = run_over(frames, bench, cfg)
        screens: dict[object, int] = {}
        control: dict[object, int] = {}
        for trade in report.trades:
            if trade.arm == "screens":
                screens[trade.signal_date] = screens.get(trade.signal_date, 0) + 1
            elif trade.arm == "random from universe":
                control[trade.signal_date] = control.get(trade.signal_date, 0) + 1
        assert screens, "no signals, this fixture proves nothing"
        for day, n in screens.items():
            assert control.get(day, 0) == n, f"{day}: {n} screened, {control.get(day, 0)} drawn"

    def test_a_date_with_more_signals_gets_more_control_draws(self):
        universe = np.zeros((3, 5), dtype=bool)
        universe[1, :] = True
        universe[2, :] = True
        rng = np.random.default_rng(0)
        dates, picked = bt._draw_control(universe, {1: 4, 2: 1}, rng)
        assert list(dates).count(1) == 4
        assert list(dates).count(2) == 1
        assert len(set(picked[dates == 1])) == 4, "drawn without replacement"

    def test_asking_for_more_names_than_exist_takes_the_whole_universe(self):
        universe = np.zeros((2, 3), dtype=bool)
        universe[1, :2] = True
        dates, picked = bt._draw_control(universe, {1: 9}, np.random.default_rng(0))
        assert sorted(picked) == [0, 1]


class TestTheNullTest:
    """One control is an anecdote. The percentile is the result."""

    def test_the_percentile_is_reported_for_the_quoted_period(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD", "EEE"], days=900)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames,
            bench,
            cfg,
            start=index[400].date(),
            end=index[-30].date(),
            fit_end=index[700].date(),
            replicates=25,
        )
        null = report.null_test
        assert null is not None
        assert null.replicates == 25
        assert str(index[700].date()) in null.period
        for horizon in bt.HORIZONS:
            assert 0.0 <= null.beats_pct[horizon] <= 100.0
            assert null.random_p05[horizon] <= null.random_median[horizon]
            assert null.random_median[horizon] <= null.random_p95[horizon]

    def test_a_screen_that_only_ever_buys_the_best_name_beats_every_control(self):
        # A rigged panel where one ticker rises and the rest fall. A screen that
        # finds it should sit at the top of the distribution. If this does not
        # come out at 100 the percentile is not measuring what it claims to.
        n, m = 60, 6
        rng = np.random.default_rng(3)
        close = np.zeros((n, m))
        close[:, 0] = np.linspace(100.0, 200.0, n)
        for i in range(1, m):
            close[:, i] = np.linspace(100.0, 60.0, n) + rng.normal(0, 0.5, n)
        panel = bt.Panel(
            dates=pd.bdate_range("2024-01-01", periods=n),
            tickers=tuple("ABCDEF"),
            open=close,
            close=close,
            fast=np.full((n, m), 1.0),
            slow=np.full((n, m), 1.0),
            gap=np.full((n, m), 10.0),
            avg_volume=np.full((n, m), 1e6),
            rsi=np.full((n, m), 50.0),
            rsi_low=np.full((n, m), 50.0),
            beta=np.full((n, m), 3.0),
        )
        universe = np.ones((n, m), dtype=bool)
        returns = {h: bt.forward_returns(panel, h, 0.0) for h in bt.HORIZONS}
        days = list(range(5, 30))
        null = bt.null_distribution(
            panel,
            universe,
            dict.fromkeys(days, 1),
            returns,
            np.asarray(days),
            np.zeros(len(days), dtype=int),  # always the winner
            np.ones(n, dtype=bool),
            "test",
            replicates=60,
        )
        for horizon in bt.HORIZONS:
            assert null.beats_pct[horizon] == 100.0
            assert null.screens_mean[horizon] > null.random_p95[horizon]

    def test_a_screen_that_picks_at_random_lands_in_the_middle(self):
        n, m = 80, 8
        rng = np.random.default_rng(11)
        close = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, (n, m)), axis=0)
        panel = bt.Panel(
            dates=pd.bdate_range("2024-01-01", periods=n),
            tickers=tuple("ABCDEFGH"),
            open=close,
            close=close,
            fast=np.full((n, m), 1.0),
            slow=np.full((n, m), 1.0),
            gap=np.full((n, m), 10.0),
            avg_volume=np.full((n, m), 1e6),
            rsi=np.full((n, m), 50.0),
            rsi_low=np.full((n, m), 50.0),
            beta=np.full((n, m), 3.0),
        )
        universe = np.ones((n, m), dtype=bool)
        returns = {h: bt.forward_returns(panel, h, 0.0) for h in bt.HORIZONS}
        days = list(range(5, 45))
        chooser = np.random.default_rng(99)
        null = bt.null_distribution(
            panel,
            universe,
            dict.fromkeys(days, 1),
            returns,
            np.asarray(days),
            chooser.integers(0, m, len(days)),
            np.ones(n, dtype=bool),
            "test",
            replicates=100,
        )
        # A coin toss should not clear the bar. This is the assertion that
        # stops the machinery from flattering whatever it is handed.
        assert not any(null.beats_pct[h] >= 95.0 for h in bt.HORIZONS)

    def test_the_verdict_refuses_to_call_a_small_sample(self):
        assert "decides nothing" in bt.verdict(99.0, trades=12)
        assert "worth taking seriously" in bt.verdict(97.0, trades=200)
        assert "coin toss" in bt.verdict(52.0, trades=200)
        assert "worse than picking at random" in bt.verdict(3.0, trades=200)

    def test_the_verdict_appears_in_the_rendered_report(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=900)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames,
            bench,
            cfg,
            start=index[400].date(),
            end=index[-30].date(),
            fit_end=index[700].date(),
            replicates=20,
        )
        text = bt.render(report)
        assert "IS IT LUCK?" in text
        assert "random controls" in text
        assert "20 random controls" in text
