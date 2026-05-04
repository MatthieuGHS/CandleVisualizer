from __future__ import annotations

from datetime import date, timedelta

from dash import dcc, html

from api import AVAILABLE_APIS
from core.excel_io import get_status


def build_layout() -> html.Div:
    today = date.today()
    default_start_str = (today - timedelta(days=2)).strftime("%d/%m/%Y") + " 00:00"
    default_end_str = today.strftime("%d/%m/%Y") + " 00:00"
    status = get_status()
    default_api = "Binance"
    default_export_intervals = list(AVAILABLE_APIS[default_api].export_intervals)

    return html.Div(
        [
            html.H1("Candle Visualizer", style={"marginBottom": "0.25rem"}),
            html.P(
                "Récupère des bougies crypto sur 4 intervalles, visualise-les, "
                "et empile-les dans 4 fichiers Excel synchronisés.",
                style={"color": "#555", "marginTop": "0"},
            ),
            # ------------------------------------------------------------------
            # Configuration panel
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.H3("Configuration"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("API"),
                                    dcc.Dropdown(
                                        id="api-dropdown",
                                        options=[
                                            {"label": k, "value": k}
                                            for k in AVAILABLE_APIS.keys()
                                        ],
                                        value=default_api,
                                        clearable=False,
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "160px"},
                            ),
                            html.Div(
                                [
                                    html.Label("Symbol"),
                                    dcc.Input(
                                        id="symbol-input",
                                        type="text",
                                        value="BTCUSDT",
                                        placeholder="Ex: BTCUSDT",
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "160px"},
                            ),
                            html.Div(
                                [
                                    html.Label("Intervalles fetched"),
                                    html.Div(
                                        id="export-intervals-info",
                                        children=", ".join(default_export_intervals),
                                        style={
                                            "padding": "0.5rem",
                                            "border": "1px solid #ccc",
                                            "borderRadius": "4px",
                                            "backgroundColor": "#f5f5f5",
                                            "color": "#555",
                                        },
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "200px"},
                            ),
                        ],
                        style={"display": "flex", "gap": "1rem", "flexWrap": "wrap"},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Début (UTC) — JJ/MM/AAAA HH:MM"),
                                    dcc.Input(
                                        id="start-datetime",
                                        type="text",
                                        value=default_start_str,
                                        placeholder="01/06/2025 00:00",
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "220px"},
                            ),
                            html.Div(
                                [
                                    html.Label("Fin (UTC) — JJ/MM/AAAA HH:MM"),
                                    dcc.Input(
                                        id="end-datetime",
                                        type="text",
                                        value=default_end_str,
                                        placeholder="01/12/2025 00:00",
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "220px"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "1rem",
                            "marginTop": "1rem",
                            "flexWrap": "wrap",
                        },
                    ),
                    html.Button(
                        "Charger les bougies (4 intervalles)",
                        id="load-button",
                        n_clicks=0,
                        style={"marginTop": "1rem", "padding": "0.5rem 1rem"},
                    ),
                    html.Div(id="load-status", style={"marginTop": "0.5rem"}),
                ],
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "6px",
                    "padding": "1rem",
                    "marginBottom": "1rem",
                    "backgroundColor": "#fafafa",
                },
            ),
            # ------------------------------------------------------------------
            # Main chart with viewer interval selector
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.Label("Intervalle d'affichage"),
                    dcc.Dropdown(
                        id="viewer-interval",
                        options=[
                            {"label": i, "value": i} for i in default_export_intervals
                        ],
                        value=default_export_intervals[0],
                        clearable=False,
                        style={"width": "200px", "marginBottom": "0.5rem"},
                    ),
                ],
                style={"marginBottom": "0.5rem"},
            ),
            dcc.Loading(
                dcc.Graph(id="candles-graph", style={"height": "70vh"}),
                type="default",
            ),
            # ------------------------------------------------------------------
            # Export panel
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.H3("Export Excel"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Label (optionnel)"),
                                    dcc.Input(
                                        id="label-input",
                                        type="text",
                                        placeholder="Ex: long BTC avril",
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"flex": "2", "minWidth": "220px"},
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Ajouter aux 4 fichiers Excel",
                                        id="export-button",
                                        n_clicks=0,
                                        disabled=True,
                                        style={"padding": "0.5rem 1rem", "width": "100%"},
                                    ),
                                ],
                                style={
                                    "flex": "1",
                                    "minWidth": "200px",
                                    "alignSelf": "flex-end",
                                },
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Ouvrir le dossier exports",
                                        id="open-folder-button",
                                        n_clicks=0,
                                        style={"padding": "0.5rem 1rem", "width": "100%"},
                                    ),
                                ],
                                style={
                                    "flex": "1",
                                    "minWidth": "200px",
                                    "alignSelf": "flex-end",
                                },
                            ),
                        ],
                        style={"display": "flex", "gap": "1rem", "flexWrap": "wrap"},
                    ),
                    html.Div(
                        id="export-status",
                        children=_status_text(status),
                        style={"marginTop": "0.75rem", "color": "#333"},
                    ),
                ],
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "6px",
                    "padding": "1rem",
                    "marginTop": "1rem",
                    "backgroundColor": "#fafafa",
                },
            ),
            # ------------------------------------------------------------------
            # Import panel — 4 xlsx + labels.csv
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.H3("Importer une archive"),
                    html.P(
                        "Drag & drop les 4 fichiers `candles_*.xlsx` + le `labels.csv`. "
                        "L'intervalle de chaque xlsx est auto-détecté via la metadata. "
                        "Tu pourras ajouter à ton archive locale uniquement les trades qui t'intéressent.",
                        style={"color": "#555", "fontSize": "0.9rem"},
                    ),
                    dcc.Upload(
                        id="import-upload",
                        children=html.Div(
                            [
                                "Drag & drop ou ",
                                html.A("sélectionner les fichiers"),
                                " (4 xlsx + 1 csv)",
                            ]
                        ),
                        multiple=True,
                        style={
                            "width": "100%",
                            "height": "60px",
                            "lineHeight": "60px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "5px",
                            "textAlign": "center",
                            "marginBottom": "0.5rem",
                            "color": "#555",
                        },
                    ),
                    html.Div(id="import-status", style={"marginBottom": "0.5rem"}),
                    html.Div(
                        [
                            html.Button(
                                "← Précédent",
                                id="import-prev",
                                n_clicks=0,
                                style={"padding": "0.5rem 1rem"},
                            ),
                            html.Button(
                                "Suivant →",
                                id="import-next",
                                n_clicks=0,
                                style={"padding": "0.5rem 1rem"},
                            ),
                            html.Button(
                                "➕ Ajouter à mon archive",
                                id="import-add",
                                n_clicks=0,
                                style={
                                    "padding": "0.5rem 1rem",
                                    "color": "#1565c0",
                                    "borderColor": "#1565c0",
                                },
                            ),
                            html.Div(
                                id="import-info",
                                style={
                                    "marginLeft": "1rem",
                                    "alignSelf": "center",
                                    "color": "#333",
                                    "flex": "1",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "0.5rem",
                            "flexWrap": "wrap",
                            "alignItems": "center",
                        },
                    ),
                    html.Div(
                        [
                            html.Label("Intervalle d'affichage (preview)"),
                            dcc.Dropdown(
                                id="import-viewer-interval",
                                options=[],
                                clearable=False,
                                style={"width": "200px", "marginTop": "0.25rem"},
                            ),
                        ],
                        style={"marginTop": "0.5rem"},
                    ),
                    dcc.Loading(
                        dcc.Graph(id="import-graph", style={"height": "60vh"}),
                        type="default",
                    ),
                ],
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "6px",
                    "padding": "1rem",
                    "marginTop": "1rem",
                    "backgroundColor": "#fafafa",
                },
            ),
            # ------------------------------------------------------------------
            # Archive viewer (read from Excel)
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.H3("Archive Excel"),
                    html.Div(
                        [
                            html.Button(
                                "← Précédent",
                                id="archive-prev",
                                n_clicks=0,
                                style={"padding": "0.5rem 1rem"},
                            ),
                            html.Button(
                                "Suivant →",
                                id="archive-next",
                                n_clicks=0,
                                style={"padding": "0.5rem 1rem"},
                            ),
                            html.Button(
                                "Rafraîchir",
                                id="archive-refresh",
                                n_clicks=0,
                                style={"padding": "0.5rem 1rem"},
                            ),
                            dcc.ConfirmDialogProvider(
                                children=html.Button(
                                    "🗑 Supprimer",
                                    style={
                                        "padding": "0.5rem 1rem",
                                        "color": "#c62828",
                                        "borderColor": "#c62828",
                                    },
                                ),
                                id="archive-delete",
                                message="Supprimer ce trade des 4 fichiers Excel ? Action définitive.",
                            ),
                            html.A(
                                html.Button(
                                    "📥 Télécharger l'archive (ZIP)",
                                    id="archive-download-button",
                                    n_clicks=0,
                                    style={"padding": "0.5rem 1rem"},
                                ),
                                id="archive-download-link",
                                href="#",
                                target="_blank",
                            ),
                            html.Div(
                                id="archive-info",
                                style={
                                    "marginLeft": "1rem",
                                    "alignSelf": "center",
                                    "color": "#333",
                                    "flex": "1",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "0.5rem",
                            "flexWrap": "wrap",
                            "alignItems": "center",
                        },
                    ),
                    html.Div(
                        [
                            html.Label("Intervalle d'affichage"),
                            dcc.Dropdown(
                                id="archive-interval",
                                options=[],
                                clearable=False,
                                style={"width": "200px", "marginTop": "0.25rem"},
                            ),
                        ],
                        style={"marginTop": "0.5rem"},
                    ),
                    dcc.Loading(
                        dcc.Graph(id="archive-graph", style={"height": "70vh"}),
                        type="default",
                    ),
                    dcc.Download(id="archive-download"),
                ],
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "6px",
                    "padding": "1rem",
                    "marginTop": "1rem",
                    "backgroundColor": "#fafafa",
                },
            ),
            # ------------------------------------------------------------------
            # Reconstruction depuis CSV — workflow autonome
            # ------------------------------------------------------------------
            html.Div(
                [
                    html.H3("Reconstruire 4 Excel depuis un CSV"),
                    html.P(
                        "Workflow autonome : upload un CSV au format `labels.csv` "
                        "(`symbol, timeframe, t_ath, exchange`), l'app fetch les 4 "
                        "intervalles autour de chaque `t_ath` et te propose le ZIP "
                        "(4 Excel + CSV) en téléchargement. "
                        "N'affecte ni l'archive locale ni `labels.csv` racine.",
                        style={"color": "#555", "fontSize": "0.9rem"},
                    ),
                    dcc.Upload(
                        id="rebuild-upload",
                        children=html.Div(
                            ["Drag & drop ou ", html.A("sélectionner le CSV")]
                        ),
                        multiple=False,
                        style={
                            "width": "100%",
                            "height": "60px",
                            "lineHeight": "60px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "5px",
                            "textAlign": "center",
                            "marginBottom": "0.5rem",
                            "color": "#555",
                        },
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Fenêtre (jours autour de t_ath)"),
                                    dcc.Input(
                                        id="rebuild-window-days",
                                        type="number",
                                        value=7,
                                        min=1,
                                        max=90,
                                        step=1,
                                        style={"width": "100%"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "180px"},
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Lancer la reconstruction",
                                        id="rebuild-button",
                                        n_clicks=0,
                                        style={
                                            "padding": "0.5rem 1rem",
                                            "width": "100%",
                                        },
                                    ),
                                ],
                                style={
                                    "flex": "1",
                                    "minWidth": "200px",
                                    "alignSelf": "flex-end",
                                },
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "📥 Télécharger ZIP (4 Excel + CSV)",
                                        id="rebuild-download-button",
                                        n_clicks=0,
                                        disabled=True,
                                        style={
                                            "padding": "0.5rem 1rem",
                                            "width": "100%",
                                        },
                                    ),
                                ],
                                style={
                                    "flex": "1",
                                    "minWidth": "240px",
                                    "alignSelf": "flex-end",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "gap": "1rem",
                            "flexWrap": "wrap",
                        },
                    ),
                    dcc.Loading(
                        html.Div(
                            id="rebuild-status",
                            style={"marginTop": "0.75rem", "color": "#333"},
                        ),
                        type="default",
                    ),
                    dcc.Download(id="rebuild-download"),
                ],
                style={
                    "border": "1px solid #ddd",
                    "borderRadius": "6px",
                    "padding": "1rem",
                    "marginTop": "1rem",
                    "backgroundColor": "#fafafa",
                },
            ),
            # ------------------------------------------------------------------
            # Stores
            # ------------------------------------------------------------------
            # Bougies fetched : `{interval: candles_json, ...}` pour l'API courante
            dcc.Store(id="candles-store"),
            dcc.Store(id="trade-context-store"),
            dcc.Store(id="archive-index-store", data=0),
            dcc.Store(id="import-store"),  # archive importée parsée
            dcc.Store(id="import-index-store", data=0),
            dcc.Store(id="rebuild-cache-id"),  # uuid pointant vers le ZIP en cache serveur
        ],
        style={
            "maxWidth": "1200px",
            "margin": "2rem auto",
            "padding": "0 1rem",
            "fontFamily": "system-ui, sans-serif",
        },
    )


def _status_text(status: dict) -> str:
    if not status["files"]:
        return f"Aucun fichier encore. Sera créé dans : {status['dir']}"
    files = ", ".join(status["files"])
    return f"{status['nb_trades']} trade(s) — fichiers : {files} — dossier : {status['dir']}"
