"""CLI behaviour.

Only the watchlist parser for now. `cli.py` is at zero coverage and filling that
in properly is its own session in the build plan; this file exists because the
parser changed to support the format `scripts/build_watchlist.py` writes, and a
change without a test is how the format quietly drifts apart from the reader.
"""

from __future__ import annotations

import pytest

from stocksignal.cli import _load_watchlist
from stocksignal.config import Config
from stocksignal.data import DataError, SyntheticSource, YFinanceSource, get_source


class TestLoadWatchlist:
    def test_no_path_falls_back_to_the_config_default(self):
        cfg = Config()
        assert _load_watchlist(None, cfg) == list(cfg.default_watchlist)

    def test_reads_one_ticker_a_line(self, tmp_path):
        path = tmp_path / "wl.txt"
        path.write_text("AAPL\nMSFT\nNVDA\n")
        assert _load_watchlist(path, Config()) == ["AAPL", "MSFT", "NVDA"]

    def test_skips_whole_line_comments_and_blanks(self, tmp_path):
        path = tmp_path / "wl.txt"
        path.write_text("# a heading\n\nAAPL\n\n# another\nMSFT\n")
        assert _load_watchlist(path, Config()) == ["AAPL", "MSFT"]

    def test_strips_inline_comments(self, tmp_path):
        # The generated watchlist puts the numbers that earned a symbol its
        # place right next to the symbol. Without this, the ticker would be
        # the whole line and every scan would fail on a lookup.
        path = tmp_path / "wl.txt"
        path.write_text("NVDA  # beta 2.41  $221.87  vol 121,849,613\nAMD # beta 3.19\n")
        assert _load_watchlist(path, Config()) == ["NVDA", "AMD"]

    def test_upper_cases_and_trims(self, tmp_path):
        path = tmp_path / "wl.txt"
        path.write_text("  nvda  \n\tamd\n")
        assert _load_watchlist(path, Config()) == ["NVDA", "AMD"]

    def test_an_empty_file_is_an_empty_list_not_an_error(self, tmp_path):
        path = tmp_path / "wl.txt"
        path.write_text("# everything got filtered out\n")
        assert _load_watchlist(path, Config()) == []


class TestSourceSelection:
    def test_the_default_is_synthetic_so_the_tool_always_runs(self):
        assert isinstance(get_source(), SyntheticSource)

    def test_live_still_means_yfinance_for_older_callers(self):
        assert isinstance(get_source(offline=False), YFinanceSource)

    def test_a_named_provider_wins_over_the_offline_flag(self):
        assert isinstance(get_source(offline=True, provider="yfinance"), YFinanceSource)

    def test_an_unknown_provider_names_the_valid_ones(self):
        with pytest.raises(DataError, match="synthetic, yfinance, alpaca"):
            get_source(provider="bloomberg")

    def test_alpaca_resolves_without_credentials_present(self, monkeypatch):
        # Constructing the source must not require a key. Credentials are
        # checked when a request is actually made, so `--source alpaca` fails
        # with a clear message rather than at import time.
        monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
        source = get_source(provider="alpaca")
        assert hasattr(source, "histories"), "the batch path is why we want Alpaca"
