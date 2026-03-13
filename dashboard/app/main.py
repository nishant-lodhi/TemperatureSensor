"""TempMonitor Dashboard — app creation, layout, clock."""
# from dotenv import load_dotenv  # noqa: E402, I001
# load_dotenv()

import logging  # noqa: E402
import os  # noqa: E402

import dash  # noqa: E402
import dash_bootstrap_components as dbc  # noqa: E402
from dash import Input, Output, dcc, html  # noqa: E402

from app import config as cfg  # noqa: E402
from app.routes import register  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("tempsensor")

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

logger.info("APP_INIT env=%s src=%s aws=%s",
            os.environ.get("ENVIRONMENT", "local"),
            os.environ.get("DATA_SOURCE", "mysql"),
            cfg.AWS_MODE)

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


_clock_offset = None


@app.callback(
    Output("live-clock", "children"),
    Output("client-badge", "children"),
    Input("clock-interval", "n_intervals"),
)
def update_clock(_):
    """Tick every second — update navbar clock and client badge."""
    from datetime import datetime, timezone
    global _clock_offset
    if _clock_offset is None:
        try:
            from app.auth import get_client_id
            from app.data.provider import get_provider
            prov = get_provider(get_client_id())
            db_now = prov.get_db_time()
            if db_now:
                _clock_offset = db_now - datetime.now(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    display = utc_now + _clock_offset if _clock_offset else utc_now
    label = "Local" if _clock_offset else "UTC"
    return (
        display.strftime(f"%b %d, %Y  %H:%M:%S {label}"),
        "",
    )


if __name__ == "__main__":
    try:
        from app.data.mysql_reader import warmup
        warmup()
    except Exception as exc:
        logger.warning("MySQL warm-up failed: %s", exc)
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", "8051")))
