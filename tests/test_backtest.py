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

from helpers import make_bars, quote_from
from stocksignal import backtest as bt
from stocksignal.config import Config
from stocksignal.data import SyntheticSource, shuffle_order, shuffle_returns
from stocksignal.levels import nearest_levels
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


def panel_of(close, **overrides):
    """A Panel with permissive defaults, so a test overrides only what it is about.

    Hand-building the full struct in every test meant that adding one field to
    `Panel` broke seven unrelated tests and taught nothing. Defaults here are
    deliberately permissive: every gate passes unless a test says otherwise.
    """
    close = np.asarray(close, dtype=float)
    n, m = close.shape
    full = dict(
        dates=pd.bdate_range("2026-01-01", periods=n),
        tickers=tuple("ABCDEFGHIJKLMNOP"[:m]),
        open=close.copy(),
        close=close,
        high=close * 1.01,
        low=close * 0.99,
        fast=np.full((n, m), 1.0),
        slow=np.full((n, m), 1.0),
        gap=np.full((n, m), 10.0),
        avg_volume=np.full((n, m), 1e6),
        rsi=np.full((n, m), 50.0),
        rsi_low=np.full((n, m), 50.0),
        reward_risk=np.full((n, m), 5.0),
        support=np.full((n, m), np.nan),
        resistance=np.full((n, m), np.nan),
        beta=np.full((n, m), 3.0),
    )
    full.update(overrides)
    return bt.Panel(**full)


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
        panel = panel_of(
            np.array([[9.0], [11.0], [12.0], [13.0], [14.0], [15.0]]),
            # Opens half a point under each close, so the OPEN crosses the fast
            # SMA on bar 1 exactly as the close does. Since 2026-08-14 the short
            # SMA is tested against the open (page 116), so a flat open under
            # the line would fail every bar and this test would measure nothing.
            open=np.array([[8.5], [10.5], [11.5], [12.5], [13.5], [14.5]]),
            fast=np.full((6, 1), 10.0),
            slow=np.full((6, 1), 5.0),
            gap=np.full((6, 1), 100.0),
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
        readings = np.array(rsi_values, dtype=float).reshape(n, 1)
        return panel_of(
            np.full((n, 1), 12.0),
            # Above the fast SMA and still distinct from the close. The short
            # SMA is tested on the open (page 116); this fixture is about the
            # gate under test, not about confirmation, so it must clear it.
            open=np.full((n, 1), 11.5),
            fast=np.full((n, 1), 11.0),
            slow=np.full((n, 1), 5.0),
            gap=np.full((n, 1), 100.0),
            rsi=readings,
            rsi_low=readings,
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
        assert null.distinct_tickers > 0
        for horizon in bt.HORIZONS:
            for stat in bt.STATS:
                assert 0.0 <= null.beats_pct[horizon][stat] <= 100.0
                assert null.random_p05[horizon][stat] <= null.random_median[horizon][stat]
                assert null.random_median[horizon][stat] <= null.random_p95[horizon][stat]

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
        panel = panel_of(close, dates=pd.bdate_range("2024-01-01", periods=n))
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
        # The ceiling, not 100. With 60 controls the strongest honest claim is
        # 1 - 1/61 = 98.4%: a permutation test cannot report p = 0.
        ceiling = 100.0 * (1.0 - 1.0 / 61.0)
        for horizon in bt.HORIZONS:
            assert null.beats_pct[horizon]["mean"] == pytest.approx(ceiling)
            assert null.screens[horizon]["mean"] > null.random_p95[horizon]["mean"]

    def test_a_screen_that_picks_at_random_lands_in_the_middle(self):
        n, m = 80, 8
        rng = np.random.default_rng(11)
        close = 100.0 * np.cumprod(1 + rng.normal(0, 0.02, (n, m)), axis=0)
        panel = panel_of(close, dates=pd.bdate_range("2024-01-01", periods=n))
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
        assert not any(null.beats_pct[h]["mean"] >= 95.0 for h in bt.HORIZONS)

    def _null(self, trades=200, family=1, replicates=200, **pct):
        """A NullTest with the percentiles dialled in by hand."""
        beats = {h: {"mean": 50.0, "median": 50.0, "trimmed": 50.0} for h in bt.HORIZONS}
        for stat, value in pct.items():
            for h in bt.HORIZONS:
                beats[h][stat] = value
        flat = {h: dict.fromkeys(bt.STATS, 1.0) for h in bt.HORIZONS}
        return bt.NullTest(
            replicates=replicates,
            period="test",
            screen_trades=trades,
            distinct_tickers=20,
            family_size=family,
            exit_rule="hold",
            screens=flat,
            random_median=flat,
            random_p05=flat,
            random_p95=flat,
            beats_pct=beats,
            tail_lift=dict.fromkeys(bt.HORIZONS, 1.5),
        )

    def test_the_verdict_refuses_to_call_a_small_sample(self):
        said = bt.verdict(self._null(trades=12, mean=99.0), 20)
        assert "decides nothing" in said

    def test_a_clean_pass_is_called_a_pass(self):
        said = bt.verdict(self._null(mean=99.0, median=99.0, trimmed=99.0, family=1), 20)
        assert "Take this seriously" in said

    def test_a_coin_toss_is_called_a_coin_toss(self):
        assert "coin toss" in bt.verdict(self._null(mean=52.0), 20)

    def test_worse_than_random_is_said_out_loud(self):
        assert "worse than picking at random" in bt.verdict(self._null(mean=3.0), 20)

    def test_an_edge_that_lives_in_its_tail_is_called_out(self):
        # The whole reason the trimmed statistic exists. A mean that clears the
        # bar while the trimmed mean does not is not a weaker pass, it is a
        # different finding, and the verdict has to say which one it is.
        said = bt.verdict(self._null(mean=99.0, median=99.0, trimmed=40.0), 20)
        assert "edge IS the tail" in said

    def test_a_mean_that_passes_on_a_worse_typical_trade_is_called_out(self):
        said = bt.verdict(self._null(mean=99.0, median=20.0, trimmed=99.0), 20)
        assert "WORSE than random" in said
        assert "1.50 points" in said

    def test_the_bar_rises_with_the_number_of_variants_tried(self):
        # 96% is a pass if it was the only thing tested and noise if it is one
        # of twelve. Same number, different meaning, and the report must not
        # present them identically.
        alone = self._null(mean=96.0, median=96.0, trimmed=96.0, family=1)
        one_of_twelve = self._null(mean=96.0, median=96.0, trimmed=96.0, family=12, replicates=5000)
        assert "Take this seriously" in bt.verdict(alone, 20)
        assert "Promising, not proven" in bt.verdict(one_of_twelve, 20)

    def test_too_few_controls_to_resolve_the_bar_says_so(self):
        # 200 controls resolve to 0.5%, so a 99.58% bar is not expressible.
        # Printing a confident verdict off that would be an artefact.
        tight = self._null(mean=99.0, median=99.0, trimmed=99.0, family=12, replicates=200)
        assert not tight.resolvable
        assert "cannot resolve" in bt.verdict(tight, 20)

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


class TestGate1RewardRisk:
    """Gate 1, page 115: more upward potential than downward."""

    def test_levels_are_causal_because_truncation_agrees_with_them(self, cfg):
        # THE test for this feature. Everywhere else in the project causality
        # comes free from truncating the frame; `nearest_levels` is handed the
        # whole history and has to shift the centred swing window by hand. If
        # that shift is wrong by one bar the backtest knows where price turned
        # before it turned. So: compute at every bar, then recompute on a frame
        # truncated at each sampled bar, and demand they agree exactly.
        frames, _ = synth(["AAA"], days=800)
        df = frames["AAA"]
        full = nearest_levels(df, cfg)
        checked = 0
        for t in range(300, len(df), 23):
            truncated = nearest_levels(df.iloc[: t + 1], cfg).iloc[-1]
            for column in ("resistance", "support"):
                seen, known = truncated[column], full.iloc[t][column]
                if np.isnan(seen) and np.isnan(known):
                    continue
                assert seen == pytest.approx(known), f"{column} at bar {t} saw the future"
            checked += 1
        assert checked > 15, "this test is only meaningful if it actually checked things"

    def test_a_level_appears_only_when_its_third_touch_is_confirmed(self, cfg):
        # Two things at once, both causal. A swing at bar i needs bars i+1..i+5
        # to print lower before anyone can call it a high, AND under the
        # rulebook's three-confirmation rule the LEVEL does not exist until the
        # third of those swings has itself been confirmed.
        #
        # The baseline is a rising ramp rather than a flat line: `swing_points`
        # compares with `==`, so on a plateau every bar ties the rolling max and
        # every bar registers as a swing. A flat fixture would test the fixture.
        closes = [100.0 + 0.5 * i for i in range(90)]
        for peak in (20, 40, 60):
            closes[peak] = 200.0
        df = make_bars(closes)
        levels = nearest_levels(df, cfg)
        swing = cfg.level_swing_lookback

        # Two touches is a coincidence, not a level.
        assert levels["resistance"].iloc[: 60 + swing].isna().all(), (
            "a level formed before its third touch was confirmed"
        )
        assert levels["resistance"].iloc[60 + swing] == pytest.approx(200.0 * 1.01)

    def test_one_lonely_swing_is_not_a_level(self, cfg):
        closes = [100.0 + 0.5 * i for i in range(90)]
        closes[40] = 200.0
        df = make_bars(closes)
        assert nearest_levels(df, cfg)["resistance"].isna().all()
        # ...unless you ask for the old single-touch behaviour, which is kept
        # only so the two can be compared.
        loose = nearest_levels(df, Config(level_source="swings"))
        assert loose["resistance"].iloc[45] == pytest.approx(200.0 * 1.01)

    def test_no_ceiling_above_fails_the_gate_rather_than_passing_it(self):
        # NaN means "I cannot see a level", not "there is no level". A gate that
        # treats the two alike passes every stock at an all-time high, which is
        # the exact setup gate 1 exists to be careful about.
        n = 4
        panel = panel_of(
            np.full((n, 1), 12.0),
            # Above the fast SMA and still distinct from the close. The short
            # SMA is tested on the open (page 116); this fixture is about the
            # gate under test, not about confirmation, so it must clear it.
            open=np.full((n, 1), 11.5),
            fast=np.full((n, 1), 11.0),
            slow=np.full((n, 1), 5.0),
            gap=np.full((n, 1), 100.0),
            reward_risk=np.array([[np.nan], [0.5], [1.0], [4.0]]),
        )
        loose, _ = bt.trend_mask(panel, Config())
        assert loose.sum() == 4, "gate 1 must be off by default"
        gated, _ = bt.trend_mask(panel, Config(min_reward_risk=1.0))
        assert list(gated[:, 0]) == [False, False, True, True]
        strict, _ = bt.trend_mask(panel, Config(min_reward_risk=2.0))
        assert list(strict[:, 0]) == [False, False, False, True]

    def test_the_ratio_is_upside_over_downside_from_todays_close(self, cfg):
        # Worked by hand so the arithmetic cannot drift. Three peaks at 110 and
        # three troughs at 90, spaced far enough apart to be separate swings,
        # then a climb to a close of 100 that forms no further ones.
        anchors = [(0, 100.0), (6, 110.0), (18, 90.0), (30, 110.0)]
        anchors += [(42, 90.0), (54, 110.0), (66, 90.0), (80, 100.0)]
        closes = list(
            np.interp(
                np.arange(81),
                [bar for bar, _ in anchors],
                [price for _, price in anchors],
            )
        )
        row = nearest_levels(make_bars(closes), cfg).iloc[-1]
        assert row["resistance"] == pytest.approx(110.0 * 1.01), "the three-touch ceiling"
        assert row["support"] == pytest.approx(90.0 * 0.99), "the three-touch floor"
        assert row["upside_pct"] == pytest.approx(11.1)
        assert row["downside_pct"] == pytest.approx(10.9)
        assert row["reward_risk"] == pytest.approx(11.1 / 10.9)

    def test_highs_and_lows_pool_so_a_broken_ceiling_can_become_a_floor(self, cfg):
        # The flip rule, page 14: "if a stock breaks a resistance level it now
        # becomes support". That is only expressible if nothing is born a
        # support or a resistance. The first version kept two separate pools
        # keyed on swing highs and swing lows, which made the rule impossible.
        anchors = [(0, 100.0), (6, 110.0), (18, 90.0), (30, 110.0)]
        anchors += [(42, 90.0), (54, 110.0), (66, 90.0), (85, 125.0)]
        closes = list(
            np.interp(
                np.arange(86),
                [bar for bar, _ in anchors],
                [price for _, price in anchors],
            )
        )
        row = nearest_levels(make_bars(closes), cfg).iloc[-1]
        # Price is now above the old ceiling, so the ceiling reads as the floor.
        assert row["support"] == pytest.approx(110.0 * 1.01), "the broken ceiling did not flip"

    def test_the_gate_only_ever_removes_signals(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=700)
        panel = bt.build_panel(frames, bench, cfg)
        loose, _ = bt.trend_mask(panel, cfg)
        gated, _ = bt.trend_mask(panel, Config(min_reward_risk=1.0))
        assert (gated & ~loose).sum() == 0
        assert gated.sum() < loose.sum(), "this fixture proves nothing if nothing is removed"

    def test_an_impossible_ratio_is_rejected_at_config_time(self):
        with pytest.raises(ValueError, match="min_reward_risk"):
            Config(min_reward_risk=0.0)


# Exit mechanics tests care about fills, not about the matched-geometry rule
# that keeps the ARMS comparable, so they switch that off and say so. They also
# use single swing points rather than three-touch levels: the question is what
# happens WHEN a stop is hit, and three-touch levels are sparse enough on
# synthetic data that most bars would have no stop to hit at all.
STOPS_ONLY = Config(exit_rule="stops", exit_requires_levels=False, level_source="swings")


class TestExitRules:
    """Section 4 of the rulebook: the stop, the target, and the trail.

    Every assertion here is about a fill nobody would dispute. A backtest lies
    to you most comfortably at the moment it decides what price you got.
    """

    def _one(self, closes, highs=None, lows=None, opens=None, **kw):
        """One ticker, bars spelled out.

        `opens` matters more than it looks. The fill rule takes the WORSE of the
        stop and the bar's open, so a fixture that lazily sets open == close
        will fill at the close and the test will "fail" while the code is
        right — which is exactly what happened when these were first written.
        """
        close = np.asarray(closes, dtype=float).reshape(-1, 1)
        n = len(close)

        def col(values):
            return close.copy() if values is None else np.asarray(values, float).reshape(n, 1)

        return panel_of(close, open=col(opens), high=col(highs), low=col(lows), **kw)

    def test_with_no_level_in_range_stops_change_nothing(self):
        # The seam has to be exact: a trade that never touches a stop or a
        # target must return precisely what holding returned, or every
        # comparison against the earlier results is measuring the plumbing.
        frames, bench = synth(["AAA", "BBB", "CCC"], days=700)
        panel = bt.build_panel(frames, bench, Config())
        bare = bt.Panel(
            **{
                **panel.__dict__,
                "support": np.full_like(panel.support, np.nan),
                "resistance": np.full_like(panel.resistance, np.nan),
            }
        )
        held = bt.forward_returns(bare, 10, 0.2)
        stopped = bt.exit_returns(bare, 10, 0.2, STOPS_ONLY)
        finite = np.isfinite(held) & np.isfinite(stopped)
        assert finite.any()
        assert np.allclose(held[finite], stopped[finite])

    def test_the_hard_stop_caps_the_loss(self):
        # Enter at 100, stop at 95, then price falls off a cliff. Holding loses
        # 80%; the stop loses about 5%.
        panel = self._one(
            [100.0, 100.0, 90.0, 60.0, 20.0, 20.0],
            opens=[100.0, 100.0, 100.0, 60.0, 20.0, 20.0],
            lows=[100.0, 100.0, 94.0, 60.0, 20.0, 20.0],
            support=np.full((6, 1), 95.0),
        )
        held = bt.forward_returns(panel, 4, 0.0)[0, 0]
        stopped = bt.exit_returns(panel, 4, 0.0, STOPS_ONLY)[0, 0]
        assert held == pytest.approx(-80.0)
        assert stopped == pytest.approx(-5.0)

    def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop(self):
        # The decision that stops this from flattering itself. Price closes at
        # 100 and opens at 80 the next morning, straight through a stop at 95.
        # You did not get 95. You got 80.
        close = np.array([[100.0], [100.0], [80.0], [80.0]])
        panel = panel_of(
            close,
            open=np.array([[100.0], [100.0], [80.0], [80.0]]),
            high=np.array([[100.0], [100.0], [80.0], [80.0]]),
            low=np.array([[100.0], [100.0], [80.0], [80.0]]),
            support=np.full((4, 1), 95.0),
        )
        got = bt.exit_returns(panel, 2, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(-20.0), "filled at the stop price it never traded at"

    def test_when_one_bar_covers_both_the_stop_wins(self):
        # Daily bars cannot say which came first. Assuming the stop means the
        # losing reading always wins, so the result is a floor, not a guess.
        panel = self._one(
            [100.0, 100.0, 100.0, 100.0],
            opens=[100.0, 100.0, 100.0, 100.0],
            highs=[100.0, 100.0, 130.0, 100.0],
            lows=[100.0, 100.0, 90.0, 100.0],
            support=np.full((4, 1), 95.0),
            resistance=np.full((4, 1), 120.0),
        )
        got = bt.exit_returns(panel, 2, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(-5.0), "took the target on a bar that also hit the stop"

    def test_the_trailing_stop_only_arms_after_the_target(self):
        # Price rises 4% and falls back. That is a 5% round trip from the peak,
        # so a trail armed from entry would have fired. The target was never
        # reached, so it must not have.
        panel = self._one(
            [100.0, 100.0, 104.0, 98.0, 98.0],
            opens=[100.0, 100.0, 102.0, 102.0, 98.0],
            highs=[100.0, 100.0, 104.0, 104.0, 98.0],
            lows=[100.0, 100.0, 104.0, 98.0, 98.0],
            support=np.full((5, 1), 90.0),
            resistance=np.full((5, 1), 120.0),
        )
        got = bt.exit_returns(panel, 3, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(-2.0), "the trail armed before the target was reached"

    def test_the_trail_follows_the_high_up_and_never_back_down(self):
        # Target at 110 reached on bar 2 (high 120, so peak 120, trail 114).
        # Bar 3 dips to 115: above the trail, still in. Bar 4 dips to 113:
        # through it, out at 114.
        panel = self._one(
            [100.0, 100.0, 118.0, 116.0, 113.0, 113.0],
            opens=[100.0, 100.0, 118.0, 116.0, 116.0, 113.0],
            highs=[100.0, 100.0, 120.0, 118.0, 116.0, 113.0],
            lows=[100.0, 100.0, 112.0, 115.0, 113.0, 113.0],
            support=np.full((6, 1), 90.0),
            resistance=np.full((6, 1), 110.0),
        )
        got = bt.exit_returns(panel, 4, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(14.0), "the 5% trail below the 120 peak is 114"

    def test_a_stop_at_or_above_entry_is_ignored_rather_than_instant(self):
        # `nearest_levels` reads support from the signal bar's close. Price can
        # gap up overnight and leave that support above the entry, which would
        # otherwise stop the trade out on its own first tick.
        #
        # The support has to be ABOVE the 120 entry for this to test anything.
        # The first version used 110, which was already below it, so the mask
        # was never exercised and deleting it left the test green.
        panel = self._one([100.0, 120.0, 130.0, 140.0], support=np.full((4, 1), 125.0))
        got = bt.exit_returns(panel, 2, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(140.0 / 120.0 * 100.0 - 100.0)

    def test_costs_still_come_off_once(self):
        panel = self._one([100.0, 100.0, 110.0, 110.0])
        free = bt.exit_returns(panel, 2, 0.0, STOPS_ONLY)[0, 0]
        charged = bt.exit_returns(panel, 2, 0.25, STOPS_ONLY)[0, 0]
        assert free - charged == pytest.approx(0.25)

    def test_the_dispatcher_honours_the_config(self):
        frames, bench = synth(["AAA", "BBB"], days=500)
        panel = bt.build_panel(frames, bench, Config())
        held = bt.horizon_returns(panel, 10, 0.2, Config(exit_rule="hold"))
        assert np.allclose(held, bt.forward_returns(panel, 10, 0.2), equal_nan=True), (
            "hold must be untouched, or every earlier result silently changes"
        )

    def test_stops_shrink_the_left_tail_on_real_shaped_data(self):
        # The claim the whole exercise rests on. Not "stops make money" — only
        # that they bound what a loser costs, which is what the rulebook says
        # they are for.
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=1200)
        cfg = STOPS_ONLY
        panel = bt.build_panel(frames, bench, cfg)
        held = bt.forward_returns(panel, 20, 0.2)
        stopped = bt.exit_returns(panel, 20, 0.2, cfg)
        finite = np.isfinite(held) & np.isfinite(stopped)
        assert np.nanmin(stopped[finite]) > np.nanmin(held[finite])

    def test_arming_the_trail_never_lowers_the_exit_level(self):
        # The bug an independent review caught. Arming used to REPLACE the hard
        # stop with peak * 0.95, so when the target sat less than about 5.26%
        # above the stop, reaching it moved the exit DOWN. Entry 100, stop 98,
        # target 102: bar 2 tags 102 and arms a trail at 96.9, and a bar-3 low
        # of 97 should exit at the hard stop for -2%, not survive to 96.9.
        panel = self._one(
            [100.0, 100.0, 101.0, 97.0, 97.0],
            opens=[100.0, 100.0, 100.0, 99.0, 97.0],
            highs=[100.0, 100.0, 102.0, 99.0, 97.0],
            lows=[100.0, 100.0, 100.0, 97.0, 97.0],
            support=np.full((5, 1), 98.0),
            resistance=np.full((5, 1), 102.0),
        )
        got = bt.exit_returns(panel, 3, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(-2.0), "the trail undercut the pre-committed hard stop"

    def test_a_trade_that_closed_early_survives_a_later_missing_bar(self):
        # One NaN close in the middle of the history used to discard a trade
        # that had already stopped out many sessions earlier, for no reason.
        closes = [100.0, 100.0, 90.0, 95.0, 95.0, 95.0, 95.0]
        panel = self._one(
            closes,
            opens=[100.0, 100.0, 100.0, 95.0, 95.0, 95.0, 95.0],
            lows=[100.0, 100.0, 94.0, 95.0, 95.0, 95.0, 95.0],
            support=np.full((7, 1), 95.0),
        )
        holed = np.array(panel.close, copy=True)
        holed[5, 0] = np.nan
        panel = bt.Panel(**{**panel.__dict__, "close": holed})
        got = bt.exit_returns(panel, 4, 0.0, STOPS_ONLY)[0, 0]
        assert got == pytest.approx(-5.0), "a later missing bar erased a completed trade"

    def test_an_unknown_exit_rule_is_rejected_at_config_time(self):
        with pytest.raises(ValueError, match="exit_rule"):
            Config(exit_rule="hope")


class TestTheArmsGetTheSameGeometry:
    """The trap that nearly became a finding.

    A trend screen picks names near their highs, which often have no resistance
    above them. No resistance means no target, which means the trailing stop
    never arms, which means their winners run uncapped while the control's get
    trimmed. On a feed containing no signal at all, that alone put the screens
    at the 96th percentile.
    """

    def test_a_trade_missing_either_level_is_not_taken(self):
        panel = panel_of(
            np.full((5, 1), 100.0),
            support=np.full((5, 1), 90.0),
            resistance=np.full((5, 1), np.nan),
        )
        matched = bt.exit_returns(panel, 3, 0.0, Config(exit_rule="stops"))
        assert not np.isfinite(matched).any(), "took a trade with no target"
        loose = bt.exit_returns(panel, 3, 0.0, STOPS_ONLY)
        assert np.isfinite(loose[0, 0]), "the opt-out must still trade it"

    def test_screened_names_really_do_have_targets_less_often(self, cfg):
        # The measurement behind the rule, kept as a test so it cannot quietly
        # stop being true. If this ever fails, the correction is unnecessary
        # and should be revisited rather than left in place out of habit.
        frames, bench = synth([a + b for a in "ABCDEFGH" for b in "XYZ"], days=1100)
        confirmation = Config(trend_entry="confirmation")
        panel = bt.build_panel(frames, bench, confirmation)
        universe = bt.universe_mask(panel, confirmation)
        signals, _ = bt.trend_mask(panel, confirmation, universe=universe)
        entry = bt._shift_back(panel.open, 1)
        has_target = np.isfinite(panel.resistance) & (panel.resistance > entry)
        eligible = universe & np.isfinite(entry)
        assert has_target[signals & universe].mean() < has_target[eligible].mean(), (
            "screened picks no longer skew towards having no ceiling above them"
        )

    def test_with_matched_geometry_a_signal_free_feed_lands_mid_pack(self):
        # The end-to-end proof that the correction worked: on data with no
        # predictive structure the screens must come out ordinary.
        #
        # AVERAGED OVER SEVERAL DRAWS, and the first version of this test was
        # wrong for exactly the reason the project spent a day learning. It ran
        # ONE feed and asserted the percentile was under 95. That statistic is
        # enormously noisy at these trade counts: twenty shuffles of real data
        # produced percentiles spanning 0 to 95 with a mean of 50. A single
        # reading tells you almost nothing, and asserting on one would fail
        # roughly one run in twenty for no reason at all. So: several feeds,
        # every horizon, and the assertion is on the average.
        readings: list[float] = []
        for seed in (23, 41, 67):
            frames, bench = synth([a + b for a in "ABCDEF" for b in "XYZ"], days=1200, seed=seed)
            index = next(iter(frames.values())).index
            report = bt.run(
                frames,
                bench,
                Config(trend_entry="confirmation", exit_rule="stops"),
                start=index[400].date(),
                end=index[-30].date(),
                replicates=60,
            )
            null = report.null_test
            assert null is not None
            readings.extend(null.beats_pct[h]["mean"] for h in bt.HORIZONS)

        average = float(np.mean(readings))
        assert 20.0 < average < 80.0, (
            f"screens averaged the {average:.0f}th percentile on feeds with no signal in them"
        )


class TestTheMedianIsNotEvidenceUnderStops:
    """The second artefact, caught the same way as the first.

    A hard stop piles stopped-out trades into a dense lump just below zero. The
    median sits inside that lump, so a small difference in how often an arm gets
    stopped moves it a long way. Trend-screened names are stopped slightly less
    often for reasons unrelated to prediction, and on a signal-free feed their
    median still beat 99-100% of controls.
    """

    def test_the_report_warns_and_the_verdict_ignores_it(self):
        frames, bench = synth([a + b for a in "ABCDEF" for b in "XYZ"], days=1100)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames,
            bench,
            Config(trend_entry="confirmation", exit_rule="stops"),
            start=index[400].date(),
            end=index[-30].date(),
            fit_end=index[700].date(),
            replicates=80,
        )
        text = bt.render(report)
        assert "ignore, see below" in text
        assert "not evidence under stops" in text
        assert report.null_test is not None
        assert report.null_test.exit_rule == "stops"

    def test_a_high_mean_with_a_low_median_is_not_blamed_on_the_tail_under_stops(self):
        # Under "hold" that pattern is a real diagnosis. Under "stops" the median
        # is unreliable, so the verdict must not reach for it as an explanation.
        builder = TestTheNullTest()
        held = builder._null(mean=99.0, median=20.0, trimmed=99.0, family=1)
        assert "WORSE than random" in bt.verdict(held, 20)

        stopped = bt.NullTest(
            **{**held.__dict__, "exit_rule": "stops"},
        )
        assert "WORSE than random" not in bt.verdict(stopped, 20)
        assert "Take this seriously" in bt.verdict(stopped, 20)

    def test_no_warning_when_holding_to_the_horizon(self, cfg):
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=900)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames, bench, cfg, start=index[400].date(), end=index[-30].date(), replicates=20
        )
        assert "ignore, see below" not in bt.render(report)


class TestTheEstimatorAndTheControlsConstraints:
    """Two corrections that came out of an independent statistical review.

    Both point the same way: the first version was willing to overstate, and the
    second was quietly hiding real effects rather than inventing them.
    """

    def test_the_percentile_can_never_claim_certainty(self):
        # A raw proportion prints 100%, which asserts p = 0 off a finite number
        # of dice rolls. The add-one estimator caps at 1 - 1/(R+1).
        n, m = 40, 4
        close = np.tile(np.linspace(100.0, 130.0, n).reshape(n, 1), (1, m))
        close[:, 1:] = np.linspace(100.0, 70.0, n).reshape(n, 1)
        panel = panel_of(close, dates=pd.bdate_range("2024-01-01", periods=n))
        returns = {h: bt.forward_returns(panel, h, 0.0) for h in bt.HORIZONS}
        days = list(range(5, 18))
        for replicates in (50, 200):
            null = bt.null_distribution(
                panel,
                np.ones((n, m), dtype=bool),
                dict.fromkeys(days, 1),
                returns,
                np.asarray(days),
                np.zeros(len(days), dtype=int),
                np.ones(n, dtype=bool),
                "test",
                replicates=replicates,
            )
            for horizon in bt.HORIZONS:
                got = null.beats_pct[horizon]["mean"]
                assert got < 100.0
                assert got == pytest.approx(100.0 * (1.0 - 1.0 / (replicates + 1.0)))

    def test_the_control_obeys_the_same_no_repeat_rule_as_the_screens(self):
        # The screens are thinned so a ticker cannot signal twice inside the
        # gap. An unthinned control can, and its repeats overlap by 19 of 20
        # sessions, which widens the null and buries real effects.
        universe = np.ones((60, 12), dtype=bool)
        counts = dict.fromkeys(range(0, 40, 4), 2)
        rng = np.random.default_rng(0)
        dates, picked = bt._draw_control(universe, counts, rng, min_gap=20)
        seen: dict[int, int] = {}
        for t, i in zip(dates, picked, strict=True):
            if int(i) in seen:
                assert t - seen[int(i)] >= 20, f"ticker {i} redrawn after {t - seen[int(i)]}"
            seen[int(i)] = int(t)
        assert len(dates) == sum(counts.values()), "the count per date must survive the constraint"

    def test_the_constraint_yields_rather_than_break_count_matching(self):
        # Count matching is the more important property. With too few names to
        # honour the gap, the draw fills the date anyway rather than short it.
        universe = np.ones((30, 2), dtype=bool)
        counts = dict.fromkeys(range(0, 10, 2), 2)
        dates, _ = bt._draw_control(universe, counts, np.random.default_rng(0), min_gap=20)
        assert len(dates) == sum(counts.values())

    def test_two_hundred_controls_cannot_decide_at_the_corrected_bar(self):
        # Ten expected exceedances, not one. One is enough for the grid to
        # contain the bar and not nearly enough to decide at it.
        builder = TestTheNullTest()
        assert not builder._null(family=15, replicates=200).resolvable
        assert not builder._null(family=15, replicates=2000).resolvable
        assert builder._null(family=15, replicates=5000).resolvable


class TestShuffledReturnsAreARealNull:
    """The control that does not have to be proved neutral.

    Three artefacts were traced to `SyntheticSource` having structure it was
    advertised as not having. Shuffling real bars sidesteps the problem: it
    keeps volatility, price level and candle shape, and destroys every
    time-series relationship a technical screen reads.
    """

    def test_the_bars_keep_their_shape_and_lose_their_order(self):
        frames, _ = synth(["AAA"], days=600)
        original = frames["AAA"]
        shuffled = shuffle_returns(original, shuffle_order(original.index, seed=3))

        assert list(shuffled.index) == list(original.index)
        assert shuffled["close"].iloc[0] == pytest.approx(original["close"].iloc[0])
        # Same set of daily moves, different order.
        before = np.sort(original["close"].to_numpy()[1:] / original["close"].to_numpy()[:-1])
        after = np.sort(shuffled["close"].to_numpy()[1:] / shuffled["close"].to_numpy()[:-1])
        assert np.allclose(before, after)
        assert not np.allclose(original["close"].to_numpy(), shuffled["close"].to_numpy()), (
            "the order survived"
        )

    def test_every_bar_stays_internally_consistent(self):
        frames, _ = synth(["AAA", "BBB"], days=400)
        order = shuffle_order(next(iter(frames.values())).index, seed=11)
        for name, df in frames.items():
            out = shuffle_returns(df, order)
            assert (out["high"] >= out[["open", "close"]].max(axis=1) - 1e-9).all(), name
            assert (out["low"] <= out[["open", "close"]].min(axis=1) + 1e-9).all(), name
            assert (out["close"] > 0).all(), name
            # Candle proportions are the bar's own, only the level moved.
            ratio = out["high"] / out["close"]
            assert np.allclose(ratio, df["high"] / df["close"])

    def test_the_trend_screen_finds_far_less_to_like(self):
        # The point of the control. Shuffling destroys persistence, so a screen
        # built on moving-average structure should fire markedly less often.
        frames, bench = synth([a + b for a in "ABCDEF" for b in "XYZ"], days=900)
        cfg = Config(trend_entry="confirmation")
        real = bt.trend_mask(bt.build_panel(frames, bench, cfg), cfg)[0].sum()
        order = shuffle_order(bench.index, seed=4)
        shuffled = {t: shuffle_returns(df, order) for t, df in frames.items()}
        fake = bt.trend_mask(bt.build_panel(shuffled, shuffle_returns(bench, order), cfg), cfg)[
            0
        ].sum()
        assert real > 0 and fake >= 0
        assert fake < real, "shuffling left the trend structure intact"

    def test_it_is_deterministic_for_a_given_seed(self):
        frames, _ = synth(["AAA"], days=300)
        index = frames["AAA"].index
        a = shuffle_returns(frames["AAA"], shuffle_order(index, seed=5))
        b = shuffle_returns(frames["AAA"], shuffle_order(index, seed=5))
        c = shuffle_returns(frames["AAA"], shuffle_order(index, seed=6))
        assert np.allclose(a["close"], b["close"])
        assert not np.allclose(a["close"], c["close"])

    def test_a_short_frame_is_aligned_onto_the_shared_calendar(self):
        # The contract changed when the permutation became positional: every
        # frame is reindexed onto the shared calendar first, because that is the
        # only way two tickers can carry the same date's return at the same
        # position. A late lister is therefore defined across the whole window
        # in the shuffled world, which is a deliberate distortion of a world
        # that is already counterfactual.
        frames, _ = synth(["AAA"], days=300)
        order = shuffle_order(frames["AAA"].index, seed=1)
        late = frames["AAA"].iloc[150:]
        out = shuffle_returns(late, order)
        assert len(out) == 300
        assert out["close"].notna().all()
        assert (out["high"] >= out[["open", "close"]].max(axis=1) - 1e-9).all()

    def test_a_degenerate_calendar_is_returned_unchanged(self):
        frames, _ = synth(["AAA"], days=300)
        tiny = frames["AAA"].iloc[:2]
        out = shuffle_returns(tiny, shuffle_order(tiny.index, seed=1))
        assert np.allclose(out["close"], tiny["close"])

    def test_a_late_lister_keeps_its_co_movement(self):
        # The bug this replaced: placement by rank within each ticker's OWN
        # index meant a ticker missing sessions placed a given date's return at
        # a different position from one that had them all, and the offset
        # drifted. A twin missing its first hundred sessions correlated 0.04
        # with its full-history counterpart. Beta collapsed and every late
        # listing fell out of the shuffled universe.
        frames, bench = synth(["AAA"], days=600)
        order = shuffle_order(bench.index, seed=3)
        full = shuffle_returns(frames["AAA"], order)["close"].pct_change()
        late = shuffle_returns(frames["AAA"].iloc[150:], order)["close"].pct_change()
        paired = pd.concat([full, late], axis=1).dropna()
        paired = paired[paired.index >= frames["AAA"].index[150]]
        assert paired.corr().iloc[0, 1] > 0.7

    def test_beta_and_therefore_the_universe_survive_the_shuffle(self):
        # THE regression test. Per-ticker permutations destroy every ticker's
        # correlation with the benchmark, so every beta collapses towards zero
        # and the `beta >= 2` universe filter matches nothing. The first version
        # did exactly that and produced "0 tickers in the universe" and one
        # trade across six years.
        cfg = Config()
        frames, bench = synth([a + b for a in "ABCDEF" for b in "XYZ"], days=900)
        order = shuffle_order(bench.index, seed=9)
        shuffled = {t: shuffle_returns(df, order) for t, df in frames.items()}

        before = bt.universe_mask(bt.build_panel(frames, bench, cfg), cfg)
        after = bt.universe_mask(bt.build_panel(shuffled, shuffle_returns(bench, order), cfg), cfg)
        assert before.sum() > 0, "this fixture proves nothing with an empty universe"
        assert after.sum() > 0.5 * before.sum(), (
            "the shuffle emptied the universe, so beta did not survive it"
        )


class TestTheControlCanActuallyBeFilled:
    """Count matching is the property the whole design rests on.

    Under stops a trade needs a stop below and a target above. Gate 1 cannot
    fire without both, so the requirement never binds on the screens — but the
    control was drawing from the whole universe and having most of its picks
    discarded afterwards. A real run came back with 66 screen trades against 6
    controls, which is not a control, it is a rounding error with a name.
    """

    def test_both_arms_get_the_same_number_of_trades_under_stops(self):
        frames, bench = synth([a + b for a in "ABCDEFGHIJKL" for b in "XYZ"], days=1800)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames,
            bench,
            Config(trend_entry="confirmation", min_reward_risk=2.0, exit_rule="stops"),
            start=index[400].date(),
            end=index[-30].date(),
            replicates=0,
        )
        counts: dict[str, int] = {}
        for trade in report.trades:
            counts[trade.arm] = counts.get(trade.arm, 0) + 1
        assert counts.get("screens", 0) > 8, "this fixture proves nothing without trades"
        drawn = counts.get("random from universe", 0)
        assert drawn >= 0.8 * counts["screens"], (
            f"{counts['screens']} screen trades but only {drawn} controls: the control "
            "is being filtered after the draw instead of before it"
        )

    def test_the_restriction_does_not_apply_when_holding_to_the_horizon(self):
        # Without stops there is no geometry requirement, so the universe must
        # not be narrowed and earlier results must not silently change.
        frames, bench = synth(["AAA", "BBB", "CCC", "DDD"], days=900)
        cfg = Config(trend_entry="confirmation")
        panel = bt.build_panel(frames, bench, cfg)
        plain = bt.universe_mask(panel, cfg)
        index = next(iter(frames.values())).index
        report = bt.run(
            frames, bench, cfg, start=index[400].date(), end=index[-30].date(), replicates=0
        )
        assert plain.sum() > 0 and report.universe_days > 0


class TestTheVerdictDoesNotMisdiagnose:
    """Resolution and power are different failures and must not print alike."""

    def test_clearing_the_bar_without_enough_controls_says_so(self):
        builder = TestTheNullTest()
        null = builder._null(mean=99.9, median=99.9, trimmed=99.9, family=18, replicates=1000)
        assert not null.resolvable
        said = bt.verdict(null, 20)
        assert "cannot" in said and "resolve" in said
        assert "short of the" not in said, "a result past the bar was called short of it"

    def test_a_genuinely_short_result_is_still_called_short(self):
        builder = TestTheNullTest()
        null = builder._null(mean=90.0, median=90.0, trimmed=90.0, family=18, replicates=5000)
        assert "cannot" not in bt.verdict(null, 20)
