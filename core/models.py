from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradeMetadata:
    trade_id: str
    label: str
    exchange: str
    symbol: str
    interval: str
    start_utc: datetime
    end_utc: datetime
    nb_candles: int

    def to_row(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "label": self.label,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "interval": self.interval,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "nb_candles": self.nb_candles,
        }


METADATA_COLUMNS = [
    "trade_id",
    "label",
    "exchange",
    "symbol",
    "interval",
    "start_utc",
    "end_utc",
    "nb_candles",
]

CANDLES_COLUMNS = [
    "trade_id",
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "pct_change",
]
