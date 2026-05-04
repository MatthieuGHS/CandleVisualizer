from __future__ import annotations

import os

from dash import Dash

from ui.callbacks import register_callbacks
from ui.layout import build_layout


def create_app() -> Dash:
    app = Dash(__name__, title="Candle Visualizer")
    app.layout = build_layout()
    register_callbacks(app)
    return app


app = create_app()
# Exposé pour gunicorn (`gunicorn app:server`).
server = app.server


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("DASH_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=port)
