from __future__ import annotations

import platform
import re
import subprocess
from datetime import datetime
from io import StringIO

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, html, no_update
from plotly.subplots import make_subplots

from api import AVAILABLE_APIS
from core.excel_io import EXPORTS_DIR, append_trade, delete_trade, get_status, read_all


BULL_COLOR = "#26a69a"
BEAR_COLOR = "#ef5350"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def register_callbacks(app: Dash) -> None:
    @app.callback(
        Output("candles-store", "data"),
        Output("trade-context-store", "data"),
        Output("candles-graph", "figure"),
        Output("load-status", "children"),
        Output("export-button", "disabled"),
        Input("load-button", "n_clicks"),
        State("api-dropdown", "value"),
        State("symbol-input", "value"),
        State("interval-dropdown", "value"),
        State("start-date", "date"),
        State("start-time", "value"),
        State("end-date", "date"),
        State("end-time", "value"),
        prevent_initial_call=True,
    )
    def load_candles(
        n_clicks, api_name, symbol, interval, start_date, start_time, end_date, end_time
    ):
        try:
            start_dt = _combine_datetime(start_date, start_time)
            end_dt = _combine_datetime(end_date, end_time)
        except ValueError as e:
            return no_update, no_update, _empty_figure(), _error(str(e)), True

        if start_dt >= end_dt:
            return no_update, no_update, _empty_figure(), _error("La date de début doit être avant la date de fin."), True

        if not symbol or not symbol.strip():
            return no_update, no_update, _empty_figure(), _error("Symbol requis."), True

        api = AVAILABLE_APIS.get(api_name)
        if api is None:
            return no_update, no_update, _empty_figure(), _error(f"API inconnue: {api_name}"), True

        symbol = symbol.strip().upper()

        try:
            df = api.fetch_candles(symbol, interval, start_dt, end_dt)
        except Exception as e:
            return no_update, no_update, _empty_figure(), _error(f"Erreur API: {e}"), True

        if df.empty:
            return (
                None,
                None,
                _empty_figure(),
                _error("Aucune chandelle retournée pour cette plage."),
                True,
            )

        figure = build_figure(df, symbol=symbol, interval=interval, exchange=api_name)

        context = {
            "exchange": api_name,
            "symbol": symbol,
            "interval": interval,
            "start_utc": start_dt.isoformat(),
            "end_utc": end_dt.isoformat(),
        }

        status = html.Span(
            f"✓ {len(df)} chandelles chargées ({df['open_time'].min()} → {df['open_time'].max()})",
            style={"color": "#2e7d32"},
        )

        return df.to_json(orient="split", date_format="iso"), context, figure, status, False

    @app.callback(
        Output("export-status", "children"),
        Output("label-input", "value"),
        Input("export-button", "n_clicks"),
        State("candles-store", "data"),
        State("trade-context-store", "data"),
        State("label-input", "value"),
        prevent_initial_call=True,
    )
    def export_to_excel(n_clicks, candles_json, context, label):
        if not candles_json or not context:
            return _error("Charge d'abord des chandelles avant d'exporter."), no_update

        df = pd.read_json(StringIO(candles_json), orient="split")
        df["open_time"] = pd.to_datetime(df["open_time"])
        df["close_time"] = pd.to_datetime(df["close_time"])

        start_dt = datetime.fromisoformat(context["start_utc"])
        end_dt = datetime.fromisoformat(context["end_utc"])

        label_value = (label or "").strip()
        if not label_value:
            label_value = f"{context['symbol']}_{start_dt.isoformat()}_{end_dt.isoformat()}"

        try:
            append_trade(
                label=label_value,
                exchange=context["exchange"],
                symbol=context["symbol"],
                interval=context["interval"],
                candles=df,
                start_utc=start_dt,
                end_utc=end_dt,
            )
        except Exception as e:
            return _error(f"Erreur export: {e}"), no_update

        status = get_status()
        return (
            html.Span(
                f"✓ Ajouté — {status['nb_trades']} trades au total dans {status['path']}",
                style={"color": "#2e7d32"},
            ),
            "",
        )

    @app.callback(
        Output("archive-index-store", "data"),
        Output("archive-info", "children"),
        Output("archive-graph", "figure"),
        Output("archive-prev", "disabled"),
        Output("archive-next", "disabled"),
        Input("archive-prev", "n_clicks"),
        Input("archive-next", "n_clicks"),
        Input("archive-refresh", "n_clicks"),
        Input("archive-delete", "submit_n_clicks"),
        Input("export-status", "children"),
        State("archive-index-store", "data"),
    )
    def update_archive(prev_n, next_n, refresh_n, delete_n, export_status, current_idx):
        trigger = callback_context.triggered_id

        # Delete the current trade before re-reading
        if trigger == "archive-delete" and delete_n:
            meta_before, _ = read_all()
            if not meta_before.empty:
                idx_to_del = current_idx if isinstance(current_idx, int) else 0
                idx_to_del = max(0, min(idx_to_del, len(meta_before) - 1))
                try:
                    delete_trade(str(meta_before.iloc[idx_to_del]["trade_id"]))
                except Exception:
                    pass

        meta, candles = read_all()
        if meta.empty:
            return (
                0,
                html.Span("Aucun trade dans le fichier Excel.", style={"color": "#888"}),
                _empty_figure(),
                True,
                True,
            )

        idx = current_idx if isinstance(current_idx, int) else 0
        n = len(meta)

        if trigger == "archive-prev":
            idx = max(0, idx - 1)
        elif trigger == "archive-next":
            idx = min(n - 1, idx + 1)
        elif trigger == "export-status":
            # Jump to the trade that was just added (last row)
            idx = n - 1
        else:
            # archive-refresh, archive-delete, or initial load: clamp
            idx = max(0, min(idx, n - 1))

        row = meta.iloc[idx]
        trade_id = row["trade_id"]
        sub = candles[candles["trade_id"] == trade_id].copy()
        sub["open_time"] = pd.to_datetime(sub["open_time"])
        sub["close_time"] = pd.to_datetime(sub["close_time"])

        fig = build_figure(
            sub,
            symbol=str(row["symbol"]),
            interval=str(row["interval"]),
            exchange=str(row["exchange"]),
        )

        info = html.Span(
            f"Trade {idx + 1}/{n} — {row['label']} — {row['symbol']} {row['interval']} ({row['exchange']})",
            style={"color": "#333"},
        )

        return idx, info, fig, idx == 0, idx == n - 1

    @app.callback(
        Output("open-folder-button", "n_clicks"),
        Input("open-folder-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_exports_folder(n_clicks):
        if not n_clicks:
            return no_update
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        try:
            if system == "Linux":
                subprocess.Popen(["xdg-open", str(EXPORTS_DIR)])
            elif system == "Darwin":
                subprocess.Popen(["open", str(EXPORTS_DIR)])
            elif system == "Windows":
                subprocess.Popen(["explorer", str(EXPORTS_DIR)])
        except Exception:
            pass
        return 0


def build_figure(df: pd.DataFrame, symbol: str, interval: str, exchange: str) -> go.Figure:
    colors = [BULL_COLOR if c >= o else BEAR_COLOR for o, c in zip(df["open"], df["close"])]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["open_time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing_line_color=BULL_COLOR,
            decreasing_line_color=BEAR_COLOR,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=df["open_time"],
            y=df["volume"],
            marker_color=colors,
            name="Volume",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    start_str = df["open_time"].min().strftime("%Y-%m-%d %H:%M")
    end_str = df["open_time"].max().strftime("%Y-%m-%d %H:%M")

    fig.update_layout(
        title=f"{symbol} — {interval} — {start_str} → {end_str} ({exchange})",
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=True,
        xaxis2_rangeslider_thickness=0.05,
        margin=dict(l=40, r=20, t=50, b=30),
        template="plotly_white",
    )
    fig.update_yaxes(title_text="Prix", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig


def _empty_figure() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=30),
        annotations=[
            dict(
                text="Aucune donnée — charge des chandelles pour commencer.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="#888"),
            )
        ],
    )
    return fig


def _combine_datetime(date_str: str | None, time_str: str | None) -> datetime:
    if not date_str:
        raise ValueError("Date manquante.")
    time_str = (time_str or "00:00").strip()
    m = TIME_RE.match(time_str)
    if not m:
        raise ValueError(f"Format d'heure invalide: '{time_str}' (attendu HH:MM).")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Heure hors plage: '{time_str}'.")
    base = datetime.fromisoformat(date_str[:10])
    return base.replace(hour=hour, minute=minute)


def _error(msg: str) -> html.Span:
    return html.Span(f"⚠ {msg}", style={"color": "#c62828"})
