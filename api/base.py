from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import pandas as pd


CANDLE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


class ExchangeAPI(ABC):
    name: str
    supported_intervals: list[str]

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return a DataFrame with columns defined in CANDLE_COLUMNS.

        Timestamps are timezone-naive UTC datetimes.
        """

    @abstractmethod
    def interval_to_timedelta(self, interval: str) -> timedelta:
        """Convert an interval string (e.g. '15m', '1h') to a timedelta."""
