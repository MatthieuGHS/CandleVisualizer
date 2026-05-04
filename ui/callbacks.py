from __future__ import annotations

import base64
import io
import platform
import subprocess
import time
import uuid
import zipfile
from datetime import datetime
from io import BytesIO, StringIO

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update
from plotly.subplots import make_subplots

from api import AVAILABLE_APIS
from core.excel_io import (
    CANDLES_COLUMNS,
    EXCEL_PATHS,
    EXPORTS_DIR,
    METADATA_COLUMNS,
    add_imported_trade,
    append_trade,
    archive_zip_bytes,
    build_archives_in_memory,
    delete_trade,
    get_status,
    get_trade_candles,
    list_trades,
    new_trade_id,
    parse_uploaded_archives,
    _read_archive_file,
)
from core.labels_io import (
    EXCHANGE_LABEL_INTERVAL,
    LABELS_PATH,
    append_label,
    compute_label_from_local,
    denormalize_symbol_for_api,
    labels_csv_bytes,
    lookup_label_row,
    parse_uploaded_labels,
    rebuild_labels_from_archive,
)
from core.models import TradeMetadata


# Cache serveur pour les ZIP de reconstruction (clé : uuid → bytes du zip).
# OK pour app locale single-user. Effacé au redémarrage du process.
_REBUILD_CACHE: dict = {}


BULL_COLOR = "#26a69a"
BEAR_COLOR = "#ef5350"

MAX_FETCH_RETRIES = 3
RETRY_BASE_SLEEP_S = 1.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fetch_with_retry(api, symbol, interval, start, end):
    """Fetch avec retry exponentiel : 3 tentatives max, sleep 1s/2s/4s."""
    last_exc = None
    for attempt in range(MAX_FETCH_RETRIES):
        try:
            df = api.fetch_candles(symbol, interval, start, end)
            return df
        except Exception as e:
            last_exc = e
            if attempt < MAX_FETCH_RETRIES - 1:
                time.sleep(RETRY_BASE_SLEEP_S * (2**attempt))
    raise RuntimeError(
        f"Échec après {MAX_FETCH_RETRIES} tentatives sur {symbol} {interval} : {last_exc}"
    )


def _df_to_json(df: pd.DataFrame) -> str:
    return df.to_json(orient="split", date_format="iso")


def _df_from_json(s: str) -> pd.DataFrame:
    df = pd.read_json(StringIO(s), orient="split")
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"])
    if "close_time" in df.columns:
        df["close_time"] = pd.to_datetime(df["close_time"])
    return df


def _decode_upload(contents: str) -> bytes:
    """Dash dcc.Upload renvoie un base64. Décode en bytes."""
    _, b64 = contents.split(",", 1)
    return base64.b64decode(b64)


def _split_uploaded_files(filenames: list[str], contents_list: list[str]):
    """Sépare les fichiers uploadés en (xlsx_files, csv_file).

    Returns:
        (xlsx_named_files, csv_bytes_or_none)
        xlsx_named_files : liste d'objets file-like avec attributs `.name` et `.size`
    """
    xlsx_files = []
    csv_bytes = None

    for fname, content in zip(filenames, contents_list):
        data = _decode_upload(content)
        lower = fname.lower()
        if lower.endswith(".xlsx"):
            bio = BytesIO(data)
            bio.name = fname
            bio.size = len(data)
            xlsx_files.append(bio)
        elif lower.endswith(".csv"):
            if csv_bytes is not None:
                raise ValueError("Plusieurs fichiers .csv fournis (1 seul attendu).")
            csv_bytes = data
        else:
            raise ValueError(f"Fichier inattendu : {fname} (.xlsx ou .csv attendu)")

    return xlsx_files, csv_bytes


# --------------------------------------------------------------------------- #
# Callbacks
# --------------------------------------------------------------------------- #


