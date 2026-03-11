"""Flask routes — auth middleware, /connect, /disconnect, /healthz.

Extracted from main.py to keep app creation separate from HTTP plumbing.
"""

from flask import Response, g, make_response, redirect, request

from app import config as cfg

_AUTH_SKIP = ("/connect/", "/disconnect", "/_dash-component-suites/",
              "/_dash-dependencies", "/assets/", "/_reload-hash")


def register(server):
    """Attach all routes and middleware to the Flask server."""

    @server.before_request
    def auth_middleware():
        g.client_id = None
        g.client_name = None
        if not cfg.AWS_MODE:
            g.client_id = "demo_client_1"
            g.client_name = "Demo Facility"
            return None
        path = request.path
        if any(path.startswith(p) for p in _AUTH_SKIP):
            return None
        from app.auth import COOKIE_NAME, COOKIE_SECRET, validate_token_hint, verify_cookie
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

    @server.route("/connect/<token>")
    def connect(token: str):
        if not cfg.AWS_MODE:
            return redirect("/")
        from app.auth import COOKIE_MAX_AGE, COOKIE_NAME, create_cookie, resolve_token
        client = resolve_token(token)
        if not client:
            return _expired_page("Invalid or expired access link.")
        cookie_val = create_cookie(client["client_id"], client["client_name"], token[:8])
        resp = redirect("/")
        resp.set_cookie(COOKIE_NAME, cookie_val, max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="Lax", secure=request.scheme == "https")
        return resp

    @server.route("/disconnect")
    def disconnect():
        from app.auth import COOKIE_NAME
        resp = redirect("/connect/none")
        resp.delete_cookie(COOKIE_NAME)
        return resp

    @server.route("/healthz")
    def healthz():
        import json
        import time as _t
        result = {"mysql": "untested", "provider": "untested"}
        try:
            t0 = _t.time()
            from app.data.mysql_reader import warmup
            warmup()
            result["mysql"] = f"OK in {_t.time()-t0:.2f}s"
        except Exception as exc:
            result["mysql"] = f"FAIL: {exc}"
        try:
            t0 = _t.time()
            from app.data.provider import get_provider
            states = get_provider("demo_client_1").get_all_sensor_states()
            result["provider"] = f"OK ({len(states)} sensors) in {_t.time()-t0:.2f}s"
        except Exception as exc:
            result["provider"] = f"FAIL: {exc}"
        return Response(json.dumps(result, indent=2), mimetype="application/json")


def _expired_page(msg: str = "Your session has expired") -> Response:
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TempMonitor</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:{cfg.COLORS['bg']};font-family:'DM Sans',system-ui,sans-serif;color:{cfg.COLORS['text']};}}
.card{{background:{cfg.COLORS['card']};border:1px solid {cfg.COLORS['card_border']};
border-radius:16px;padding:48px 40px;text-align:center;max-width:420px;box-shadow:0 8px 32px rgba(0,0,0,0.5);}}
.logo{{font-size:1.3rem;margin-bottom:24px;}}.logo b{{color:{cfg.COLORS['primary']};letter-spacing:1px;}}
h2{{color:{cfg.COLORS['warning']};font-size:1.1rem;margin:0 0 12px;}}
p{{color:{cfg.COLORS['text_muted']};font-size:0.88rem;line-height:1.5;margin:0;}}
</style></head><body><div class="card"><div class="logo"><b>TEMP</b><span>MONITOR</span></div>
<h2>{msg}</h2><p>Please use the access link provided by your facility administrator.</p>
</div></body></html>"""
    return make_response(body, 200)
