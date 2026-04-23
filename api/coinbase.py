from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from .base import CANDLE_COLUMNS, ExchangeAPI


COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
MAX_CANDLES = 300


INTERVAL_MAP: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}

GRANULARITY_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


class CoinbaseAPI(ExchangeAPI):
    name = "Coinbase"
    supported_intervals = list(INTERVAL_MAP.keys())

    def interval_to_timedelta(self, interval: str) -> timedelta:
        if interval not in INTERVAL_MAP:
            raise ValueError(f"Unsupported interval: {interval}")
        return INTERVAL_MAP[interval]

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if interval not in INTERVAL_MAP:
            raise ValueError(f"Unsupported interval: {interval}")
        if start >= end:
            raise ValueError("start must be strictly before end")

        product_id = _normalize_symbol(symbol)
        granularity = GRANULARITY_SECONDS[interval]
        step = INTERVAL_MAP[interval]
        window = step * MAX_CANDLES  # max duration per request

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        frames: list[pd.DataFrame] = []
        cursor = start
        while cursor < end:
            batch_end = min(cursor + window, end)
            batch = self._fetch_batch(product_id, granularity, cursor, batch_end)
            if not batch.empty:
                frames.append(batch)
            cursor = batch_end
            time.sleep(0.2)

        if not frames:
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time")
        df = df.reset_index(drop=True)
        return df[CANDLE_COLUMNS]

    def _fetch_batch(
        self,
        product_id: str,
        granularity: int,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "granularity": granularity,
        }
        url = COINBASE_CANDLES_URL.format(product_id=product_id)
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            try:
                payload = response.json()
                msg = payload.get("message", response.text)
            except Exception:
                msg = response.text
            raise RuntimeError(f"Coinbase API error ({response.status_code}): {msg}")

        raw = response.json()
        if not raw:
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        # Coinbase returns [time, low, high, open, close, volume] — order differs from Binance.
        df = pd.DataFrame(
            raw,
            columns=["time_s", "low", "high", "open", "close", "volume"],
        )
        df["open_time"] = (
            pd.to_datetime(df["time_s"], unit="s", utc=True)
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
        )
        df["close_time"] = (
            df["open_time"]
            + pd.to_timedelta(granularity, unit="s")
            - pd.to_timedelta(1, unit="ms")
        )
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df[CANDLE_COLUMNS]


def _normalize_symbol(symbol: str) -> str:
    """Coinbase expects 'BTC-USD'. Accept 'BTCUSD', 'BTCUSDT', 'btc-usd', etc."""
    s = symbol.strip().upper()
    if "-" in s:
        return s
    for quote in ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}-{quote}"
    return s
