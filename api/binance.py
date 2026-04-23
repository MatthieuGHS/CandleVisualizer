from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from .base import CANDLE_COLUMNS, ExchangeAPI


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000


INTERVAL_MAP: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "1w": timedelta(weeks=1),
    # Approximation for month — Binance handles the real alignment server-side.
    "1M": timedelta(days=30),
}


class BinanceAPI(ExchangeAPI):
    name = "Binance"
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

        start_ms = _to_ms(start)
        end_ms = _to_ms(end)

        frames: list[pd.DataFrame] = []
        cursor = start_ms

        while cursor < end_ms:
            batch = self._fetch_batch(symbol, interval, cursor, end_ms)
            if batch.empty:
                break
            frames.append(batch)
            # Advance cursor past the last open_time in this batch to avoid duplicates.
            last_open_ms = int(batch["_open_ms"].iloc[-1])
            next_cursor = last_open_ms + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < MAX_LIMIT:
                break
            time.sleep(0.1)

        if not frames:
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset=["_open_ms"]).sort_values("_open_ms")
        df = df.drop(columns=["_open_ms"]).reset_index(drop=True)
        return df[CANDLE_COLUMNS]

    def _fetch_batch(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> pd.DataFrame:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }
        response = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
        if response.status_code != 200:
            try:
                payload = response.json()
                msg = payload.get("msg", response.text)
            except Exception:
                msg = response.text
            raise RuntimeError(f"Binance API error ({response.status_code}): {msg}")

        raw = response.json()
        if not raw:
            return pd.DataFrame(columns=[*CANDLE_COLUMNS, "_open_ms"])

        df = pd.DataFrame(
            raw,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )
        df["_open_ms"] = df["open_time"].astype("int64")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df[[*CANDLE_COLUMNS, "_open_ms"]]


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
