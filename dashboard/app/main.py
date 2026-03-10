"""TempMonitor Dashboard — 2-tab layout with multi-tenant auth."""

import os

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html
from flask import Response, g, make_response, redirect, request

from app import config as cfg

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap",
    ],
    suppress_callback_exceptions=True,
    title="TempMonitor",
    update_title=None,
    url_base_pathname="/",
)

server = app.server

# ---------------------------------------------------------------------------
#  Auth: /connect/<token>, /disconnect, before_request middleware
# ---------------------------------------------------------------------------
_AUTH_SKIP_PREFIXES = ("/connect/", "/disconnect", "/_dash-component-suites/", "/_dash-dependencies", "/assets/", "/_reload-hash")


@server.route("/connect/<token>")
def connect(token: str):
    """Resolve access token via Secrets Manager, set signed cookie, redirect to /."""
    if not cfg.AWS_MODE:
        resp = redirect("/")
        return resp

    from app.auth import COOKIE_MAX_AGE, COOKIE_NAME, create_cookie, resolve_token

    client = resolve_token(token)
    if not client:
        return _expired_page("Invalid or expired access link.")

    cookie_val = create_cookie(client["client_id"], client["client_name"], token[:8])
    resp = redirect("/")
    resp.set_cookie(
        COOKIE_NAME, cookie_val,
        max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax",
        secure=request.scheme == "https",
    )
    return resp


@server.route("/disconnect")
def disconnect():
    """Clear auth cookie (for admin/testing)."""
    from app.auth import COOKIE_NAME
    resp = redirect("/connect/none")
    resp.delete_cookie(COOKIE_NAME)
    return resp


@server.before_request
def auth_middleware():
    """Verify cookie, set g.client_id / g.client_name. Skip in mock mode."""
    g.client_id = None
    g.client_name = None

    if not cfg.AWS_MODE:
        g.client_id = "demo_client_1"
        g.client_name = "Demo Facility"
        return None

    path = request.path
    if any(path.startswith(p) for p in _AUTH_SKIP_PREFIXES):
        return None

    from app.auth import (
        COOKIE_NAME,
        COOKIE_SECRET,
        validate_token_hint,
        verify_cookie,
    )

    cookie_val = request.cookies.get(COOKIE_NAME)
    if not cookie_val:
        return _expired_page()

    payload = verify_cookie(cookie_val, COOKIE_SECRET)
    if not payload:
        resp = make_response(_expired_page())
        resp.delete_cookie(COOKIE_NAME)
        return resp

    if not validate_token_hint(payload["client_id"], payload["token_hint"]):
        resp = make_response(_expired_page("Your access link has been updated."))
        resp.delete_cookie(COOKIE_NAME)
        return resp

    g.client_id = payload["client_id"]
    g.client_name = payload["client_name"]
    return None


def _expired_page(msg: str = "Your session has expired") -> Response:
    """Branded HTML page shown when auth fails — no technical jargon."""
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TempMonitor</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:{cfg.COLORS['bg']}; font-family:'DM Sans',system-ui,sans-serif; color:{cfg.COLORS['text']}; }}
  .card {{ background:{cfg.COLORS['card']}; border:1px solid {cfg.COLORS['card_border']};
           border-radius:16px; padding:48px 40px; text-align:center; max-width:420px;
           box-shadow:0 8px 32px rgba(0,0,0,0.5); }}
  .logo {{ font-size:1.3rem; margin-bottom:24px; }}
  .logo b {{ color:{cfg.COLORS['primary']}; letter-spacing:1px; }}
  .logo span {{ color:{cfg.COLORS['text']}; letter-spacing:1px; font-weight:400; }}
  h2 {{ color:{cfg.COLORS['warning']}; font-size:1.1rem; margin:0 0 12px; }}
  p {{ color:{cfg.COLORS['text_muted']}; font-size:0.88rem; line-height:1.5; margin:0; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><b>TEMP</b><span>MONITOR</span></div>
  <h2>{msg}</h2>
  <p>Please use the access link provided by your facility administrator to connect.</p>
  <p style="margin-top:16px;font-size:0.78rem;">If you continue to see this message, contact your system administrator.</p>
</div>
</body></html>"""
    return make_response(body, 200)


# ---------------------------------------------------------------------------
#  Navbar — shows client name when authenticated
# ---------------------------------------------------------------------------
navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.NavbarBrand(
                [
                    html.Span("\u2B22 ", style={"color": cfg.COLORS["primary"], "fontSize": "1.4rem"}),
                    html.Span("TEMP", style={"fontWeight": "700", "color": cfg.COLORS["primary"], "letterSpacing": "1px"}),
                    html.Span("MONITOR", style={"fontWeight": "400", "color": cfg.COLORS["text"], "letterSpacing": "1px"}),
                    html.Span(id="client-badge"),
                ],
                href="/",
                style={"fontSize": "1.15rem"},
            ),
            dbc.Nav(
                [
                    dbc.NavLink(
                        "\u25C9  Live Monitor", href="/", active="exact",
                        style={"fontSize": "0.9rem", "padding": "8px 20px", "fontWeight": "500"},
                    ),
                    dbc.NavLink(
                        "\u2630  History & Reports", href="/history", active="exact",
                        style={"fontSize": "0.9rem", "padding": "8px 20px", "fontWeight": "500"},
                    ),
                ],
                navbar=True,
                className="mx-auto",
            ),
            html.Div([
                html.Span(id="live-clock", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.8rem"}),
                html.Span(
                    " \u25CF LIVE",
                    style={"color": cfg.COLORS["success"], "fontSize": "0.6rem", "fontWeight": "700",
                           "marginLeft": "10px", "textShadow": f"0 0 8px {cfg.COLORS['success']}"},
                ),
            ]),
        ],
        fluid=True,
    ),
    color=cfg.COLORS["bg"],
    dark=True,
    style={"borderBottom": f"1px solid {cfg.COLORS['card_border']}", "position": "sticky",
           "top": "0", "zIndex": "999"},
)

app.layout = html.Div(
    [
        dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
        navbar,
        dbc.Container(dash.page_container, fluid=True, className="px-3 pt-3"),
    ],
    style={"backgroundColor": cfg.COLORS["bg"], "minHeight": "100vh",
           "fontFamily": "'DM Sans', system-ui, sans-serif", "color": cfg.COLORS["text"]},
)


@app.callback(
    Output("live-clock", "children"),
    Output("client-badge", "children"),
    Input("clock-interval", "n_intervals"),
)
def update_clock(_):
    from datetime import datetime, timezone

    clock = datetime.now(timezone.utc).strftime("%b %d, %Y  %H:%M:%S UTC")
    badge = ""
    return clock, badge


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8051)
