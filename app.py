from __future__ import annotations

from dash import Dash

from ui.callbacks import register_callbacks
from ui.layout import build_layout


def create_app() -> Dash:
    app = Dash(__name__, title="Candle Visualizer")
    app.layout = build_layout()
    register_callbacks(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
