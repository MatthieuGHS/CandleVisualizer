from __future__ import annotations

from datetime import date, timedelta

from dash import dcc, html

from api import AVAILABLE_APIS
from core.excel_io import get_status


def build_layout() -> html.Div:
    default_intervals = AVAILABLE_APIS["Binance"].supported_intervals
    today = date.today()
    default_start = today - timedelta(days=2)
    status = get_status()

    return html.Div(
        [
            html.H1("Candle Visualizer", style={"marginBottom": "0.25rem"}),
            html.P(
                "Récupère des chandeliers crypto, visualise-les, et empile-les dans un fichier Excel réutilisable.",
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
                                        options=[{"label": k, "value": k} for k in AVAILABLE_APIS.keys()],
                                        value="Binance",
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
                                    html.Label("Interval"),
                                    dcc.Dropdown(
                                        id="interval-dropdown",
                                        options=[{"label": i, "value": i} for i in default_intervals],
                                        value="15m",
                                        clearable=False,
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "120px"},
                            ),
                        ],
                        style={"display": "flex", "gap": "1rem", "flexWrap": "wrap"},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Début (UTC)"),
                                    html.Div(
                                        [
                                            dcc.DatePickerSingle(
                                                id="start-date",
                                                date=default_start,
                                                display_format="DD/MM/YYYY",
                                            ),
                                            dcc.Input(
                                                id="start-time",
                                                type="text",
                                                value="00:00",
                                                placeholder="HH:MM",
                                                style={"width": "90px", "marginLeft": "0.5rem"},
                                            ),
                                        ],
                                        style={"display": "flex", "alignItems": "center"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "220px"},
                            ),
                            html.Div(
                                [
                                    html.Label("Fin (UTC)"),
                                    html.Div(
                                        [
                                            dcc.DatePickerSingle(
                                                id="end-date",
                                                date=today,
                                                display_format="DD/MM/YYYY",
                                            ),
                                            dcc.Input(
                                                id="end-time",
                                                type="text",
                                                value="00:00",
                                                placeholder="HH:MM",
                                                style={"width": "90px", "marginLeft": "0.5rem"},
                                            ),
                                        ],
                                        style={"display": "flex", "alignItems": "center"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "220px"},
                            ),
                        ],
                        style={"display": "flex", "gap": "1rem", "marginTop": "1rem", "flexWrap": "wrap"},
                    ),
                    html.Button(
                        "Charger les chandelles",
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
            # Chart
            # ------------------------------------------------------------------
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
                                        "Ajouter au fichier Excel",
                                        id="export-button",
                                        n_clicks=0,
                                        disabled=True,
                                        style={"padding": "0.5rem 1rem", "width": "100%"},
                                    ),
                                ],
                                style={"flex": "1", "minWidth": "200px", "alignSelf": "flex-end"},
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
                                style={"flex": "1", "minWidth": "200px", "alignSelf": "flex-end"},
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
                                message="Supprimer ce trade du fichier Excel ? Action définitive.",
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
                        style={"display": "flex", "gap": "0.5rem", "flexWrap": "wrap", "alignItems": "center"},
                    ),
                    dcc.Loading(
                        dcc.Graph(id="archive-graph", style={"height": "70vh"}),
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
            # Stores
            # ------------------------------------------------------------------
            dcc.Store(id="candles-store"),
            dcc.Store(id="trade-context-store"),
            dcc.Store(id="archive-index-store", data=0),
        ],
        style={
            "maxWidth": "1200px",
            "margin": "2rem auto",
            "padding": "0 1rem",
            "fontFamily": "system-ui, sans-serif",
        },
    )


def _status_text(status: dict) -> str:
    if not status["exists"]:
        return f"Aucun fichier encore. Sera créé à : {status['path']}"
    return f"{status['nb_trades']} trade(s) dans {status['path']}"
