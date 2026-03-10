"""Page 1: Live Monitor — horizontal sensor grid + detail below."""

from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
from dash import Input, Output, callback, ctx, dcc, html, no_update

from app import config as cfg
from app.auth import get_client_id
from app.data.provider import get_provider

dash.register_page(__name__, path="/", name="Live Monitor")

_F = "'DM Sans', system-ui, sans-serif"


def layout(**kwargs):
    return html.Div([
        dcc.Interval(id="mon-tick", interval=cfg.REFRESH_MONITOR_MS),
        dcc.Store(id="mon-selected", data=None),
        dcc.Store(id="mon-show-alerts", data=False),
        html.Div(id="mon-banner"),
        html.Div(id="mon-alert-drawer"),
        html.Div(id="mon-grid"),
        html.Div(id="mon-detail"),
    ])


@callback(Output("mon-banner", "children"), Input("mon-tick", "n_intervals"))
def update_banner(_):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    alerts = prov.get_active_alerts()
    total = len(states)
    online = sum(1 for s in states if s.get("status") != "offline")
    temps = [s.get("temperature", 0) for s in states if s.get("status") != "offline"]
    avg = float(np.mean(temps)) if temps else 0
    low_bat = sum(1 for s in states if s.get("battery_pct", 100) < cfg.BATTERY_LOW and s.get("status") != "offline")

    if any([avg >= cfg.TEMP_CRITICAL_HIGH, len(alerts) >= 5]):
        label, color, bg = "ACTION REQUIRED", cfg.COLORS["danger"], cfg.COLORS["danger_dim"]
    elif any([avg >= cfg.TEMP_HIGH, avg <= cfg.TEMP_LOW, len(alerts) > 0, low_bat > 0]):
        label, color, bg = "NEEDS ATTENTION", cfg.COLORS["warning"], cfg.COLORS["warning_dim"]
    else:
        label, color, bg = "ALL CLEAR", cfg.COLORS["success"], cfg.COLORS["success_dim"]

    a_color = cfg.COLORS["danger"] if alerts else cfg.COLORS["success"]
    alert_pill = html.Div([
        html.Span(str(len(alerts)), style={"color": a_color, "fontWeight": "700", "fontSize": "1.05rem", "marginRight": "4px"}),
        html.Span("Alerts", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.72rem"}),
    ], id="banner-alert-btn", n_clicks=0,
       style={"cursor": "pointer", "padding": "2px 10px", "borderRadius": "8px",
              "border": f"1px solid {a_color if alerts else 'transparent'}", "transition": "background 0.2s"})

    return html.Div([
        dbc.Row([
            dbc.Col(html.Div([
                html.H1(label, style={"color": color, "fontWeight": "700", "fontSize": "1.3rem", "letterSpacing": "2px", "margin": 0, "fontFamily": _F}),
                html.Span(id="facility-name-label", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.75rem", "fontFamily": _F}),
            ]), lg=4),
            dbc.Col(html.Div([
                _pill(f"{online}/{total}", "Sensors", cfg.COLORS["success"] if online == total else cfg.COLORS["warning"]),
                alert_pill,
                _pill(f"{avg:.1f}°F", "Avg Temp", cfg.COLORS["primary"]),
                _pill(str(low_bat), "Low Battery", cfg.COLORS["danger"] if low_bat else cfg.COLORS["success"]),
            ], className="d-flex gap-3 flex-wrap justify-content-end align-items-center"), lg=8),
        ], className="align-items-center"),
    ], style={**cfg.CARD_STYLE, "backgroundColor": bg, "padding": "12px 18px", "marginBottom": "10px"})


def _pill(v, l, c):
    return html.Div([
        html.Span(v, style={"color": c, "fontWeight": "700", "fontSize": "1.05rem", "marginRight": "4px"}),
        html.Span(l, style={"color": cfg.COLORS["text_muted"], "fontSize": "0.72rem"}),
    ])


@callback(Output("mon-show-alerts", "data"), Input("banner-alert-btn", "n_clicks"), prevent_initial_call=True)
def toggle_alerts(n):
    return n % 2 == 1 if n else False


@callback(Output("mon-alert-drawer", "children"), Input("mon-show-alerts", "data"), Input("mon-tick", "n_intervals"))
def render_alert_drawer(show, _):
    if not show:
        return html.Div()
    prov = get_provider(get_client_id())
    alerts = prov.get_active_alerts()
    if not alerts:
        return html.Div("No active alerts", style={**cfg.CARD_STYLE, "padding": "12px 16px", "marginBottom": "10px",
                                                     "color": cfg.COLORS["success"], "fontSize": "0.85rem", "fontFamily": _F})
    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "WARNING": 3}
    items = []
    for a in sorted(alerts, key=lambda x: _sev_order.get(x.get("severity", ""), 9)):
        sev, sc = a.get("severity", ""), cfg.SEVERITY_COLORS.get(a.get("severity", ""), cfg.COLORS["text_muted"])
        items.append(html.Div([
            html.Div([html.Span(cfg.SEVERITY_LABELS.get(sev, sev), style={"backgroundColor": sc, "color": "#fff",
                      "padding": "2px 10px", "borderRadius": "10px", "fontSize": "0.65rem", "fontWeight": "700", "marginRight": "8px"}),
                html.Span(a.get("device_id", ""), style={"fontFamily": "monospace", "fontSize": "0.75rem", "color": cfg.COLORS["text_muted"], "marginRight": "auto"}),
                html.Span(_fmt_time(a.get("triggered_at", "")), style={"fontSize": "0.68rem", "color": cfg.COLORS["text_muted"]})],
                style={"display": "flex", "alignItems": "center", "gap": "4px"}),
            html.Div(a.get("message", ""), style={"fontSize": "0.82rem", "color": cfg.COLORS["text"], "marginTop": "4px", "fontFamily": _F}),
        ], style={**cfg.CARD_STYLE, "padding": "10px 14px", "marginBottom": "6px", "borderLeft": f"3px solid {sc}"}))
    return html.Div([html.Div(html.Span(f"\u26A0 {len(alerts)} Active Alerts", style={"fontWeight": "700", "fontSize": "0.88rem",
        "color": cfg.COLORS["warning"], "fontFamily": _F}), style={"marginBottom": "8px"}), *items], style={"marginBottom": "10px"})


@callback(Output("mon-grid", "children"), Input("mon-tick", "n_intervals"), Input("mon-selected", "data"))
def update_grid(_, selected_id):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    alert_devices = {a.get("device_id") for a in prov.get_active_alerts()}

    def _sort(s):
        has_issue = s["device_id"] in alert_devices or s.get("anomaly", False) or s.get("status") == "offline" or s.get("temperature", 0) >= cfg.TEMP_HIGH or s.get("temperature", 0) <= cfg.TEMP_LOW
        return (0 if has_issue else 1, -s.get("temperature", 0))

    states.sort(key=_sort)
    tiles = []
    for s in states:
        temp, did, st = s.get("temperature", 0), s["device_id"], s.get("status", "online")
        anom, bat, sig = s.get("anomaly", False), s.get("battery_pct", 100), s.get("signal_label", "Good")
        has_alert = did in alert_devices

        if st == "offline": c = cfg.COLORS["text_muted"]
        elif temp >= cfg.TEMP_HIGH or temp <= cfg.TEMP_LOW or has_alert: c = cfg.COLORS["danger"]
        elif anom: c = cfg.COLORS["warning"]
        else: c = cfg.COLORS["success"]

        bat_c = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["text_muted"])
        sig_icon = cfg.SIGNAL_ICONS.get(sig, "")
        badge = html.Span(" \u26A0", style={"color": cfg.COLORS["warning"], "fontSize": "0.6rem"}) if (anom or has_alert) else ""
        temp_display = f"{temp:.1f}°F" if st != "offline" else f"{temp:.1f}°F*"

        is_selected = did == selected_id
        sel_style = {
            "boxShadow": f"0 0 0 2px {cfg.COLORS['primary']}" if is_selected else cfg.CARD_STYLE.get("boxShadow", "none"),
            "transform": "scale(1.05)" if is_selected else "none",
            "zIndex": "2" if is_selected else "auto",
        }
        tile = html.Div([
            html.Div([
                html.Span("\u25CF ", style={"color": c, "fontSize": "0.55rem"}),
                html.Span(did, style={"fontFamily": "monospace", "fontSize": "0.6rem", "color": cfg.COLORS["text_muted"]}),
                badge,
            ], style={"lineHeight": "1.2", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}),
            html.Div(temp_display, style={"fontWeight": "700", "fontSize": "1rem", "color": c, "lineHeight": "1.3", "fontFamily": _F}),
            html.Div([
                html.Span(f"\U0001F50B{bat}%", style={"fontSize": "0.55rem", "color": bat_c, "marginRight": "5px"}),
                html.Img(src=sig_icon, style={"height": "12px", "verticalAlign": "middle"}),
            ], style={"lineHeight": "1.2"}),
        ], id={"type": "sensor-card", "index": did}, n_clicks=0, style={
            **cfg.CARD_STYLE, "borderTop": f"3px solid {c}", "padding": "7px 10px", "cursor": "pointer",
            "width": "130px", "textAlign": "center", "transition": "all 0.15s", **sel_style,
        })
        tiles.append(tile)

    header = html.Div(html.Span(f"\u2609 {len(states)} Sensors", style={"fontWeight": "600", "fontSize": "0.8rem", "color": cfg.COLORS["text_muted"], "fontFamily": _F}),
                       style={"marginBottom": "6px"})
    grid = html.Div(tiles, style={"display": "flex", "flexWrap": "wrap", "gap": "7px", "maxHeight": "220px", "overflowY": "auto", "paddingBottom": "4px"})
    return html.Div([header, grid], style={"marginBottom": "12px"})


