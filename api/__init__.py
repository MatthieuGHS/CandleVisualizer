from __future__ import annotations

from .base import ExchangeAPI
from .binance import BinanceAPI

AVAILABLE_APIS: dict[str, ExchangeAPI] = {
    "Binance": BinanceAPI(),
}

__all__ = ["ExchangeAPI", "BinanceAPI", "AVAILABLE_APIS"]
