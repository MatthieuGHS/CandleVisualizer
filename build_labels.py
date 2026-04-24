"""
Génère labels.csv à partir des trades déjà enregistrés dans exports/candles.xlsx.

Le fichier Excel n'est JAMAIS modifié — on ne fait que le lire.

Pour chaque trade :
  1. On identifie le jour du pic (high max) dans les bougies 1d stockées
  2. On refait un fetch 30m sur Binance dans une fenêtre ±1j autour de ce jour
  3. On prend la bougie 30m dont le high est le plus élevé → c'est le vrai ATH
  4. On écrit une ligne au format imposé par guide.md

Usage : python build_labels.py
"""
from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

import pandas as pd

from api.binance import BinanceAPI

EXCEL_PATH = Path("exports/candles.xlsx")
OUTPUT_CSV = Path("labels.csv")
TIMEFRAME = "30m"
EXCHANGE = "binance"

_KNOWN_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH")


def to_binance_pair(symbol: str) -> tuple[str, str]:
    """
    Retourne (binance_api_symbol, csv_symbol).
    Ex: 'SUI-USD'  -> ('SUIUSDT',  'SUI/USDT')
        'AVAXUSDT' -> ('AVAXUSDT', 'AVAX/USDT')
    """
    s = symbol.strip().upper()
    if "-" in s:
        base, _quote = s.split("-", 1)
    else:
        base = s
        for q in _KNOWN_QUOTES:
            if s.endswith(q) and len(s) > len(q):
                base = s[: -len(q)]
                break
    return f"{base}USDT", f"{base}/USDT"


def find_precise_ath(
    api: BinanceAPI,
    binance_symbol: str,
    rough_peak_day: pd.Timestamp,
) -> pd.Timestamp:
    """Refetch 30m autour du pic journalier et retourne l'open_time du vrai ATH."""
    start = (rough_peak_day - timedelta(days=1)).to_pydatetime()
    end = (rough_peak_day + timedelta(days=2)).to_pydatetime()
    df = api.fetch_candles(binance_symbol, "30m", start, end)
    if df.empty:
        raise RuntimeError(f"Fetch 30m vide pour {binance_symbol} autour de {rough_peak_day}")
    peak_row = df.loc[df["high"].idxmax()]
    return pd.Timestamp(peak_row["open_time"])


def main() -> None:
    meta = pd.read_excel(EXCEL_PATH, sheet_name="metadata")
    candles = pd.read_excel(EXCEL_PATH, sheet_name="candles")
    candles["open_time"] = pd.to_datetime(candles["open_time"])

    api = BinanceAPI()
    rows: list[dict[str, str]] = []

    for _, trade in meta.iterrows():
        sub = candles[candles["trade_id"] == trade["trade_id"]]
        rough_peak = sub.loc[sub["high"].idxmax(), "open_time"]
        binance_sym, csv_sym = to_binance_pair(trade["symbol"])

        print(f"[{trade['symbol']:10s}] pic jour ≈ {rough_peak.date()} → fetch 30m {binance_sym}…", end=" ", flush=True)
        try:
            ath = find_precise_ath(api, binance_sym, rough_peak)
            t_ath = ath.strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"ATH = {t_ath}")
            rows.append({
                "symbol": csv_sym,
                "timeframe": TIMEFRAME,
                "t_ath": t_ath,
                "exchange": EXCHANGE,
            })
        except Exception as e:
            print(f"ÉCHEC ({e})")

    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "timeframe", "t_ath", "exchange"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ {len(rows)} lignes écrites dans {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