@callback(Output("mon-selected", "data"), Input({"type": "sensor-card", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def select_sensor(clicks):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    triggered = ctx.triggered_id
    return triggered["index"] if triggered and isinstance(triggered, dict) else no_update


@callback(Output("mon-detail", "children"), Input("mon-selected", "data"), Input("mon-tick", "n_intervals"))
def update_detail(selected_id, _):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    if not selected_id:
        selected_id = states[0]["device_id"] if states else None
    if not selected_id:
        return html.P("No sensors available", style={"color": cfg.COLORS["text_muted"], "fontFamily": _F})
    state = next((s for s in states if s["device_id"] == selected_id), None)
    if not state:
        return html.P("Sensor not found", style={"color": cfg.COLORS["text_muted"], "fontFamily": _F})

    temp = float(state.get("temperature") or 0)
    hi = float(state.get("actual_high_1h") or temp)
    lo = float(state.get("actual_low_1h") or temp)
    roc = float(state.get("rate_of_change") or 0)
    bat = float(state.get("battery_pct") or 0)
    sig = state.get("signal_label") or "Good"
    dbm = float(state.get("signal_dbm") or -50)
    anomaly = bool(state.get("anomaly"))
    reason = state.get("anomaly_reason")
    st = state.get("status") or "online"
    last_seen = state.get("last_seen", "")

    if st == "offline": cond, cc = "Offline", cfg.COLORS["text_muted"]
    elif temp >= cfg.TEMP_HIGH: cond, cc = "Too Warm", cfg.COLORS["danger"]
    elif temp <= cfg.TEMP_LOW: cond, cc = "Too Cold", cfg.COLORS["primary_light"]
    else: cond, cc = "Comfortable", cfg.COLORS["success"]

    trend = "\u2191 Rising" if roc > 0.5 else ("\u2193 Falling" if roc < -0.5 else "\u2192 Steady")
    tc = cfg.COLORS["warning"] if roc > 0.5 else (cfg.COLORS["primary_light"] if roc < -0.5 else cfg.COLORS["success"])
    sc = cfg.COLORS["success"] if st == "online" else cfg.COLORS["text_muted"]
    bc = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["success"])
    sig_icon = cfg.SIGNAL_ICONS.get(sig, "")

    last_seen_text = ""
    if st == "offline" and last_seen:
        last_seen_text = f" \u2022 Last seen: {_fmt_time(last_seen)}"

    header = dbc.Row([
        dbc.Col(html.Div([
            html.Span(f"\u25CF {st.upper()}", style={"color": sc, "fontWeight": "600", "fontSize": "0.72rem", "fontFamily": _F}),
            html.Span(f"  {selected_id}", style={"fontFamily": "monospace", "color": cfg.COLORS["text_muted"], "fontSize": "0.82rem"}),
            html.Span(last_seen_text, style={"color": cfg.COLORS["warning"], "fontSize": "0.68rem", "fontFamily": _F}) if last_seen_text else "",
        ]), width="auto"),
        dbc.Col(html.Div([
            html.Span(f"{temp:.1f}°F", style={"color": cc, "fontWeight": "700", "fontSize": "1.8rem", "marginRight": "10px", "fontFamily": _F}),
            html.Span(cond, style={"color": cc, "fontWeight": "600", "fontSize": "0.85rem", "fontFamily": _F}),
        ]), width="auto"),
    ], className="align-items-center mb-2 g-3")

    tiles_data = [
        ("1h High", f"{hi:.1f}°F", cfg.COLORS["danger"] if hi > cfg.TEMP_HIGH else cfg.COLORS["text"]),
        ("1h Low", f"{lo:.1f}°F", cfg.COLORS["primary_light"] if lo < cfg.TEMP_LOW else cfg.COLORS["text"]),
        ("Trend", trend if st == "online" else "N/A", tc if st == "online" else cfg.COLORS["text_muted"]),
        ("Battery", f"{bat}%" if st == "online" else "N/A", bc if st == "online" else cfg.COLORS["text_muted"]),
    ]
    sig_tile = _wifi_tile(sig, sig_icon, cfg.COLORS["success"] if sig in ("Strong", "Good") else cfg.COLORS["warning"])
    dbm_tile = _tile("dBm", str(dbm), cfg.COLORS["text_muted"])
    info = dbc.Row([*[dbc.Col(_tile(*t), xs=4, md=2) for t in tiles_data],
                     dbc.Col(sig_tile, xs=4, md=2), dbc.Col(dbm_tile, xs=4, md=2)], className="g-2 mb-2")

    anom_box = html.Div()
    if anomaly and reason:
        anom_box = html.Div([
            html.Span("\u26A0 Anomaly: ", style={"fontWeight": "700", "color": cfg.COLORS["warning"], "fontFamily": _F}),
            html.Span(reason, style={"color": cfg.COLORS["text"], "fontFamily": _F}),
        ], style={**cfg.CARD_STYLE, "backgroundColor": cfg.COLORS["warning_dim"],
                  "borderLeft": f"3px solid {cfg.COLORS['warning']}", "padding": "8px 12px", "marginBottom": "10px", "fontSize": "0.82rem"})

    if st == "online":
        chart = _chart(prov, selected_id)
    else:
        chart = _chart_offline(prov, selected_id, last_seen)

    all_alerts = prov.get_active_alerts()
    facility_alerts = sorted(all_alerts, key=lambda a: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "WARNING": 3}.get(a.get("severity", ""), 9))
    alert_items = [_arow(a, selected_id) for a in facility_alerts[:8]]
    alerts_sec = html.Div([
        html.H6(f"Active Alerts ({len(all_alerts)})", style={"color": cfg.COLORS["text_muted"], "fontWeight": "600", "fontSize": "0.8rem", "marginBottom": "8px", "fontFamily": _F}),
        html.Div(alert_items) if alert_items else html.Span("No active alerts", style={"color": cfg.COLORS["success"], "fontSize": "0.82rem", "fontFamily": _F}),
    ], style={**cfg.CARD_STYLE, "padding": "12px 14px"})

    return html.Div([header, info, anom_box, chart, alerts_sec])


def _arow(a, sel):
    sev = a.get("severity", "")
    c = cfg.SEVERITY_COLORS.get(sev, cfg.COLORS["text_muted"])
    did = a.get("device_id", "")
    is_selected = did == sel
    return html.Div([
        html.Span(cfg.SEVERITY_LABELS.get(sev, sev), style={"backgroundColor": c, "color": "#fff", "padding": "1px 8px", "borderRadius": "10px", "fontSize": "0.6rem", "fontWeight": "700", "marginRight": "6px"}),
        html.Span(did[-8:], style={"fontFamily": "monospace", "fontSize": "0.68rem", "color": cfg.COLORS["primary"] if is_selected else cfg.COLORS["text_muted"], "marginRight": "6px", "fontWeight": "700" if is_selected else "400"}),
        html.Span(a.get("message", "")[:40], style={"fontSize": "0.78rem", "fontFamily": _F, "color": cfg.COLORS["text"]}),
    ], style={"marginBottom": "5px", "padding": "4px 0", "borderLeft": f"2px solid {cfg.COLORS['primary'] if is_selected else 'transparent'}", "paddingLeft": "8px" if is_selected else "10px"})


def _chart(prov, device_id):
    now = datetime.now(timezone.utc)
    readings = prov.get_readings(device_id, (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:00Z"))
    h_ts, h_t = [r["timestamp"] for r in readings], [r["temperature"] for r in readings]
    fc = prov.get_forecast_series(device_id, "30min", 30)
    f_ts = [f["timestamp"] for f in fc]
    fig = go.Figure()
    a_ts = h_ts + f_ts
    if a_ts:
        fig.add_trace(go.Scatter(x=[a_ts[0], a_ts[-1], a_ts[-1], a_ts[0]], y=[cfg.TEMP_LOW]*2 + [cfg.TEMP_HIGH]*2,
                                 fill="toself", fillcolor=cfg.COLORS["safe_zone"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=h_ts, y=h_t, mode="lines", name="Actual", line=dict(color=cfg.COLORS["primary"], width=2.5)))
    if f_ts:
        f_pred = [f["predicted"] for f in fc]
        f_upper = [f["ci_upper"] for f in fc]
        f_lower = [f["ci_lower"] for f in fc]
        if h_ts and h_t:
            bridge_ts, bridge_val = h_ts[-1], h_t[-1]
            f_ts = [bridge_ts] + f_ts
            f_pred = [bridge_val] + f_pred
            f_upper = [bridge_val] + f_upper
            f_lower = [bridge_val] + f_lower
        fig.add_trace(go.Scatter(x=f_ts, y=f_upper, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=f_ts, y=f_lower, fill="tonexty", fillcolor=cfg.COLORS["primary_dim"], line=dict(width=0), name="Forecast Range"))
        fig.add_trace(go.Scatter(x=f_ts, y=f_pred, mode="lines", name="Forecast", line=dict(color=cfg.COLORS["primary_light"], width=2, dash="dot")))
    fig.add_hline(y=cfg.TEMP_HIGH, line_dash="dot", line_color=cfg.COLORS["danger"], line_width=1, annotation_text="Too Hot", annotation_font_color=cfg.COLORS["danger"], annotation_font_size=9)
    fig.add_hline(y=cfg.TEMP_LOW, line_dash="dot", line_color=cfg.COLORS["primary_light"], line_width=1, annotation_text="Too Cold", annotation_font_color=cfg.COLORS["primary_light"], annotation_font_size=9)
    if h_ts and f_ts:
        fig.add_shape(type="line", x0=h_ts[-1], x1=h_ts[-1], y0=0, y1=1, yref="paper", line=dict(dash="dash", color=cfg.COLORS["text_muted"], width=1))
        fig.add_annotation(x=h_ts[-1], y=1, yref="paper", text="Now", showarrow=False, font=dict(color=cfg.COLORS["text_muted"], size=9), yshift=8)
    fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, plot_bgcolor=cfg.CHART_PLOT_BG,
                      font=cfg.CHART_FONT, height=270, margin=dict(l=40, r=10, t=20, b=28), hovermode="x unified", hoverlabel=cfg.HOVER_LABEL,
                      xaxis=dict(gridcolor=cfg.CHART_GRID_COLOR), yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, title="°F"),
                      legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=9)))
    return dbc.Card(dcc.Graph(figure=fig, config={"displayModeBar": False}), style=cfg.CARD_STYLE, className="mb-2")