def register_callbacks(app: Dash) -> None:

    # ──────────────────────────────────────────────────────────────────
    # Update API-dependent fields (export intervals + viewer dropdown)
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("export-intervals-info", "children"),
        Output("symbol-input", "placeholder"),
        Output("viewer-interval", "options"),
        Output("viewer-interval", "value"),
        Input("api-dropdown", "value"),
    )
    def update_api_dependent_fields(api_name):
        api = AVAILABLE_APIS.get(api_name)
        if api is None:
            return no_update, no_update, no_update, no_update
        intervals = list(api.export_intervals)
        info = ", ".join(intervals)
        placeholder = "Ex: BTC-USD" if api_name == "Coinbase" else "Ex: BTCUSDT"
        return info, placeholder, [{"label": i, "value": i} for i in intervals], intervals[0]

    # ──────────────────────────────────────────────────────────────────
    # Load candles : fetch the 4 intervals with retry
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("candles-store", "data"),
        Output("trade-context-store", "data"),
        Output("load-status", "children"),
        Output("export-button", "disabled"),
        Input("load-button", "n_clicks"),
        State("api-dropdown", "value"),
        State("symbol-input", "value"),
        State("start-datetime", "value"),
        State("end-datetime", "value"),
        prevent_initial_call=True,
    )
    def load_candles(n_clicks, api_name, symbol, start_str, end_str):
        try:
            start_dt = _parse_datetime(start_str, "début")
            end_dt = _parse_datetime(end_str, "fin")
        except ValueError as e:
            return no_update, no_update, _error(str(e)), True

        if start_dt >= end_dt:
            return no_update, no_update, _error("La date de début doit être avant la date de fin."), True

        if not symbol or not symbol.strip():
            return no_update, no_update, _error("Symbol requis."), True

        api = AVAILABLE_APIS.get(api_name)
        if api is None:
            return no_update, no_update, _error(f"API inconnue : {api_name}"), True

        symbol_clean = symbol.strip().upper()

        # Fetch séquentiel des 4 intervalles avec retry. Si un seul échoue après
        # les retries, on annule tout (cohérence multi-fichiers).
        per_interval_json: dict = {}
        per_interval_count: dict = {}
        for iv in api.export_intervals:
            try:
                df = _fetch_with_retry(api, symbol_clean, iv, start_dt, end_dt)
            except Exception as e:
                return no_update, no_update, _error(f"Fetch {iv} échoué : {e}"), True
            if df.empty:
                return (
                    no_update,
                    no_update,
                    _error(f"Aucune bougie retournée pour {iv} sur cette plage."),
                    True,
                )
            per_interval_json[iv] = _df_to_json(df)
            per_interval_count[iv] = len(df)

        context = {
            "exchange": api_name,
            "symbol": symbol_clean,
            "intervals": list(api.export_intervals),
            "start_utc": start_dt.isoformat(),
            "end_utc": end_dt.isoformat(),
        }

        summary = ", ".join(f"{iv}: {n}" for iv, n in per_interval_count.items())
        status = html.Span(
            f"✓ 4 intervalles chargés ({summary})",
            style={"color": "#2e7d32"},
        )
        return per_interval_json, context, status, False

    # ──────────────────────────────────────────────────────────────────
    # Main view : redraw the graph when the viewer interval changes
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("candles-graph", "figure"),
        Input("viewer-interval", "value"),
        Input("candles-store", "data"),
        State("trade-context-store", "data"),
    )
    def update_main_view(viewer_iv, candles_json, context):
        if not candles_json or not viewer_iv or viewer_iv not in candles_json:
            return _empty_figure()
        if not context:
            return _empty_figure()
        df = _df_from_json(candles_json[viewer_iv])
        return build_figure(
            df,
            symbol=context["symbol"],
            interval=viewer_iv,
            exchange=context["exchange"],
        )

    # ──────────────────────────────────────────────────────────────────
    # Export : append to the 4 Excel files + labels.csv
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("export-status", "children", allow_duplicate=True),
        Output("label-input", "value"),
        Input("export-button", "n_clicks"),
        State("candles-store", "data"),
        State("trade-context-store", "data"),
        State("label-input", "value"),
        prevent_initial_call=True,
    )
    def export_to_excel(n_clicks, candles_json, context, label):
        if not candles_json or not context:
            return _error("Charge d'abord des bougies avant d'exporter."), no_update

        candles_per_iv = {iv: _df_from_json(s) for iv, s in candles_json.items()}

        start_dt = datetime.fromisoformat(context["start_utc"])
        end_dt = datetime.fromisoformat(context["end_utc"])

        label_value = (label or "").strip()
        if not label_value:
            label_value = f"{context['symbol']}_{start_dt.isoformat()}_{end_dt.isoformat()}"

        try:
            meta = append_trade(
                label=label_value,
                exchange=context["exchange"],
                symbol=context["symbol"],
                candles_per_interval=candles_per_iv,
                start_utc=start_dt,
                end_utc=end_dt,
            )
        except Exception as e:
            return _error(f"Erreur export : {e}"), no_update

        # labels.csv : recompute depuis les bougies locales du timeframe de référence
        csv_warning = ""
        try:
            ref_iv = EXCHANGE_LABEL_INTERVAL[context["exchange"]]
            ref_candles = get_trade_candles(meta.trade_id, ref_iv)
            label_row = compute_label_from_local(
                {"symbol": context["symbol"], "exchange": context["exchange"], "trade_id": meta.trade_id},
                ref_candles,
            )
            append_label(label_row)
        except Exception as e:
            csv_warning = f" (⚠ labels.csv non mis à jour : {e})"

        status = get_status()
        return (
            html.Span(
                f"✓ Ajouté — {status['nb_trades']} trades — fichiers : "
                f"{', '.join(status['files'])}{csv_warning}",
                style={"color": "#2e7d32" if not csv_warning else "#c0a000"},
            ),
            "",
        )

    # ──────────────────────────────────────────────────────────────────
    # Archive — state : navigation, delete, options du selectbox
    # (séparé de la vue pour casser le cycle archive-interval ↔ index-store)
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("archive-index-store", "data"),
        Output("archive-prev", "disabled"),
        Output("archive-next", "disabled"),
        Output("archive-interval", "options"),
        Output("archive-interval", "value"),
        Input("archive-prev", "n_clicks"),
        Input("archive-next", "n_clicks"),
        Input("archive-refresh", "n_clicks"),
        Input("archive-delete", "submit_n_clicks"),
        Input("export-status", "children"),
        State("archive-index-store", "data"),
        State("archive-interval", "value"),
    )
    def update_archive_state(
        prev_n, next_n, refresh_n, delete_n, export_status, current_idx, current_iv
    ):
        trigger = callback_context.triggered_id

        if trigger == "archive-delete" and delete_n:
            meta_before = list_trades()
            if not meta_before.empty:
                idx_to_del = current_idx if isinstance(current_idx, int) else 0
                idx_to_del = max(0, min(idx_to_del, len(meta_before) - 1))
                try:
                    delete_trade(str(meta_before.iloc[idx_to_del]["trade_id"]))
                except Exception:
                    pass
                try:
                    rebuild_labels_from_archive()
                except Exception:
                    pass

        meta = list_trades()
        if meta.empty:
            return 0, True, True, [], None

        idx = current_idx if isinstance(current_idx, int) else 0
        n = len(meta)

        if trigger == "archive-prev":
            idx = max(0, idx - 1)
        elif trigger == "archive-next":
            idx = min(n - 1, idx + 1)
        elif trigger == "export-status":
            idx = n - 1
        else:
            idx = max(0, min(idx, n - 1))

        exchange = str(meta.iloc[idx]["exchange"])
        api = AVAILABLE_APIS.get(exchange)
        if api is None:
            return idx, idx == 0, idx == n - 1, [], None

        intervals = list(api.export_intervals)
        new_iv = current_iv if current_iv in intervals else intervals[0]
        return (
            idx,
            idx == 0,
            idx == n - 1,
            [{"label": i, "value": i} for i in intervals],
            new_iv,
        )

    # ──────────────────────────────────────────────────────────────────
    # Archive — view : redessine info + graph quand l'index ou l'intervalle change
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("archive-info", "children"),
        Output("archive-graph", "figure"),
        Input("archive-index-store", "data"),
        Input("archive-interval", "value"),
    )
    def update_archive_view(archive_idx, archive_iv):
        meta = list_trades()
        if meta.empty:
            return (
                html.Span("Aucun trade dans l'archive.", style={"color": "#888"}),
                _empty_figure(),
            )

        idx = archive_idx if isinstance(archive_idx, int) else 0
        idx = max(0, min(idx, len(meta) - 1))

        row = meta.iloc[idx]
        trade_id = row["trade_id"]
        exchange = str(row["exchange"])

        api = AVAILABLE_APIS.get(exchange)
        if api is None:
            return (
                html.Span(f"Exchange inconnu : {exchange}", style={"color": "#c62828"}),
                _empty_figure(),
            )

        intervals = list(api.export_intervals)
        iv_to_show = archive_iv if archive_iv in intervals else intervals[0]

        sub = get_trade_candles(trade_id, iv_to_show)
        if sub.empty:
            fig = _empty_figure()
        else:
            sub["open_time"] = pd.to_datetime(sub["open_time"])
            sub["close_time"] = pd.to_datetime(sub["close_time"])
            fig = build_figure(
                sub,
                symbol=str(row["symbol"]),
                interval=iv_to_show,
                exchange=exchange,
            )

        info = html.Span(
            f"Trade {idx + 1}/{len(meta)} — {row['label']} — {row['symbol']} ({exchange}) "
            f"— vue : {iv_to_show}",
            style={"color": "#333"},
        )
        return info, fig

    # ──────────────────────────────────────────────────────────────────
    # Archive ZIP download
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("archive-download", "data"),
        Input("archive-download-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def download_archive(n_clicks):
        if not n_clicks:
            return no_update
        extras = {}
        csv_bytes = labels_csv_bytes()
        if csv_bytes is not None:
            extras["labels.csv"] = csv_bytes
        zb = archive_zip_bytes(extra_files=extras)
        if zb is None:
            return no_update
        return dcc.send_bytes(zb, "candlevisualizer_archive.zip")

    # ──────────────────────────────────────────────────────────────────
    # Import : parse uploaded files (4 xlsx + 1 csv)
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("import-store", "data"),
        Output("import-status", "children"),
        Output("import-viewer-interval", "options"),
        Output("import-viewer-interval", "value"),
        Input("import-upload", "contents"),
        State("import-upload", "filename"),
        prevent_initial_call=True,
    )
    def parse_import(contents, filenames):
        # `import-index-store.data` est remis à 0 par `update_import_view` quand le
        # store change (trigger `import-store`) — ce callback n'a pas à l'écrire,
        # ce qui éviterait un duplicate Output.
        if not contents or not filenames:
            return None, "", [], None

        try:
            xlsx_files, csv_bytes = _split_uploaded_files(filenames, contents)
        except ValueError as e:
            return None, _error(str(e)), [], None

        if csv_bytes is None:
            return None, _error("Aucun labels.csv détecté dans les fichiers uploadés."), [], None

        try:
            by_iv = parse_uploaded_archives(xlsx_files)
        except ValueError as e:
            return None, _error(str(e)), [], None

        try:
            labels_df = parse_uploaded_labels(BytesIO(csv_bytes))
        except ValueError as e:
            return None, _error(f"labels.csv invalide : {e}"), [], None

        # Sérialiser pour le store
        store = {
            "by_interval": {iv: {"meta": _df_to_json(m), "candles": _df_to_json(c)} for iv, (m, c) in by_iv.items()},
            "labels": _df_to_json(labels_df),
        }

        first_iv = next(iter(by_iv.keys()))
        first_meta = by_iv[first_iv][0]
        if first_meta.empty:
            return None, _error("Archive importée vide."), [], None
        n_imp = len(first_meta)

        intervals = sorted(by_iv.keys())
        msg = html.Span(
            f"✓ Archive parsée — {n_imp} trades — intervalles : {intervals} "
            f"— labels.csv : {len(labels_df)} lignes",
            style={"color": "#2e7d32"},
        )
        return (
            store,
            msg,
            [{"label": i, "value": i} for i in intervals],
            intervals[0],
        )

    # ──────────────────────────────────────────────────────────────────
    # Import : navigation + render preview
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("import-index-store", "data"),
        Output("import-info", "children"),
        Output("import-graph", "figure"),
        Output("import-prev", "disabled"),
        Output("import-next", "disabled"),
        Input("import-prev", "n_clicks"),
        Input("import-next", "n_clicks"),
        Input("import-store", "data"),
        Input("import-viewer-interval", "value"),
        State("import-index-store", "data"),
    )
    def update_import_view(prev_n, next_n, store, viewer_iv, current_idx):
        if not store:
            return 0, "", _empty_figure(), True, True

        by_iv = store["by_interval"]
        first_iv = next(iter(by_iv.keys()))
        first_meta = _df_from_json(by_iv[first_iv]["meta"])
        if first_meta.empty:
            return 0, html.Span("Archive vide.", style={"color": "#888"}), _empty_figure(), True, True

        idx = current_idx if isinstance(current_idx, int) else 0
        n = len(first_meta)
        trigger = callback_context.triggered_id
        if trigger == "import-prev":
            idx = max(0, idx - 1)
        elif trigger == "import-next":
            idx = min(n - 1, idx + 1)
        elif trigger == "import-store":
            idx = 0
        else:
            idx = max(0, min(idx, n - 1))

        row = first_meta.iloc[idx]
        trade_id = str(row["trade_id"])
        exchange = str(row["exchange"])

        iv_to_show = viewer_iv if viewer_iv in by_iv else first_iv
        candles_df = _df_from_json(by_iv[iv_to_show]["candles"])
        sub = candles_df[candles_df["trade_id"] == trade_id].copy()
        if sub.empty:
            fig = _empty_figure()
        else:
            sub["open_time"] = pd.to_datetime(sub["open_time"])
            sub["close_time"] = pd.to_datetime(sub["close_time"])
            fig = build_figure(
                sub,
                symbol=str(row["symbol"]),
                interval=iv_to_show,
                exchange=exchange,
            )

        info = html.Span(
            f"[Import] Trade {idx + 1}/{n} — {row['label']} — {row['symbol']} ({exchange}) "
            f"— vue : {iv_to_show}",
            style={"color": "#333"},
        )
        return idx, info, fig, idx == 0, idx == n - 1

    # ──────────────────────────────────────────────────────────────────
    # Import : add the current trade to the local archive
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("export-status", "children", allow_duplicate=True),
        Input("import-add", "n_clicks"),
        State("import-store", "data"),
        State("import-index-store", "data"),
        prevent_initial_call=True,
    )
    def add_imported_to_local(n_clicks, store, current_idx):
        if not n_clicks or not store:
            return no_update
        by_iv_serialized = store["by_interval"]
        labels_df = _df_from_json(store["labels"])

        by_iv = {
            iv: (_df_from_json(d["meta"]), _df_from_json(d["candles"]))
            for iv, d in by_iv_serialized.items()
        }
        first_iv = next(iter(by_iv.keys()))
        first_meta, _ = by_iv[first_iv]
        idx = current_idx if isinstance(current_idx, int) else 0
        idx = max(0, min(idx, len(first_meta) - 1))
        row = first_meta.iloc[idx].to_dict()
        old_trade_id = str(row["trade_id"])

        try:
            new_trade_id, exchange = add_imported_trade(old_trade_id, by_iv)
        except Exception as e:
            return _error(f"Échec import : {e}")

        # labels.csv : lookup la ligne du CSV importé, sinon recompute
        warning = ""
        try:
            label_row = lookup_label_row(
                labels_df,
                symbol=str(row["symbol"]),
                exchange=exchange,
                start_utc=row["start_utc"],
                end_utc=row["end_utc"],
            )
            if label_row is None:
                # Fallback : recompute depuis les bougies locales fraîchement écrites
                ref_iv = EXCHANGE_LABEL_INTERVAL.get(exchange)
                if ref_iv is None:
                    raise ValueError(f"Exchange non supporté pour labels : {exchange}")
                ref_candles = get_trade_candles(new_trade_id, ref_iv)
                label_row = compute_label_from_local(
                    {"symbol": row["symbol"], "exchange": exchange, "trade_id": new_trade_id},
                    ref_candles,
                )
            else:
                # On garde la ligne CSV importée telle quelle (déjà validée)
                pass
            append_label(label_row)
        except Exception as e:
            warning = f" (⚠ labels.csv non mis à jour : {e})"

        status = get_status()
        return html.Span(
            f"✓ Trade importé — {status['nb_trades']} trades — fichiers : "
            f"{', '.join(status['files'])}{warning}",
            style={"color": "#2e7d32" if not warning else "#c0a000"},
        )

    # ──────────────────────────────────────────────────────────────────
    # Rebuild : CSV → fetch les 4 intervalles → ZIP en mémoire (4 xlsx + csv)
    # Workflow autonome : ne touche ni l'archive locale ni labels.csv racine.
    # ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output("rebuild-status", "children"),
        Output("rebuild-cache-id", "data"),
        Output("rebuild-download-button", "disabled"),
        Input("rebuild-button", "n_clicks"),
        State("rebuild-upload", "contents"),
        State("rebuild-upload", "filename"),
        State("rebuild-window-days", "value"),
        prevent_initial_call=True,
    )
    def rebuild_from_csv(n_clicks, contents, filename, window_days):
        if not n_clicks:
            return no_update, no_update, no_update
        if not contents:
            return _error("Upload un CSV avant de lancer."), no_update, True

        try:
            csv_bytes = _decode_upload(contents)
        except Exception as e:
            return _error(f"Lecture CSV : {e}"), no_update, True

        try:
            labels_df = parse_uploaded_labels(BytesIO(csv_bytes))
        except ValueError as e:
            return _error(f"CSV invalide : {e}"), no_update, True

        if labels_df.empty:
            return _error("CSV vide."), no_update, True

        try:
            window = pd.Timedelta(days=int(window_days or 7))
        except Exception:
            return _error(f"Fenêtre invalide : {window_days!r}"), no_update, True

        # Bucket par intervalle pour build_archives_in_memory
        trades_per_interval: dict = {}
        skipped: list[str] = []
        succeeded = 0

        for idx, row in labels_df.iterrows():
            line_no = idx + 1
            symbol_csv = str(row["symbol"])
            exchange_raw = str(row["exchange"]).strip()
            exchange_cap = exchange_raw.capitalize()
            api = AVAILABLE_APIS.get(exchange_cap)
            if api is None:
                skipped.append(f"l.{line_no} : exchange '{exchange_raw}' inconnu")
                continue

            try:
                t_ath = pd.Timestamp(row["t_ath"])
                if t_ath.tzinfo is not None:
                    t_ath = t_ath.tz_convert("UTC").tz_localize(None)
            except Exception as e:
                skipped.append(f"l.{line_no} : t_ath invalide ({e})")
                continue

            symbol_api = denormalize_symbol_for_api(symbol_csv, exchange_cap)
            start_dt = (t_ath - window).to_pydatetime()
            end_dt = (t_ath + window).to_pydatetime()

            # Fetch les 4 intervals avec retry
            try:
                per_iv = {}
                for iv in api.export_intervals:
                    df = _fetch_with_retry(api, symbol_api, iv, start_dt, end_dt)
                    if df.empty:
                        raise RuntimeError(f"aucune bougie {iv}")
                    per_iv[iv] = df
            except Exception as e:
                skipped.append(f"l.{line_no} ({symbol_csv}) : {e}")
                continue

            # Construire les meta_row + candles_df pour cette ligne
            trade_id = new_trade_id()
            label = f"{symbol_api}_{start_dt.isoformat()}_{end_dt.isoformat()}"
            for iv, candles in per_iv.items():
                meta_row = TradeMetadata(
                    trade_id=trade_id,
                    label=label,
                    exchange=exchange_cap,
                    symbol=symbol_api,
                    interval=iv,
                    start_utc=start_dt,
                    end_utc=end_dt,
                    nb_candles=len(candles),
                ).to_row()
                new_c = candles.copy()
                new_c.insert(0, "trade_id", trade_id)
                new_c["pct_change"] = (
                    (new_c["close"] - new_c["open"]) / new_c["open"] * 100
                ).round(4)
                new_c = new_c[CANDLES_COLUMNS]
                trades_per_interval.setdefault(iv, []).append((meta_row, new_c))
            succeeded += 1

        if succeeded == 0:
            details = "; ".join(skipped[:5])
            more = f" ({len(skipped) - 5} de plus)" if len(skipped) > 5 else ""
            return _error(f"Aucun trade reconstruit. Skippé : {details}{more}"), no_update, True

        # Construire les 4 xlsx en mémoire + le ZIP
        xlsx_per_iv = build_archives_in_memory(trades_per_interval)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for iv, data in xlsx_per_iv.items():
                zf.writestr(f"candles_{iv}.xlsx", data)
            zf.writestr("labels.csv", csv_bytes)
        zip_bytes = buf.getvalue()

        # Cache serveur (la callback de download relit depuis cet uuid)
        rid = uuid.uuid4().hex[:12]
        _REBUILD_CACHE[rid] = zip_bytes

        msg_parts = [f"✓ {succeeded} trade(s) reconstruit(s)"]
        if skipped:
            msg_parts.append(f"{len(skipped)} skippé(s)")
        msg = " — ".join(msg_parts)
        details = ""
        if skipped:
            details = " | détails : " + "; ".join(skipped[:5])
            if len(skipped) > 5:
                details += f" (+{len(skipped) - 5} autres)"

        return (
            html.Span(
                msg + details,
                style={"color": "#2e7d32" if not skipped else "#c0a000"},
            ),
            rid,
            False,
        )

    @app.callback(
        Output("rebuild-download", "data"),
        Input("rebuild-download-button", "n_clicks"),
        State("rebuild-cache-id", "data"),
        prevent_initial_call=True,
    )
    def rebuild_download(n_clicks, rid):
        if not n_clicks or not rid:
            return no_update
        zip_bytes = _REBUILD_CACHE.get(rid)
        if zip_bytes is None:
            return no_update
        return dcc.send_bytes(zip_bytes, "rebuild_archive.zip")

    # ──────────────────────────────────────────────────────────────────
    # Open exports folder
    # ──────────────────────────────────────────────────────────────────
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


# --------------------------------------------------------------------------- #
# Plot helpers
# --------------------------------------------------------------------------- #


def build_figure(df: pd.DataFrame, symbol: str, interval: str, exchange: str) -> go.Figure:
    colors = [BULL_COLOR if c >= o else BEAR_COLOR for o, c in zip(df["open"], df["close"])]
    pct_change = (df["close"] - df["open"]) / df["open"] * 100
    hover_text = [f"Variation: {p:+.2f}%" for p in pct_change]

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
            text=hover_text,
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
                text="Aucune donnée — charge des bougies pour commencer.",
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


_DATETIME_FORMATS = (
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _parse_datetime(raw: str | None, field: str) -> datetime:
    if not raw or not raw.strip():
        raise ValueError(f"Date de {field} manquante.")
    s = raw.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Date de {field} invalide : '{s}' (attendu JJ/MM/AAAA HH:MM)."
    )


def _error(msg: str) -> html.Span:
    return html.Span(f"⚠ {msg}", style={"color": "#c62828"})
