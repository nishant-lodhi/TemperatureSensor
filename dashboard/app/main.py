"""TempMonitor Dashboard — app creation, layout, clock."""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html

from app import config as cfg
from app.routes import register

app = dash.Dash(
    __name__, use_pages=True, pages_folder="pages",
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap",
    ],
    suppress_callback_exceptions=True, title="TempMonitor", update_title=None, url_base_pathname="/",
)

server = app.server
register(server)

_F = "'DM Sans', system-ui, sans-serif"

navbar = dbc.Navbar(
    dbc.Container([
        dbc.NavbarBrand([
            html.Span("\u2B22 ", style={"color": cfg.COLORS["primary"], "fontSize": "1.4rem"}),
            html.Span("TEMP", style={"fontWeight": "700", "color": cfg.COLORS["primary"], "letterSpacing": "1px"}),
            html.Span("MONITOR", style={"fontWeight": "400", "color": cfg.COLORS["text"], "letterSpacing": "1px"}),
            html.Span(id="client-badge"),
        ], href="/", style={"fontSize": "1.15rem"}),
        html.Div([
            html.Span(id="live-clock", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.8rem"}),
            html.Span(" \u25CF LIVE", style={"color": cfg.COLORS["success"], "fontSize": "0.6rem",
                       "fontWeight": "700", "marginLeft": "10px",
                       "textShadow": f"0 0 8px {cfg.COLORS['success']}"}),
        ]),
    ], fluid=True),
    color=cfg.COLORS["bg"], dark=True,
    style={"borderBottom": f"1px solid {cfg.COLORS['card_border']}", "position": "sticky", "top": "0", "zIndex": "999"},
)

app.layout = html.Div([
    dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    navbar,
    dbc.Container(dash.page_container, fluid=True, className="px-3 pt-3"),
], style={"backgroundColor": cfg.COLORS["bg"], "minHeight": "100vh", "fontFamily": _F, "color": cfg.COLORS["text"]})


@app.callback(Output("live-clock", "children"), Output("client-badge", "children"), Input("clock-interval", "n_intervals"))
def update_clock(_):
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%b %d, %Y  %H:%M:%S UTC"), ""


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        from app.data.mysql_reader import warmup
        warmup()
    except Exception as exc:
        logging.getLogger(__name__).warning("MySQL warm-up failed: %s", exc)
    app.run(debug=False, host="0.0.0.0", port=8051)
