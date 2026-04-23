# CandleVisualizer

Application Dash locale pour récupérer, visualiser et archiver des chandeliers crypto.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
python app.py
```

Puis ouvrir http://127.0.0.1:8050 dans le navigateur.

## Utilisation

1. Choisir l'API (Binance par défaut)
2. Saisir un symbol (ex. `BTCUSDT`, `ETHUSDT`)
3. Choisir la plage (date + heure UTC) et l'intervalle
4. Cliquer **Charger les chandelles** → le graphique s'affiche (candles + volume)
5. Optionnel : saisir un label, puis **Ajouter au fichier Excel** pour empiler ce trade dans `exports/candles.xlsx`

## Format Excel

Un unique fichier `exports/candles.xlsx` contient deux sheets :

- **`metadata`** : une ligne par trade stocké
  - `trade_id`, `label`, `exchange`, `symbol`, `interval`, `start_utc`, `end_utc`, `nb_candles`, `added_at`
- **`candles`** : toutes les chandelles de tous les trades empilées
  - `trade_id`, `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`

`trade_id` relie les deux sheets. Le fichier contient toute l'information nécessaire pour reconstruire un graphique sans refaire d'appel API.

## Ajouter un nouvel exchange

1. Créer un fichier `api/mon_exchange.py` implémentant `ExchangeAPI` (voir `api/base.py`)
2. Implémenter `fetch_candles()` (retour : DataFrame avec colonnes `open_time, open, high, low, close, volume, close_time`) et `interval_to_timedelta()`
3. L'enregistrer dans `api/__init__.py` :

```python
from .mon_exchange import MonExchangeAPI

AVAILABLE_APIS = {
    "Binance": BinanceAPI(),
    "MonExchange": MonExchangeAPI(),
}
```

Le dropdown de l'UI se met à jour automatiquement.

## Structure

```
candle_visualizer/
├── app.py                # Point d'entrée Dash
├── api/                  # Couche exchange (base + implémentations)
├── core/                 # Modèles + I/O Excel
├── ui/                   # Layout + callbacks Dash
├── exports/              # Fichier candles.xlsx
└── requirements.txt
```
