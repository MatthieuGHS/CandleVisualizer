# CandleVisualizer

Application Dash locale pour récupérer, visualiser et archiver des bougies crypto. Chaque trade chargé peut être empilé dans un **unique** fichier Excel réutilisable — suffisant pour reconstruire n'importe quel graphique plus tard, sans refaire d'appel API.

Un script secondaire (`build_labels.py`) consomme ensuite cet Excel pour produire un `labels.csv` contenant, pour chaque trade, le timestamp 30m de la bougie au `high` maximum.

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

### 1. Charger des bougies (section « Configuration »)

| Champ | Description |
|---|---|
| **API** | Exchange source : **Binance** ou **Coinbase**. Architecture extensible, voir plus bas. |
| **Symbol** | Paire de trading. Format dépend de l'exchange : `BTCUSDT` sur Binance, `BTC-USD` sur Coinbase. Majuscules forcées. Le placeholder du champ s'adapte à l'API choisie. |
| **Interval** | Dépend de l'exchange. **Binance** : 15 granularités (`1m` → `1M`). **Coinbase** : 6 granularités (`1m`, `5m`, `15m`, `1h`, `6h`, `1d`). La liste se met à jour en changeant d'API. |
| **Début / Fin (UTC)** | Bornes de la plage à récupérer. Champ texte unique au format `JJ/MM/AAAA HH:MM` (ex. `25/04/2025 14:30`). Les formats `JJ/MM/AAAA`, `AAAA-MM-JJ HH:MM` et `AAAA-MM-JJ` sont également acceptés. **Les heures sont interprétées en UTC.** |

Clic sur **Charger les bougies** → appel API, récupération paginée (Binance renvoie max 1000 bougies par requête, Coinbase 300 ; le fetch boucle automatiquement pour couvrir la plage entière), puis rendu du graphique (candles + histogramme de volume). Le survol d'une bougie affiche OHLC + la **variation en %** de la bougie.

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
| **🗑 Supprimer** | Supprime le trade courant (metadata + ses bougies) du fichier Excel après confirmation. L'archive recale automatiquement l'affichage. |

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
| `interval` | string | Granularité des bougies (`15m`, `1h`, `1d`…). |
| `start_utc` | datetime | Début de la plage demandée (UTC, naïf). |
| `end_utc` | datetime | Fin de la plage demandée (UTC, naïf). |
| `nb_candles` | int | Nombre de bougies récupérées pour ce trade (redondant avec un `COUNT` sur `candles` mais pratique). |

### Feuille `candles` — toutes les bougies de tous les trades empilées

| Colonne | Type | Description |
|---|---|---|
| `trade_id` | string | Référence vers une ligne de `metadata`. |
| `open_time` | datetime | Ouverture de la bougie (UTC, naïf). |
| `open` | float | Prix d'ouverture. |
| `high` | float | Plus haut. |
| `low` | float | Plus bas. |
| `close` | float | Prix de clôture. |
| `volume` | float | Volume sur la bougie (en unité de base — pour `BTCUSDT`, exprimé en BTC). |
| `close_time` | datetime | Clôture de la bougie (UTC, naïf). Égale à `open_time + interval − 1ms` pour Binance. |
| `pct_change` | float | Variation de la bougie en pourcentage : `(close − open) / open × 100`. Positif = bougie haussière, négatif = bougie baissière. Arrondi à 4 décimales. |

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

## Génération du `labels.csv`

Le script `build_labels.py` consomme `exports/candles.xlsx` et produit un CSV listant, pour chaque trade, la bougie 30m Binance où le `high` est maximum.

```bash
python build_labels.py
```

Pour chaque trade du Excel, le script :

1. Lit les bougies stockées et repère celle avec le `high` le plus élevé → zone grossière du pic.
2. Refait un **fetch 30m Binance** (±1 jour autour de ce pic) pour raffiner la granularité.
3. Prend la bougie 30m dont le `high` est maximum → timestamp à la demi-heure près.
4. Écrit une ligne dans `labels.csv` :

```csv
symbol,timeframe,t_ath,exchange
SUI/USDT,30m,2025-04-25T12:00:00Z,binance
AVAX/USDT,30m,2025-05-12T07:30:00Z,binance
```

### Format

- `symbol` : avec slash (`SOL/USDT`, pas `SOLUSDT`). Les paires Coinbase `XXX-USD` sont normalisées en `XXX/USDT` Binance.
- `timeframe` : toujours `30m`.
- `t_ath` : ISO 8601 avec `Z` final (UTC). Minutes `:00` ou `:30`.
- `exchange` : toujours `binance`.

### Contrainte sur le Excel

**`build_labels.py` ne modifie jamais `candles.xlsx`** — le Excel est strictement en lecture seule côté script. Toutes les modifications doivent passer par l'app Dash (ajout ou suppression de trades).

Pour obtenir un timestamp ciblé, charge dans l'app une **fenêtre serrée autour de la zone voulue** (quelques semaines max) : le max du `high` sur cette fenêtre sera la bougie sélectionnée. Une fenêtre trop large donnera le pic global de la période.

---

## Architecture

```
CandleVisualizer/
├── app.py                    # Point d'entrée Dash
├── build_labels.py           # Script : xlsx → labels.csv (refetch 30m pour ATH précis)
├── api/
│   ├── __init__.py           # Registre AVAILABLE_APIS
│   ├── base.py               # Classe abstraite ExchangeAPI
│   ├── binance.py            # Implémentation Binance (1000/req, pagination, dédup)
│   └── coinbase.py           # Implémentation Coinbase Exchange (300/req)
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
- Pas d'authentification : seuls les endpoints publics sont utilisés (`/api/v3/klines` de Binance, `/products/{id}/candles` de Coinbase Exchange).
- Pas de déploiement : l'app est prévue pour tourner en local.
- `exports/candles.xlsx` peut être ouvert dans Excel, LibreOffice ou n'importe quelle lib pandas — c'est un xlsx standard.