def _chart_offline(prov, device_id, last_seen_iso):
    """Chart for offline sensors: show last 2h of data before the sensor went offline."""
    try:
        anchor = datetime.fromisoformat(last_seen_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return html.Div("No chart — sensor offline, no last_seen data.",
                         style={**cfg.CARD_STYLE, "padding": "20px", "textAlign": "center",
                                "color": cfg.COLORS["text_muted"], "fontSize": "0.85rem", "fontFamily": _F, "marginBottom": "10px"})
    readings = prov.get_readings(device_id, (anchor - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:00Z"))
    if not readings:
        return html.Div("No historical data available for this sensor.",
                         style={**cfg.CARD_STYLE, "padding": "20px", "textAlign": "center",
                                "color": cfg.COLORS["text_muted"], "fontSize": "0.85rem", "fontFamily": _F, "marginBottom": "10px"})
    h_ts = [r["timestamp"] for r in readings]
    h_t = [r["temperature"] for r in readings]
    fig = go.Figure()
    if h_ts:
        fig.add_trace(go.Scatter(x=[h_ts[0], h_ts[-1], h_ts[-1], h_ts[0]], y=[cfg.TEMP_LOW]*2 + [cfg.TEMP_HIGH]*2,
                                 fill="toself", fillcolor=cfg.COLORS["safe_zone"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=h_ts, y=h_t, mode="lines", name="Last Readings", line=dict(color=cfg.COLORS["text_muted"], width=2, dash="dot")))
    fig.add_hline(y=cfg.TEMP_HIGH, line_dash="dot", line_color=cfg.COLORS["danger"], line_width=1)
    fig.add_hline(y=cfg.TEMP_LOW, line_dash="dot", line_color=cfg.COLORS["primary_light"], line_width=1)
    if h_ts:
        fig.add_shape(type="line", x0=h_ts[-1], x1=h_ts[-1], y0=0, y1=1, yref="paper", line=dict(dash="dash", color=cfg.COLORS["warning"], width=1))
        fig.add_annotation(x=h_ts[-1], y=1, yref="paper", text="Last Reading", showarrow=False,
                           font=dict(color=cfg.COLORS["warning"], size=9), yshift=8)
    fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, plot_bgcolor=cfg.CHART_PLOT_BG,
                      font=cfg.CHART_FONT, height=270, margin=dict(l=40, r=10, t=20, b=28), hovermode="x unified", hoverlabel=cfg.HOVER_LABEL,
                      xaxis=dict(gridcolor=cfg.CHART_GRID_COLOR), yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, title="°F"),
                      legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=9)),
                      title=dict(text="Offline — Last 2h Before Disconnect", font=dict(size=10, color=cfg.COLORS["text_muted"]), x=0.5))
    return dbc.Card(dcc.Graph(figure=fig, config={"displayModeBar": False}), style=cfg.CARD_STYLE, className="mb-2")


def _tile(label, value, color):
    ls = {"fontSize": "0.58rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase", "letterSpacing": "1px", "fontFamily": _F}
    return html.Div([html.Div(label, style=ls), html.Div(value, style={"fontSize": "0.88rem", "fontWeight": "600", "color": color, "fontFamily": _F})],
                     style={**cfg.CARD_STYLE, "padding": "7px 10px", "textAlign": "center"})


def _wifi_tile(label, src, color):
    ls = {"fontSize": "0.58rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase", "letterSpacing": "1px", "fontFamily": _F}
    return html.Div([html.Div("Signal", style=ls), html.Div([
        html.Img(src=src, style={"height": "14px", "verticalAlign": "middle", "marginRight": "4px"}),
        html.Span(label, style={"fontSize": "0.82rem", "fontWeight": "600", "color": color, "fontFamily": _F}),
    ], style={"display": "flex", "alignItems": "center", "justifyContent": "center"})],
        style={**cfg.CARD_STYLE, "padding": "7px 10px", "textAlign": "center"})


def _fmt_time(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %H:%M")
    except Exception:
        return ""
