"""TempMonitor Dashboard — app creation, layout, clock."""

import os

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html

from app import config as cfg
from app.routes import register

app = dash.Dash(
    __name__, use_pages=True, pages_folder="pages",
    external_stylesheets=[
        dbc.themes.FLATLY,
        ("https://fonts.googleapis.com/css2?"
         "family=Inter:wght@400;500;600;700&display=swap"),
    ],
    suppress_callback_exceptions=True,
    title="TempMonitor", update_title=None, url_base_pathname="/",
)

server = app.server
register(server)

_F = "'Inter', 'DM Sans', system-ui, sans-serif"

navbar = dbc.Navbar(
    dbc.Container([
        dbc.NavbarBrand([
            html.Span("\u25C9 ", style={
                "color": "#14b8a6", "fontSize": "1.2rem",
            }),
            html.Span("TEMP", style={
                "fontWeight": "700", "color": "#ffffff",
                "letterSpacing": "1.5px", "fontSize": "0.95rem",
            }),
            html.Span("MONITOR", style={
                "fontWeight": "400", "color": "rgba(255,255,255,0.7)",
                "letterSpacing": "1.5px", "fontSize": "0.95rem",
            }),
            html.Span(id="client-badge"),
        ], href="/"),
        html.Div([
            html.Span(id="live-clock", style={
                "color": "rgba(255,255,255,0.6)", "fontSize": "0.78rem",
            }),
            html.Span(" \u25CF LIVE", style={
                "color": "#22c55e", "fontSize": "0.6rem",
                "fontWeight": "700", "marginLeft": "10px",
            }),
        ]),
    ], fluid=True),
    style={
        "backgroundColor": cfg.COLORS["header_bg"],
        "borderBottom": "none",
        "position": "sticky", "top": "0",
        "zIndex": "999",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.08)",
        "padding": "6px 0",
    },
    dark=True,
)

app.layout = html.Div([
    dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    navbar,
    dbc.Container(
        dash.page_container, fluid=True,
        className="px-3 pt-3",
    ),
], style={
    "backgroundColor": cfg.COLORS["bg"],
    "minHeight": "100vh",
    "fontFamily": _F,
    "color": cfg.COLORS["text"],
})


@app.callback(
    Output("live-clock", "children"),
    Output("client-badge", "children"),
    Input("clock-interval", "n_intervals"),
)
def update_clock(_):
    """Tick every second — update navbar clock and client badge."""
    from datetime import datetime, timezone
    return (
        datetime.now(timezone.utc).strftime("%b %d, %Y  %H:%M:%S UTC"),
        "",
    )


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        from app.data.mysql_reader import warmup
        warmup()
    except Exception as exc:
        logging.getLogger(__name__).warning("MySQL warm-up failed: %s", exc)
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "8051")))
