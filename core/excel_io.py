from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import CANDLES_COLUMNS, METADATA_COLUMNS, TradeMetadata


EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"
EXCEL_PATH = EXPORTS_DIR / "candles.xlsx"

METADATA_SHEET = "metadata"
CANDLES_SHEET = "candles"


def new_trade_id() -> str:
    return uuid.uuid4().hex[:12]


def ensure_exports_dir() -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def read_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (metadata_df, candles_df). Empty DataFrames if file does not exist."""
    if not EXCEL_PATH.exists():
        return (
            pd.DataFrame(columns=METADATA_COLUMNS),
            pd.DataFrame(columns=CANDLES_COLUMNS),
        )
    meta = pd.read_excel(EXCEL_PATH, sheet_name=METADATA_SHEET)
    candles = pd.read_excel(EXCEL_PATH, sheet_name=CANDLES_SHEET)
    return meta, candles


def append_trade(
    label: str,
    exchange: str,
    symbol: str,
    interval: str,
    candles: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
) -> TradeMetadata:
    """Append a new trade to the Excel file, creating it if needed."""
    if candles.empty:
        raise ValueError("Cannot append a trade with no candles")

    ensure_exports_dir()

    meta_df, candles_df = read_all()

    trade_id = new_trade_id()
    trade_meta = TradeMetadata(
        trade_id=trade_id,
        label=label,
        exchange=exchange,
        symbol=symbol,
        interval=interval,
        start_utc=start_utc,
        end_utc=end_utc,
        nb_candles=len(candles),
    )

    new_meta_row = pd.DataFrame([trade_meta.to_row()], columns=METADATA_COLUMNS)
    meta_df = pd.concat([meta_df, new_meta_row], ignore_index=True)

    new_candles = candles.copy()
    new_candles.insert(0, "trade_id", trade_id)
    new_candles["pct_change"] = ((new_candles["close"] - new_candles["open"]) / new_candles["open"] * 100).round(4)
    new_candles = new_candles[CANDLES_COLUMNS]
    candles_df = pd.concat([candles_df, new_candles], ignore_index=True)

    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl", mode="w") as writer:
        meta_df.to_excel(writer, sheet_name=METADATA_SHEET, index=False)
        candles_df.to_excel(writer, sheet_name=CANDLES_SHEET, index=False)

    return trade_meta


def get_status() -> dict:
    """Return a summary of what's currently in the Excel file."""
    meta_df, _ = read_all()
    return {
        "path": str(EXCEL_PATH),
        "exists": EXCEL_PATH.exists(),
        "nb_trades": len(meta_df),
    }


def delete_trade(trade_id: str) -> int:
    """Remove a trade (metadata + candles) from the Excel file. Returns remaining trade count."""
    meta_df, candles_df = read_all()
    if meta_df.empty:
        return 0

    meta_df = meta_df[meta_df["trade_id"] != trade_id].reset_index(drop=True)
    candles_df = candles_df[candles_df["trade_id"] != trade_id].reset_index(drop=True)

    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl", mode="w") as writer:
        meta_df.to_excel(writer, sheet_name=METADATA_SHEET, index=False)
        candles_df.to_excel(writer, sheet_name=CANDLES_SHEET, index=False)

    return len(meta_df)
