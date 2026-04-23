from __future__ import annotations

from .base import ExchangeAPI
from .binance import BinanceAPI
from .coinbase import CoinbaseAPI

AVAILABLE_APIS: dict[str, ExchangeAPI] = {
    "Binance": BinanceAPI(),
    "Coinbase": CoinbaseAPI(),
}

__all__ = ["ExchangeAPI", "BinanceAPI", "CoinbaseAPI", "AVAILABLE_APIS"]
