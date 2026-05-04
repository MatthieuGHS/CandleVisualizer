"""
Archive multi-intervalles synchronisée pour CandleVisualizer.

Un trade Binance est écrit dans 4 fichiers : `candles_{30m,1h,4h,1d}.xlsx`.
Un trade Coinbase est écrit dans 4 fichiers : `candles_{15m,1h,6h,1d}.xlsx`.
Les fichiers `1h` et `1d` peuvent contenir des trades des deux exchanges.

Toutes les mutations passent par `_atomic_write_all` : écriture en `.tmp` × N
puis `replace`, avec cleanup `finally` des `.tmp` orphelins.
"""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import CANDLES_COLUMNS, METADATA_COLUMNS, TradeMetadata


# Override possible via env var pour pointer vers un volume persistant
# (Railway, Fly, Render, etc.). Défaut : `<repo>/exports/`.
_DEFAULT_EXPORTS = Path(__file__).resolve().parent.parent / "exports"
EXPORTS_DIR = Path(os.environ.get("EXPORTS_DIR") or _DEFAULT_EXPORTS)

# Tous les intervalles potentiellement présents (union des export_intervals des APIs)
ALL_INTERVALS = ("15m", "30m", "1h", "4h", "6h", "1d")
EXCEL_PATHS = {iv: EXPORTS_DIR / f"candles_{iv}.xlsx" for iv in ALL_INTERVALS}

METADATA_SHEET = "metadata"
CANDLES_SHEET = "candles"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def new_trade_id() -> str:
    return uuid.uuid4().hex[:12]


def ensure_exports_dir() -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def _empty_metadata() -> pd.DataFrame:
    return pd.DataFrame(columns=METADATA_COLUMNS)


def _empty_candles() -> pd.DataFrame:
    return pd.DataFrame(columns=CANDLES_COLUMNS)


def _normalize_metadata(meta: pd.DataFrame) -> pd.DataFrame:
    for col in METADATA_COLUMNS:
        if col not in meta.columns:
            meta[col] = pd.NA
    return meta[METADATA_COLUMNS].copy().reset_index(drop=True)


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    for col in CANDLES_COLUMNS:
        if col not in candles.columns:
            candles[col] = pd.NA
    return candles[CANDLES_COLUMNS].copy().reset_index(drop=True)


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #


def _read_archive_file(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not path.exists():
        return _empty_metadata(), _empty_candles()
    sheets = pd.read_excel(path, sheet_name=None)
    meta = sheets.get(METADATA_SHEET, _empty_metadata())
    candles = sheets.get(CANDLES_SHEET, _empty_candles())
    return _normalize_metadata(meta), _normalize_candles(candles)


def read_all_archives() -> dict:
    """Renvoie `{interval: (metadata, candles)}` pour les 6 fichiers possibles.

    Les fichiers absents renvoient des DataFrames vides.
    """
    return {iv: _read_archive_file(EXCEL_PATHS[iv]) for iv in ALL_INTERVALS}


def list_trades() -> pd.DataFrame:
    """Liste dédoublonnée des trades à travers tous les fichiers.

    Un trade apparaît dans 4 fichiers (selon son exchange). On le compte une seule
    fois en dédoublonnant par `trade_id`. L'ordre est celui de la première
    occurrence trouvée parmi `ALL_INTERVALS` puis stable.
    """
    archives = read_all_archives()
    frames = [meta for meta, _ in archives.values() if not meta.empty]
    if not frames:
        return _empty_metadata()
    union = pd.concat(frames, ignore_index=True)
    union = union.drop_duplicates(subset=["trade_id"], keep="first").reset_index(drop=True)
    return union


def get_trade_candles(trade_id: str, interval: str) -> pd.DataFrame:
    if interval not in ALL_INTERVALS:
        raise ValueError(f"Intervalle non supporté : {interval}")
    _, candles = _read_archive_file(EXCEL_PATHS[interval])
    return candles[candles["trade_id"] == trade_id].reset_index(drop=True)


def get_status() -> dict:
    """Résumé de l'archive : nombre de trades distincts et fichiers présents."""
    meta = list_trades()
    existing = [iv for iv in ALL_INTERVALS if EXCEL_PATHS[iv].exists()]
    return {
        "dir": str(EXPORTS_DIR),
        "files": existing,
        "nb_trades": len(meta),
    }


# --------------------------------------------------------------------------- #
# Atomic write
# --------------------------------------------------------------------------- #


def _atomic_write(targets: dict) -> None:
    """Écrit `{path: (meta_df, candles_df)}` en mode quasi-atomique.

    Phase 1 : tout est écrit en `.tmp` (si une écriture plante, rien n'a touché
    aux vrais fichiers). Phase 2 : `replace()` chaque tmp vers son nom final.
    `finally` nettoie les `.tmp` orphelins en cas d'échec.
    """
    ensure_exports_dir()
    tmp_paths: list[tuple[Path, Path]] = []
    try:
        for final, (meta, candles) in targets.items():
            tmp = final.with_name(final.name + ".tmp")
            with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
                meta.to_excel(writer, sheet_name=METADATA_SHEET, index=False)
                candles.to_excel(writer, sheet_name=CANDLES_SHEET, index=False)
            tmp_paths.append((tmp, final))
        for tmp, final in tmp_paths:
            tmp.replace(final)
    finally:
        for tmp, _ in tmp_paths:
            tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #


def append_trade(
    label: str,
    exchange: str,
    symbol: str,
    candles_per_interval: dict,
    start_utc: datetime,
    end_utc: datetime,
) -> TradeMetadata:
    """Écrit un trade dans les 4 fichiers correspondants à son exchange.

    Args:
        label : libellé du trade
        exchange : "Binance" ou "Coinbase"
        symbol : ticker réel (BTCUSDT, BTC-USD, ...)
        candles_per_interval : `{interval: candles_df}` avec exactement 4 entrées
        start_utc / end_utc : bornes de la plage demandée

    Returns:
        TradeMetadata avec le `trade_id` généré et `interval` = première clé du dict
        (par convention le plus fin — peu utilisé en aval, kept for compat).
    """
    if not candles_per_interval:
        raise ValueError("candles_per_interval ne peut pas être vide")

    archives = read_all_archives()
    trade_id = new_trade_id()
    nb_candles_total = sum(len(c) for c in candles_per_interval.values())

    targets = {}
    for iv, sub_candles in candles_per_interval.items():
        if iv not in ALL_INTERVALS:
            raise ValueError(f"Intervalle inconnu : {iv}")
        if sub_candles.empty:
            raise ValueError(f"Bougies vides pour l'intervalle {iv}")

        local_meta, local_candles = archives[iv]

        meta_row = TradeMetadata(
            trade_id=trade_id,
            label=label,
            exchange=exchange,
            symbol=symbol,
            interval=iv,
            start_utc=start_utc,
            end_utc=end_utc,
            nb_candles=len(sub_candles),
        ).to_row()

        new_meta = pd.concat(
            [local_meta, pd.DataFrame([meta_row], columns=METADATA_COLUMNS)],
            ignore_index=True,
        )

        new_c = sub_candles.copy()
        new_c.insert(0, "trade_id", trade_id)
        new_c["pct_change"] = (
            (new_c["close"] - new_c["open"]) / new_c["open"] * 100
        ).round(4)
        new_c = new_c[CANDLES_COLUMNS]

        new_candles = pd.concat([local_candles, new_c], ignore_index=True)
        targets[EXCEL_PATHS[iv]] = (new_meta, new_candles)

    _atomic_write(targets)

    # Returned metadata reflects the first interval (canonical for the trade)
    first_iv = next(iter(candles_per_interval.keys()))
    return TradeMetadata(
        trade_id=trade_id,
        label=label,
        exchange=exchange,
        symbol=symbol,
        interval=first_iv,
        start_utc=start_utc,
        end_utc=end_utc,
        nb_candles=nb_candles_total,
    )


def delete_trade(trade_id: str) -> int:
    """Supprime un trade de tous les fichiers où il apparaît.

    Returns:
        Nombre de trades distincts restants après suppression.
    """
    archives = read_all_archives()
    targets = {}
    for iv in ALL_INTERVALS:
        meta, candles = archives[iv]
        if meta.empty and candles.empty:
            continue
        new_meta = meta[meta["trade_id"] != trade_id].reset_index(drop=True)
        new_candles = candles[candles["trade_id"] != trade_id].reset_index(drop=True)
        # On n'écrit que si le fichier existe déjà (sinon pas la peine d'en créer un vide)
        if EXCEL_PATHS[iv].exists() or not new_meta.empty:
            targets[EXCEL_PATHS[iv]] = (new_meta, new_candles)

    if targets:
        _atomic_write(targets)
    return len(list_trades())


# --------------------------------------------------------------------------- #
# Build en mémoire (pour la section reconstruction depuis CSV — sans I/O disque)
# --------------------------------------------------------------------------- #


def build_archives_in_memory(trades_per_interval: dict) -> dict:
    """Construit les xlsx bytes pour chaque intervalle sans toucher au disque.

    Args:
        trades_per_interval : `{interval: [(meta_row_dict, candles_df), ...]}`

    Returns:
        `{interval: bytes}` — un blob xlsx par intervalle non vide.
    """
    out: dict = {}
    for iv, items in trades_per_interval.items():
        if not items:
            continue
        metas = pd.DataFrame(
            [m for m, _ in items], columns=METADATA_COLUMNS
        )
        candles = pd.concat(
            [c for _, c in items], ignore_index=True
        )[CANDLES_COLUMNS]
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            metas.to_excel(writer, sheet_name=METADATA_SHEET, index=False)
            candles.to_excel(writer, sheet_name=CANDLES_SHEET, index=False)
        out[iv] = buf.getvalue()
    return out


# --------------------------------------------------------------------------- #
# Téléchargement (zip des fichiers existants + labels.csv)
# --------------------------------------------------------------------------- #


def archive_zip_bytes(extra_files: dict | None = None) -> bytes | None:
    """ZIP en mémoire des fichiers Excel existants.

    Args:
        extra_files : `{arcname: bytes}` à inclure (ex: `labels.csv`)
    """
    existing = [iv for iv in ALL_INTERVALS if EXCEL_PATHS[iv].exists()]
    if not existing and not extra_files:
        return None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for iv in existing:
            path = EXCEL_PATHS[iv]
            zf.write(path, arcname=path.name)
        if extra_files:
            for arcname, data in extra_files.items():
                zf.writestr(arcname, data)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Import — parsing et validation
# --------------------------------------------------------------------------- #


# Configurations valides : couples (exchange, intervalles) attendus à l'import
EXCHANGE_INTERVAL_SETS = {
    "Binance": frozenset(("30m", "1h", "4h", "1d")),
    "Coinbase": frozenset(("15m", "1h", "6h", "1d")),
}


def parse_uploaded_archives(uploaded_xlsx: list) -> dict:
    """Parse 4 xlsx uploadés. Auto-détection du slot via meta['interval'].

    Args:
        uploaded_xlsx : liste de file-like (ou bytes) — 4 fichiers exactement

    Returns:
        `{interval: (meta_df, candles_df)}`. Validé sur cohérence des trade_id et
        sur le fait que les 4 intervals correspondent à un exchange connu.

    Raises:
        ValueError sur toute incohérence détectée.
    """
    if len(uploaded_xlsx) != 4:
        raise ValueError(
            f"4 fichiers Excel attendus (1 par intervalle), {len(uploaded_xlsx)} fournis."
        )

    by_interval: dict = {}
    for f in uploaded_xlsx:
        name = getattr(f, "name", "<fichier>")
        try:
            sheets = pd.read_excel(f, sheet_name=None, engine="openpyxl")
        except Exception as e:
            raise ValueError(f"Lecture impossible de {name} : {e}") from e

        meta = sheets.get(METADATA_SHEET)
        candles = sheets.get(CANDLES_SHEET)
        if meta is None or candles is None:
            raise ValueError(
                f"{name} : feuilles 'metadata' et 'candles' attendues."
            )
        if "interval" not in meta.columns or meta["interval"].dropna().empty:
            raise ValueError(
                f"{name} : colonne 'interval' absente ou vide — impossible "
                "d'auto-détecter le slot. L'archive doit contenir au moins un trade."
            )
        intervals = meta["interval"].dropna().astype(str).unique()
        if len(intervals) > 1:
            raise ValueError(
                f"{name} contient plusieurs intervalles : {sorted(intervals)}."
            )
        iv = intervals[0]
        if iv not in ALL_INTERVALS:
            raise ValueError(
                f"{name} : intervalle '{iv}' non supporté (attendus : {ALL_INTERVALS})."
            )
        if iv in by_interval:
            raise ValueError(f"Deux fichiers fournis pour l'intervalle '{iv}'.")
        by_interval[iv] = (_normalize_metadata(meta), _normalize_candles(candles))

    # Vérifier que les 4 intervalles correspondent à une config exchange connue
    interval_set = frozenset(by_interval.keys())
    matching_exchanges = [
        ex for ex, ivs in EXCHANGE_INTERVAL_SETS.items() if ivs == interval_set
    ]
    if not matching_exchanges:
        raise ValueError(
            f"Les 4 intervalles {sorted(interval_set)} ne correspondent à aucun "
            f"exchange connu. Attendu : {dict(EXCHANGE_INTERVAL_SETS)}"
        )

    # Cohérence des trade_id entre les 4 fichiers
    trade_id_sets = {
        iv: set(meta["trade_id"].dropna().astype(str))
        for iv, (meta, _) in by_interval.items()
    }
    ref_iv = next(iter(by_interval))
    ref = trade_id_sets[ref_iv]
    for iv, ids in trade_id_sets.items():
        if ids != ref:
            extra = sorted(ids - ref)[:3]
            missing = sorted(ref - ids)[:3]
            details = []
            if extra:
                details.append(f"présents dans {iv} mais pas dans {ref_iv} : {extra}")
            if missing:
                details.append(f"absents de {iv} : {missing}")
            raise ValueError(
                "Les trade_id ne sont pas cohérents entre les 4 fichiers "
                f"({'; '.join(details)})."
            )

    return by_interval


def add_imported_trade(trade_id: str, imported: dict) -> tuple[str, str]:
    """Copie un trade unique de l'archive importée dans les 4 fichiers locaux
    correspondant à son exchange.

    Régénère le `trade_id`. Conserve le symbol réel (pas de renumérotation).

    Returns:
        (new_trade_id, exchange)
    """
    new_trade_id_str = new_trade_id()
    archives = read_all_archives()

    targets = {}
    exchange = None
    for iv, (imp_meta, imp_candles) in imported.items():
        src_rows = imp_meta[imp_meta["trade_id"] == trade_id]
        if src_rows.empty:
            raise ValueError(
                f"trade_id {trade_id} introuvable dans l'archive importée ({iv})."
            )
        src_row = src_rows.iloc[0].to_dict()
        if exchange is None:
            exchange = str(src_row.get("exchange", ""))
        new_row = {col: src_row.get(col) for col in METADATA_COLUMNS}
        new_row["trade_id"] = new_trade_id_str

        local_meta, local_candles = archives[iv]
        new_meta = pd.concat(
            [local_meta, pd.DataFrame([new_row], columns=METADATA_COLUMNS)],
            ignore_index=True,
        )

        sub = imp_candles[imp_candles["trade_id"] == trade_id].copy()
        sub["trade_id"] = new_trade_id_str
        sub = sub[CANDLES_COLUMNS]
        new_candles = pd.concat([local_candles, sub], ignore_index=True)

        targets[EXCEL_PATHS[iv]] = (new_meta, new_candles)

    _atomic_write(targets)
    return new_trade_id_str, exchange or ""
