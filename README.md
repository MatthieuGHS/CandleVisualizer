# CandleVisualizer

Application Dash locale pour récupérer, visualiser et archiver des chandeliers crypto. Chaque trade chargé peut être empilé dans un **unique** fichier Excel réutilisable — suffisant pour reconstruire n'importe quel graphique plus tard, sans refaire d'appel API.

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
python app.py
```

Puis ouvrir **http://127.0.0.1:8050** dans le navigateur. `Ctrl+C` pour arrêter.

---

## Utilisation

### 1. Charger des chandelles (section « Configuration »)

| Champ | Description |
|---|---|
| **API** | Exchange source (Binance par défaut ; architecture extensible, voir plus bas). |
| **Symbol** | Paire de trading — ex. `BTCUSDT`, `ETHUSDT`, `SOLUSDT`. Majuscules forcées. |
| **Interval** | Un des intervalles supportés par l'exchange (`1m`, `5m`, `15m`, `1h`, `4h`, `1d`, `1w`, etc.). |
| **Début / Fin (UTC)** | Bornes de la plage à récupérer. Le DatePicker sélectionne la date, le champ texte adjacent l'heure (`HH:MM`). **Les heures sont interprétées en UTC.** |

Clic sur **Charger les chandelles** → appel API, récupération paginée (Binance renvoie max 1000 chandelles par requête, le fetch boucle automatiquement pour couvrir la plage entière), puis rendu du graphique (candles + histogramme de volume).

### 2. Empiler un trade dans Excel (section « Export Excel »)

- Saisir un **label** optionnel (ex. `long BTC avril`). Si vide, un label par défaut est généré : `{symbol}_{start_iso}_{end_iso}`.
- **Ajouter au fichier Excel** → ajoute le trade à `exports/candles.xlsx` (crée le fichier s'il n'existe pas). La section archive (en bas) saute automatiquement sur le trade tout juste ajouté.
- **Ouvrir le dossier exports** → ouvre `exports/` dans le gestionnaire de fichiers du système.

### 3. Naviguer dans les trades archivés (section « Archive Excel »)

Relit directement `exports/candles.xlsx` à chaque action, sans appel API.

| Bouton | Effet |
|---|---|
| **← Précédent** / **Suivant →** | Navigue entre les trades. Désactivés aux bornes. |
| **Rafraîchir** | Relit le fichier depuis le disque (utile si tu as édité le `.xlsx` à côté). |
| **🗑 Supprimer** | Supprime le trade courant (metadata + ses chandelles) du fichier Excel après confirmation. L'archive recale automatiquement l'affichage. |

Le libellé au-dessus du graphique indique : `Trade X/Y — {label} — {symbol} {interval} ({exchange})`.

---

## Contenu du fichier Excel

Le fichier `exports/candles.xlsx` est un classeur à **deux feuilles**. Elles sont toujours synchronisées via une colonne commune `trade_id`.

### Feuille `metadata` — une ligne par trade

| Colonne | Type | Description |
|---|---|---|
| `trade_id` | string | Identifiant unique du trade (UUID4 tronqué à 12 caractères hex, ex. `c11196a1bba2`). Clé vers la feuille `candles`. |
| `label` | string | Libellé donné à l'export (ex. `long BTC avril`), ou valeur générée automatiquement. |
| `exchange` | string | Nom de l'exchange (`Binance`). |
| `symbol` | string | Paire de trading (`BTCUSDT`). |
| `interval` | string | Granularité des chandelles (`15m`, `1h`, `1d`…). |
| `start_utc` | datetime | Début de la plage demandée (UTC, naïf). |
| `end_utc` | datetime | Fin de la plage demandée (UTC, naïf). |
| `nb_candles` | int | Nombre de chandelles récupérées pour ce trade (redondant avec un `COUNT` sur `candles` mais pratique). |
| `added_at` | datetime | Horodatage d'ajout au fichier (UTC, naïf). |

### Feuille `candles` — toutes les chandelles de tous les trades empilées

| Colonne | Type | Description |
|---|---|---|
| `trade_id` | string | Référence vers une ligne de `metadata`. |
| `open_time` | datetime | Ouverture de la chandelle (UTC, naïf). |
| `open` | float | Prix d'ouverture. |
| `high` | float | Plus haut. |
| `low` | float | Plus bas. |
| `close` | float | Prix de clôture. |
| `volume` | float | Volume sur la chandelle (en unité de base — pour `BTCUSDT`, exprimé en BTC). |
| `close_time` | datetime | Clôture de la chandelle (UTC, naïf). Égale à `open_time + interval − 1ms` pour Binance. |

### Relation entre les feuilles

```
metadata (1)  ──┬─── trade_id ───┬──  candles (N)
                │                │
                │ 1 ligne        │ N lignes (nb_candles)
