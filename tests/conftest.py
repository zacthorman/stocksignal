"""Shared test fixtures.

The pattern to steal from this file: build price frames by hand with the exact
shape a screen is supposed to catch. A test that says "here is a chart that is
obviously an uptrend, so the trend screen must pass it" is readable by someone
who does not know Python, and it fails for exactly one reason.
"""

from __future__ import annotations

import pandas as pd
import pytest

from helpers import make_bars
from stocksignal.config import Config


@pytest.fixture
def cfg() -> Config:
    """Short windows so fixtures stay small and fast."""
    return Config(sma_fast=5, sma_slow=10, min_history_days=20, avg_volume_window=10)


@pytest.fixture
def rising_bars() -> pd.DataFrame:
    """A clean uptrend: price climbs every session."""
    return make_bars([100 + i * 1.5 for i in range(80)])


@pytest.fixture
def falling_bars() -> pd.DataFrame:
    """A clean downtrend."""
    return make_bars([220 - i * 1.5 for i in range(80)])


@pytest.fixture
def flat_bars() -> pd.DataFrame:
    """Sideways chop: the averages sit on top of each other."""
    return make_bars([100 + (1 if i % 2 else -1) * 0.2 for i in range(80)])
