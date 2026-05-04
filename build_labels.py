"""
Régénère labels.csv à partir des trades de l'archive multi-intervalles locale.

Lit `candles_30m.xlsx` pour les trades Binance et `candles_15m.xlsx` pour les
trades Coinbase, sans refetch API.

L'app fait déjà cette synchro automatiquement à chaque ajout/suppression. Ce
script sert de filet de secours si labels.csv a divergé des Excel (édition
manuelle, copie/restore, etc.).

Aucun fichier Excel n'est modifié — lecture seule.

Usage : python build_labels.py
"""
from __future__ import annotations

from core.excel_io import list_trades
from core.labels_io import LABELS_PATH, rebuild_labels_from_archive


def main() -> None:
    meta = list_trades()
    if meta.empty:
        print("Aucun trade dans l'archive — labels.csv non généré.")
        return

    n = rebuild_labels_from_archive()
    print(f"✓ {n} lignes écrites dans {LABELS_PATH}")


if __name__ == "__main__":
    main()