```

Un seul trade dans `metadata` → exactement `nb_candles` lignes correspondantes dans `candles`. Pour isoler un trade dans Excel/LibreOffice, filtrer la feuille `candles` par `trade_id` identique à celui de la ligne `metadata` voulue.

### Contrainte clé

**Le fichier Excel est auto-suffisant pour reconstruire un graphique.** Toute information nécessaire à l'affichage (symbol, interval, exchange, nom à mettre en titre) est dans `metadata`, et les OHLCV dans `candles`. Aucun appel API n'est nécessaire pour re-visualiser — c'est précisément ce que fait la section « Archive Excel ».

### Logique d'écriture

À chaque `Ajouter au fichier Excel` : l'app lit les deux feuilles existantes, concatène la nouvelle metadata/candles, puis réécrit le classeur complet (`openpyxl`, mode write). Pas d'append partiel — c'est plus lent sur très gros fichiers mais évite les pièges classiques de `openpyxl`/`pd.ExcelWriter` en mode append avec overlay.

### Suppression

Le bouton **🗑 Supprimer** retire la ligne `metadata` et toutes les lignes `candles` avec le `trade_id` correspondant, puis réécrit le classeur. Action définitive.

---

## Architecture

```
CandleVisualizer/
├── app.py                    # Point d'entrée Dash
├── api/
│   ├── __init__.py           # Registre AVAILABLE_APIS
│   ├── base.py               # Classe abstraite ExchangeAPI
│   └── binance.py            # Implémentation Binance (pagination, dédup)
├── core/
│   ├── models.py             # TradeMetadata + schémas de colonnes
│   └── excel_io.py           # read_all / append_trade / delete_trade
├── ui/
│   ├── layout.py             # Layout Dash
│   └── callbacks.py          # Callbacks + rendu Plotly
├── exports/                  # Dossier du fichier candles.xlsx
└── requirements.txt
```

### Ajouter un nouvel exchange

1. Créer `api/mon_exchange.py` qui hérite de `ExchangeAPI` (`api/base.py`) et implémente :
   - `fetch_candles(symbol, interval, start, end)` → `DataFrame` avec colonnes `open_time, open, high, low, close, volume, close_time`
   - `interval_to_timedelta(interval)` → `timedelta`
2. L'enregistrer dans `api/__init__.py` :

```python
from .mon_exchange import MonExchangeAPI

AVAILABLE_APIS = {
    "Binance": BinanceAPI(),
    "MonExchange": MonExchangeAPI(),
}
```

Le dropdown de l'UI se remplit automatiquement. La liste des intervalles affichée est celle de Binance ; si ton exchange a un jeu différent, tu peux faire dépendre le dropdown `interval` de `api-dropdown` via un callback.

---

## Notes

- Les heures sont traitées en **UTC**. Pas de conversion de fuseau côté UI.
- Pas d'authentification : seul l'endpoint public `/api/v3/klines` de Binance est utilisé.
- Pas de déploiement : l'app est prévue pour tourner en local.
- `exports/candles.xlsx` peut être ouvert dans Excel, LibreOffice ou n'importe quelle lib pandas — c'est un xlsx standard.
