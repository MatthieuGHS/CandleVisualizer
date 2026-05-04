"""
Génération de `labels.csv` à partir des bougies stockées localement.

Plus de refetch Binance : on lit directement le fichier local pertinent à
l'exchange du trade.
- Trade Binance → bougie 30m au plus haut high → ligne `30m, binance`
- Trade Coinbase → bougie 15m au plus haut high → ligne `15m, coinbase`

Format CSV (option « reflète la réalité ») : `timeframe` et `exchange` peuvent
varier d'une ligne à l'autre selon le trade.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import pandas as pd


# Override possible via env var pour persistance (Railway volume, etc.)
_DEFAULT_LABELS = Path(__file__).resolve().parent.parent / "labels.csv"
LABELS_PATH = Path(os.environ.get("LABELS_PATH") or _DEFAULT_LABELS)
LABELS_FIELDS = ["symbol", "timeframe", "t_ath", "exchange"]

_KNOWN_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH")

# Pour chaque exchange : intervalle de référence pour le label (le plus fin
# pratique disponible sur cet exchange).
EXCHANGE_LABEL_INTERVAL = {
    "Binance": "30m",
    "Coinbase": "15m",
}


def normalize_symbol_for_csv(symbol: str) -> str:
    """`BTCUSDT` → `BTC/USDT`, `BTC-USD` → `BTC/USD`. Reflète le quote réel."""
    s = symbol.strip().upper()
    if "-" in s:
        base, quote = s.split("-", 1)
        return f"{base}/{quote}"
    for q in _KNOWN_QUOTES:
        if s.endswith(q) and len(s) > len(q):
            base = s[: -len(q)]
            return f"{base}/{q}"
    return s


def denormalize_symbol_for_api(csv_symbol: str, exchange: str) -> str:
    """`BTC/USDT` + Binance → `BTCUSDT`. `BTC/USD` + Coinbase → `BTC-USD`.

    Inverse de `normalize_symbol_for_csv` selon les conventions de chaque exchange.
    """
    s = csv_symbol.strip().upper()
    if "/" not in s:
        return s
    base, quote = s.split("/", 1)
    ex = exchange.strip().lower()
    if ex == "binance":
        return f"{base}{quote}"
    if ex == "coinbase":
        return f"{base}-{quote}"
    return s


def compute_label_from_local(
    trade_meta: dict | pd.Series,
    candles_for_trade: pd.DataFrame,
) -> dict:
    """Calcule la ligne CSV depuis les bougies locales du bon intervalle.

    Args:
        trade_meta : ligne de metadata (dict ou Series) avec `symbol` et `exchange`
        candles_for_trade : bougies du trade au timeframe de référence
            (30m pour Binance, 15m pour Coinbase). On prend la bougie au plus
            haut `high`.

    Returns:
        dict avec les 4 colonnes du CSV.
    """
    if isinstance(trade_meta, pd.Series):
        meta = trade_meta.to_dict()
    else:
        meta = dict(trade_meta)

    exchange = str(meta.get("exchange", ""))
    if exchange not in EXCHANGE_LABEL_INTERVAL:
        raise ValueError(f"Exchange non supporté pour labels : {exchange!r}")
    timeframe = EXCHANGE_LABEL_INTERVAL[exchange]

    if candles_for_trade.empty:
        raise ValueError(
            f"Aucune bougie {timeframe} trouvée pour le trade "
            f"{meta.get('trade_id')} ({exchange})."
        )

    peak = candles_for_trade.loc[candles_for_trade["high"].idxmax()]
    t_ath = pd.Timestamp(peak["open_time"]).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "symbol": normalize_symbol_for_csv(str(meta.get("symbol", ""))),
        "timeframe": timeframe,
        "t_ath": t_ath,
        "exchange": exchange.lower(),
    }


def append_label(row: dict) -> None:
    """Ajoute une ligne à labels.csv. Crée le fichier avec en-tête si absent."""
    write_header = not LABELS_PATH.exists() or LABELS_PATH.stat().st_size == 0
    with LABELS_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LABELS_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def rebuild_labels(rows: list[dict]) -> None:
    """Réécrit labels.csv à zéro avec les lignes fournies."""
    with LABELS_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LABELS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def rebuild_labels_from_archive() -> int:
    """Régénère labels.csv depuis l'archive multi-intervalles locale.

    Pour chaque trade : lit les bougies du timeframe de référence de son exchange
    (30m pour Binance, 15m pour Coinbase) et calcule la ligne CSV.

    Returns:
        Nombre de lignes écrites.
    """
    from .excel_io import EXCEL_PATHS, _read_archive_file, list_trades

    meta = list_trades()
    if meta.empty:
        rebuild_labels([])
        return 0

    # Cache des bougies par intervalle pour éviter de rouvrir les fichiers à chaque trade
    candles_cache: dict = {}

    rows: list[dict] = []
    for _, trade in meta.iterrows():
        exchange = str(trade["exchange"])
        if exchange not in EXCHANGE_LABEL_INTERVAL:
            continue
        iv = EXCHANGE_LABEL_INTERVAL[exchange]
        if iv not in candles_cache:
            _, candles_cache[iv] = _read_archive_file(EXCEL_PATHS[iv])
        all_candles = candles_cache[iv]
        sub = all_candles[all_candles["trade_id"] == trade["trade_id"]]
        if sub.empty:
            continue
        try:
            rows.append(compute_label_from_local(trade, sub))
        except ValueError:
            continue

    rebuild_labels(rows)
    return len(rows)


# --------------------------------------------------------------------------- #
# Import — parsing labels.csv uploadé
# --------------------------------------------------------------------------- #


def parse_uploaded_labels(uploaded_csv) -> pd.DataFrame:
    """Parse un labels.csv uploadé et valide ses colonnes.

    Args:
        uploaded_csv : file-like (Dash dcc.Upload) ou bytes

    Returns:
        DataFrame avec les 4 colonnes attendues.

    Raises:
        ValueError si le fichier est illisible ou si les colonnes manquent.
    """
    try:
        df = pd.read_csv(uploaded_csv)
    except Exception as e:
        raise ValueError(f"Lecture impossible du labels.csv : {e}") from e

    missing = [c for c in LABELS_FIELDS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans labels.csv : {missing}. "
            f"Attendues : {LABELS_FIELDS}"
        )
    return df[LABELS_FIELDS].copy()


def lookup_label_row(
    labels_df: pd.DataFrame,
    symbol: str,
    exchange: str,
    start_utc,
    end_utc,
) -> dict | None:
    """Cherche dans `labels_df` la ligne correspondant à un trade.

    Match par (symbol normalisé, exchange.lower()) et `t_ath` ∈ [start_utc, end_utc].

    Returns:
        dict de la ligne matchée, ou None si aucune ne correspond.
    """
    if labels_df.empty:
        return None

    target_symbol = normalize_symbol_for_csv(symbol)
    target_exchange = exchange.lower()

    candidates = labels_df[
        (labels_df["symbol"].astype(str) == target_symbol)
        & (labels_df["exchange"].astype(str).str.lower() == target_exchange)
    ]
    if candidates.empty:
        return None

    start_ts = pd.Timestamp(start_utc)
    end_ts = pd.Timestamp(end_utc)
    in_window = []
    for _, row in candidates.iterrows():
        try:
            t_ath = pd.Timestamp(row["t_ath"])
            if t_ath.tzinfo is not None:
                t_ath = t_ath.tz_convert("UTC").tz_localize(None)
        except Exception:
            continue
        if start_ts <= t_ath <= end_ts:
            in_window.append(row.to_dict())

    if not in_window:
        return None
    # En cas de plusieurs matches : prendre le premier (cas rare)
    return in_window[0]


def labels_csv_bytes() -> bytes | None:
    """Renvoie le contenu de labels.csv en bytes pour inclure dans le ZIP."""
    if not LABELS_PATH.exists():
        return None
    return LABELS_PATH.read_bytes()
