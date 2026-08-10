"""Concrete price sources.

`data.py` owns the `PriceSource` protocol and the two sources the scaffold
shipped with. Anything added later lives here, so the protocol stays the
interesting file and the providers stay interchangeable.
"""

from stocksignal.sources.alpaca import AlpacaSource

__all__ = ["AlpacaSource"]
