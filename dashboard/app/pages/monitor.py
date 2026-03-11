"""Single-page dashboard — unified Live + History view with data pump pattern.

Layout: Banner → Grid → Alerts → KPIs → Unified Chart → Compliance → Alert Table
All display callbacks read from dcc.Store (pure render, zero DB calls).
"""

from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
import numpy as np
from dash import Input, Output, State, callback, ctx, dash_table, dcc, html, no_update

from app import config as cfg
from app.auth import get_client_id
from app.data.provider import get_provider

if "/" not in {v.get("path") for v in dash.page_registry.values()}:
    dash.register_page(__name__, path="/", name="Monitor")

_F = "'DM Sans', system-ui, sans-serif"
_RANGES = [
    {"label": "LIVE", "value": "live"},
    {"label": "6h", "value": "6"}, {"label": "12h", "value": "12"},
    {"label": "24h", "value": "24"}, {"label": "48h", "value": "48"},
    {"label": "7d", "value": "168"}, {"label": "14d", "value": "336"},
    {"label": "30d", "value": "720"}, {"label": "60d", "value": "1440"},
    {"label": "90d", "value": "2160"}, {"label": "120d", "value": "2880"},
]


def layout(**kwargs):
    return html.Div([
        dcc.Interval(id="mon-tick", interval=cfg.REFRESH_MONITOR_MS),
        dcc.Store(id="store-states", data=[]),
        dcc.Store(id="store-alerts", data=[]),
        dcc.Store(id="store-compliance", data=[]),
        dcc.Store(id="store-readings", data=None),
        dcc.Store(id="mon-selected", data=None),
        dcc.Store(id="mon-show-all", data=True),
        dcc.Store(id="range-mode", data="live"),
        dcc.Store(id="note-feedback", data=None),
        html.Div(id="mon-banner"),
        html.Div(id="mon-sensor-alerts"),
        html.Div(id="mon-grid"),
        html.Div(id="mon-kpis"),
        html.Div(id="mon-range-bar"),
        html.Div(id="mon-chart-container"),
        html.Div(id="mon-compliance"),
        html.Div(id="mon-alert-table"),
    ])


# ── DATA PUMP — single callback for ALL data ────────────────────────────────

@callback(
    Output("store-states", "data"),
    Output("store-alerts", "data"),
    Output("store-compliance", "data"),
    Output("store-readings", "data"),
    Output("mon-selected", "data", allow_duplicate=True),
    Input("mon-tick", "n_intervals"),
    Input("mon-selected", "data"),
    Input("range-mode", "data"),
    State("store-states", "data"),
    prevent_initial_call="initial_duplicate",
)
def data_pump(_, selected_id, range_mode, prev_states):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    alerts = prov.get_live_alerts()
    compliance = prov.get_compliance_history(7)

    auto_selected = False
    if not selected_id and states:
        selected_id = states[0]["device_id"]
        auto_selected = True

    readings_data = None
    if selected_id:
        readings_data = _fetch_readings(prov, selected_id, range_mode, states)

    return states, alerts, compliance, readings_data, (selected_id if auto_selected else no_update)


def _fetch_readings(prov, device_id, range_mode, states):
    """Build readings + forecast payload for the selected sensor and range."""
    now = datetime.now(timezone.utc)
    state = next((s for s in states if s["device_id"] == device_id), None) if states else None
    is_offline = state and state.get("status") == "offline"

    if is_offline and state.get("last_seen"):
        try:
            anchor = datetime.fromisoformat(state["last_seen"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            anchor = now
    else:
        anchor = now

    if range_mode == "live":
        hours = 2
    else:
        try:
            hours = int(range_mode)
        except (ValueError, TypeError):
            hours = 2

    since = anchor - timedelta(hours=hours)
    readings = prov.get_readings(device_id, since.strftime("%Y-%m-%dT%H:%M:00Z"),
                                 anchor.strftime("%Y-%m-%dT%H:%M:00Z") if is_offline else None)

    show_forecast = range_mode == "live" and not is_offline
    if show_forecast:
        fc = prov.get_forecast_series(device_id, "30min", 30)
    else:
        fc = []

    alert_history = prov.get_alert_history(device_id, days=max(hours // 24, 7))

    return {
        "device_id": device_id,
        "readings": readings,
        "forecast": fc,
        "offline": bool(is_offline),
        "alerts": alert_history,
        "range_mode": range_mode,
    }


# ── DISPLAY: Banner ─────────────────────────────────────────────────────────

@callback(Output("mon-banner", "children"), Input("store-states", "data"), Input("store-alerts", "data"))
def render_banner(states, alerts):
    if not states:
        states = []
    total = len(states)
    online = sum(1 for s in states if s.get("status") != "offline")
    temps = [s["temperature"] for s in states if s.get("status") != "offline"]
    avg = float(np.mean(temps)) if temps else 0
    low_bat = sum(1 for s in states if s.get("battery_pct", 100) < cfg.BATTERY_LOW and s.get("status") != "offline")
    n_alerts = len(alerts) if alerts else 0

    if avg >= cfg.TEMP_CRITICAL_HIGH or n_alerts >= 5:
        label, color, bg = "ACTION REQUIRED", cfg.COLORS["danger"], cfg.COLORS["danger_dim"]
    elif avg >= cfg.TEMP_HIGH or avg <= cfg.TEMP_LOW or n_alerts > 0 or low_bat > 0:
        label, color, bg = "NEEDS ATTENTION", cfg.COLORS["warning"], cfg.COLORS["warning_dim"]
    else:
        label, color, bg = "ALL CLEAR", cfg.COLORS["success"], cfg.COLORS["success_dim"]

    ac = cfg.COLORS["danger"] if n_alerts else cfg.COLORS["success"]
    return html.Div(dbc.Row([
        dbc.Col(html.H1(label, style={"color": color, "fontWeight": "700", "fontSize": "1.3rem",
                                       "letterSpacing": "2px", "margin": 0, "fontFamily": _F}), lg=4),
        dbc.Col(html.Div([
            _pill(f"{online}/{total}", "Sensors", cfg.COLORS["success"] if online == total else cfg.COLORS["warning"]),
            _pill(str(n_alerts), "Alerts", ac),
            _pill(f"{avg:.1f}°F", "Avg Temp", cfg.COLORS["primary"]),
            _pill(str(low_bat), "Low Battery", cfg.COLORS["danger"] if low_bat else cfg.COLORS["success"]),
        ], className="d-flex gap-3 flex-wrap justify-content-end align-items-center"), lg=8),
    ], className="align-items-center"),
        style={**cfg.CARD_STYLE, "backgroundColor": bg, "padding": "12px 18px", "marginBottom": "10px"})


# ── DISPLAY: Alert cards ────────────────────────────────────────────────────

@callback(Output("mon-sensor-alerts", "children"),
          Input("store-alerts", "data"), Input("mon-selected", "data"), Input("note-feedback", "data"))
def render_alerts(alerts, selected_id, note_fb):
    if not alerts or not selected_id:
        return html.Div()
    sensor_alerts = [a for a in alerts if a.get("device_id") == selected_id]
    if not sensor_alerts:
        return html.Div()
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "WARNING": 3}
    sensor_alerts.sort(key=lambda x: sev_order.get(x.get("severity", ""), 9))

    items = []
    for a in sensor_alerts:
        sev = a.get("severity", "")
        sc = cfg.SEVERITY_COLORS.get(sev, cfg.COLORS["text_muted"])
        is_actionable = sev in ("CRITICAL", "HIGH")
        idx = f"{a['device_id']}|{a['alert_type']}"

        noted = note_fb and note_fb.get("index") == idx
        if noted:
            action_area = html.Div([
                html.Span("\u2705 Note Sent", style={"color": cfg.COLORS["success"], "fontWeight": "700", "fontSize": "0.72rem"}),
            ], style={"marginTop": "4px"})
        elif is_actionable:
            action_area = html.Div([
                html.Button("\U0001f4cb Note", id={"type": "alert-note", "index": idx},
                            n_clicks=0, style={"background": cfg.COLORS["primary"], "color": "#fff", "border": "none",
                                                "borderRadius": "6px", "padding": "3px 10px", "fontSize": "0.65rem",
                                                "cursor": "pointer", "marginRight": "6px"}),
                html.Button("\u2715 Remove", id={"type": "alert-dismiss", "index": idx},
                            n_clicks=0, style={"background": cfg.COLORS["danger"], "color": "#fff", "border": "none",
                                                "borderRadius": "6px", "padding": "3px 10px", "fontSize": "0.65rem",
                                                "cursor": "pointer"}),
            ], style={"marginTop": "4px", "display": "flex"})
        else:
            action_area = ""

        items.append(html.Div([
            html.Div([
                html.Span(cfg.SEVERITY_LABELS.get(sev, sev), style={
                    "backgroundColor": sc, "color": "#fff", "padding": "2px 10px",
                    "borderRadius": "10px", "fontSize": "0.62rem", "fontWeight": "700", "marginRight": "8px"}),
                html.Span(a.get("message", "")[:50], style={"fontSize": "0.8rem", "color": cfg.COLORS["text"], "flex": "1"}),
                html.Span(_fmt_time(a.get("triggered_at", "")), style={"fontSize": "0.68rem", "color": cfg.COLORS["text_muted"], "marginLeft": "auto"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "4px"}),
            action_area,
        ], style={**cfg.CARD_STYLE, "padding": "8px 12px", "marginBottom": "4px",
                  "borderLeft": f"3px solid {sc}"}))

    return html.Div([
        html.Div(html.Span(f"\u26A0 {len(sensor_alerts)} Alert{'s' if len(sensor_alerts) != 1 else ''} for {selected_id[-8:]}",
            style={"fontWeight": "700", "fontSize": "0.82rem", "color": cfg.COLORS["warning"]}), style={"marginBottom": "6px"}),
        *items,
    ], style={"marginBottom": "10px"})


@callback(Output("store-alerts", "data", allow_duplicate=True),
          Input({"type": "alert-dismiss", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def handle_dismiss(clicks):
    if not ctx.triggered or not any(clicks):
        return no_update
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        return no_update
    parts = tid["index"].split("|", 1)
    if len(parts) == 2:
        prov = get_provider(get_client_id())
        prov.dismiss_alert(parts[0], parts[1])
    return get_provider(get_client_id()).get_live_alerts()


@callback(Output("note-feedback", "data"),
          Output("store-alerts", "data", allow_duplicate=True),
          Input({"type": "alert-note", "index": dash.ALL}, "n_clicks"),
          State("store-states", "data"), prevent_initial_call=True)
def handle_note(clicks, states):
    if not ctx.triggered or not any(clicks):
        return no_update, no_update
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        return no_update, no_update
    parts = tid["index"].split("|", 1)
    if len(parts) == 2:
        state = next((s for s in (states or []) if s["device_id"] == parts[0]), {})
        prov = get_provider(get_client_id())
        prov.send_alert_note(parts[0], parts[1], {
            "device_id": parts[0], "alert_type": parts[1],
            "sensor_state": state, "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        updated_alerts = prov.get_live_alerts()
        return {"index": tid["index"], "ts": datetime.now(timezone.utc).isoformat()}, updated_alerts
    return no_update, no_update


# ── DISPLAY: Sensor grid ────────────────────────────────────────────────────

@callback(Output("mon-show-all", "data"), Input("mon-filter-toggle", "value"), prevent_initial_call=True)
def toggle_filter(val):
    return bool(val)


@callback(Output("mon-grid", "children"),
          Input("store-states", "data"), Input("store-alerts", "data"),
          Input("mon-selected", "data"), Input("mon-show-all", "data"))
def render_grid(states, alerts, selected_id, show_all):
    if not states:
        states = []
    alert_devs = {a.get("device_id") for a in (alerts or [])}

    def _crit(s):
        return (s["device_id"] in alert_devs or s.get("anomaly") or s.get("status") in ("offline", "degraded")
                or s["temperature"] >= cfg.TEMP_HIGH or s["temperature"] <= cfg.TEMP_LOW)

    states_sorted = sorted(states, key=lambda s: (0 if _crit(s) else 1, -s["temperature"]))
    if show_all is False:
        states_sorted = [s for s in states_sorted if _crit(s)]

    tiles = []
    for s in states_sorted:
        temp, did, st = s["temperature"], s["device_id"], s.get("status", "online")
        anom, bat, sig = s.get("anomaly"), s.get("battery_pct", 100), s.get("signal_label", "Good")
        has_alert = did in alert_devs
        if st == "offline":
            c = cfg.COLORS["text_muted"]
        elif st == "degraded":
            c = cfg.COLORS["warning"]
        elif temp >= cfg.TEMP_HIGH or temp <= cfg.TEMP_LOW or has_alert:
            c = cfg.COLORS["danger"]
        elif anom:
            c = cfg.COLORS["warning"]
        else:
            c = cfg.COLORS["success"]
        bat_c = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["text_muted"])
        sig_icon = cfg.SIGNAL_ICONS.get(sig, "")
        badge = html.Span(" \u26A0", style={"color": cfg.COLORS["warning"], "fontSize": "0.6rem"}) if (anom or has_alert) else ""
        is_sel = did == selected_id
        sel_style = {"boxShadow": f"0 0 0 2px {cfg.COLORS['primary']}" if is_sel else cfg.CARD_STYLE.get("boxShadow", "none"),
                     "transform": "scale(1.05)" if is_sel else "none", "zIndex": "2" if is_sel else "auto"}
        tiles.append(html.Div([
            html.Div([html.Span("\u25CF ", style={"color": c, "fontSize": "0.55rem"}),
                       html.Span(did, style={"fontFamily": "monospace", "fontSize": "0.6rem", "color": cfg.COLORS["text_muted"]}), badge],
                     style={"lineHeight": "1.2", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}),
            html.Div(f"{temp:.1f}°F{'*' if st == 'offline' else ''}", style={"fontWeight": "700", "fontSize": "1rem", "color": c, "lineHeight": "1.3"}),
            html.Div([html.Span(f"\U0001F50B{bat}%", style={"fontSize": "0.55rem", "color": bat_c, "marginRight": "5px"}),
                       html.Img(src=sig_icon, style={"height": "12px", "verticalAlign": "middle"})], style={"lineHeight": "1.2"}),
        ], id={"type": "sensor-card", "index": did}, n_clicks=0,
            style={**cfg.CARD_STYLE, "borderTop": f"3px solid {c}", "padding": "7px 10px", "cursor": "pointer",
                   "width": "130px", "textAlign": "center", "transition": "all 0.15s", **sel_style}))

    lbl = f"\u2609 {len(states_sorted)} Critical (of {len(states)})" if show_all is False else f"\u2609 {len(states_sorted)} Sensors"
    header = html.Div([
        html.Span(lbl, style={"fontWeight": "600", "fontSize": "0.8rem", "color": cfg.COLORS["text_muted"]}),
        dbc.Switch(id="mon-filter-toggle", label="Show All", value=show_all if show_all is not None else True,
                   style={"display": "inline-block", "marginLeft": "16px", "fontSize": "0.75rem"},
                   input_style={"backgroundColor": cfg.COLORS["primary"] if show_all else cfg.COLORS["card_border"]}),
    ], style={"marginBottom": "6px", "display": "flex", "alignItems": "center"})
    grid = html.Div(tiles, style={"display": "flex", "flexWrap": "wrap", "gap": "7px", "maxHeight": "220px", "overflowY": "auto", "paddingBottom": "4px"})
    if not tiles:
        grid = html.Div("No critical sensors at this time.", style={"color": cfg.COLORS["success"], "fontSize": "0.85rem", "padding": "12px 0"})
    return html.Div([header, grid], style={"marginBottom": "12px"})


@callback(Output("mon-selected", "data"), Input({"type": "sensor-card", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def select_sensor(clicks):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    tid = ctx.triggered_id
    return tid["index"] if tid and isinstance(tid, dict) else no_update


# ── DISPLAY: KPI row ────────────────────────────────────────────────────────

@callback(Output("mon-kpis", "children"),
          Input("store-readings", "data"), Input("store-states", "data"), Input("mon-selected", "data"))
def render_kpis(readings_data, states, selected_id):
    if not readings_data or not readings_data.get("readings"):
        return html.Div()
    readings = readings_data["readings"]
    is_offline = readings_data.get("offline", False)
    did = readings_data.get("device_id", selected_id)
    state = next((s for s in (states or []) if s["device_id"] == did), None)

    temps = [r["temperature"] for r in readings]
    if not temps:
        return html.Div()
    arr = np.array(temps, dtype=float)
    cur, hi, lo, avg = temps[-1], float(np.max(arr)), float(np.min(arr)), float(np.mean(arr))

    fc_series = readings_data.get("forecast", [])
    if fc_series:
        predicted = fc_series[-1].get("predicted", cur)
        fc_lbl, fc_val = "Forecast", f"{predicted:.1f}°F"
        fc_clr = cfg.COLORS["danger"] if predicted > cfg.TEMP_HIGH else cfg.COLORS["primary_light"]
    elif is_offline:
        fc_lbl, fc_val, fc_clr = "Last Reading", f"{cur:.1f}°F", cfg.COLORS["text_muted"]
    else:
        fc_lbl, fc_val, fc_clr = "Forecast", "N/A", cfg.COLORS["text_muted"]

    in_range = sum(1 for t in temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    comp_pct = round(in_range / len(temps) * 100, 1)

    roc = state.get("rate_of_change", 0) if state else 0
    trend = "\u2191 Rising" if roc > 0.5 else ("\u2193 Falling" if roc < -0.5 else "\u2192 Steady")
    tc = cfg.COLORS["warning"] if roc > 0.5 else (cfg.COLORS["primary_light"] if roc < -0.5 else cfg.COLORS["success"])

    st = state.get("status", "online") if state else "online"
    sc = cfg.COLORS["success"] if st == "online" else (cfg.COLORS["warning"] if st == "degraded" else cfg.COLORS["text_muted"])
    bat = state.get("battery_pct", 0) if state else 0
    bc = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["success"])
    sig = state.get("signal_label", "Good") if state else "Good"

    status_badge = html.Span(f"\u25CF {st.upper()}", style={"color": sc, "fontWeight": "600", "fontSize": "0.7rem", "marginRight": "8px"})
    sensor_label = html.Span(did or "", style={"fontFamily": "monospace", "color": cfg.COLORS["text_muted"], "fontSize": "0.78rem"})
    temp_display = html.Span(f"{cur:.1f}°F", style={"color": cfg.COLORS["primary"], "fontWeight": "700", "fontSize": "1.5rem", "marginLeft": "12px"})

    header = html.Div([status_badge, sensor_label, temp_display], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"})

    kpi_data = [
        ("High", f"{hi:.1f}°F", cfg.COLORS["danger"] if hi > cfg.TEMP_HIGH else cfg.COLORS["text"]),
        ("Low", f"{lo:.1f}°F", cfg.COLORS["primary_light"] if lo < cfg.TEMP_LOW else cfg.COLORS["text"]),
        ("Average", f"{avg:.1f}°F", cfg.COLORS["primary"]),
        ("Trend", trend if st == "online" else "N/A", tc if st == "online" else cfg.COLORS["text_muted"]),
        (fc_lbl, fc_val, fc_clr),
        ("In Range", f"{comp_pct}%", cfg.COLORS["success"] if comp_pct >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"]),
        ("Battery", f"{bat}%" if st != "offline" else "N/A", bc if st != "offline" else cfg.COLORS["text_muted"]),
        ("Signal", sig, cfg.COLORS["success"] if sig in ("Strong", "Good") else cfg.COLORS["warning"]),
    ]

    kpi_row = dbc.Row([dbc.Col(_kpi(l, v, c), xs=4, md=True, className="mb-2") for l, v, c in kpi_data], className="g-2")

    anom_box = html.Div()
    if state and state.get("anomaly") and state.get("anomaly_reason"):
        anom_box = html.Div([
            html.Span("\u26A0 Anomaly: ", style={"fontWeight": "700", "color": cfg.COLORS["warning"]}),
            html.Span(state["anomaly_reason"], style={"color": cfg.COLORS["text"]}),
        ], style={**cfg.CARD_STYLE, "backgroundColor": cfg.COLORS["warning_dim"],
                  "borderLeft": f"3px solid {cfg.COLORS['warning']}",
                  "padding": "8px 12px", "marginBottom": "8px", "fontSize": "0.82rem"})

    return html.Div([header, anom_box, kpi_row], style={"marginBottom": "10px"})


# ── DISPLAY: Range bar ──────────────────────────────────────────────────────

@callback(Output("mon-range-bar", "children"), Input("range-mode", "data"))
def render_range_bar(current_range):
    buttons = []
    for r in _RANGES:
        is_active = r["value"] == current_range
        is_live = r["value"] == "live"
        if is_active and is_live:
            bg, border_c, text_c = cfg.COLORS["success"], cfg.COLORS["success"], "#fff"
        elif is_active:
            bg, border_c, text_c = cfg.COLORS["primary"], cfg.COLORS["primary"], "#fff"
        else:
            bg, border_c, text_c = "transparent", cfg.COLORS["card_border"], cfg.COLORS["text_muted"]

        buttons.append(html.Button(
            r["label"],
            id={"type": "range-btn", "index": r["value"]},
            n_clicks=0,
            style={"background": bg, "color": text_c, "border": f"1px solid {border_c}",
                   "borderRadius": "8px", "padding": "4px 12px", "fontSize": "0.72rem",
                   "fontWeight": "600", "cursor": "pointer", "transition": "all 0.15s"},
        ))
    return html.Div(buttons, style={"display": "flex", "gap": "6px", "flexWrap": "wrap",
                                     "marginBottom": "10px", "padding": "4px 0"})


@callback(Output("range-mode", "data"),
          Input({"type": "range-btn", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def set_range(clicks):
    if not ctx.triggered or not any(clicks):
        return no_update
    tid = ctx.triggered_id
    return tid["index"] if tid and isinstance(tid, dict) else no_update


# ── DISPLAY: Unified chart ──────────────────────────────────────────────────

@callback(Output("mon-chart-container", "children"), Input("store-readings", "data"))
def render_chart(readings_data):
    if not readings_data or not readings_data.get("readings"):
        return html.Div("Select a sensor to view chart", style={
            **cfg.CARD_STYLE, "padding": "30px", "textAlign": "center",
            "color": cfg.COLORS["text_muted"], "fontSize": "0.85rem", "marginBottom": "10px"})

    from app.pages.charts import unified_chart
    readings = readings_data["readings"]
    fc = readings_data.get("forecast", [])
    alerts = readings_data.get("alerts", [])
    is_offline = readings_data.get("offline", False)
    range_mode = readings_data.get("range_mode", "live")

    hours = 2 if range_mode == "live" else int(range_mode) if range_mode.isdigit() else 2
    height = 380 if hours <= 48 else 420

    fig = unified_chart(readings, fc, alerts, range_mode, is_offline, height)
    return dbc.Card(
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        style=cfg.CARD_STYLE, className="mb-2",
    )


# ── DISPLAY: Compliance ─────────────────────────────────────────────────────

@callback(Output("mon-compliance", "children"),
          Input("store-states", "data"), Input("store-compliance", "data"))
def render_compliance(states, comp_history):
    from app.pages.charts import compliance_gauge, compliance_trend
    if not states:
        return html.Div()

    all_temps = [s["temperature"] for s in states]
    if not all_temps:
        return html.Div()

    all_offline = all(s.get("status") == "offline" for s in states)
    in_range = sum(1 for t in all_temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    total = len(all_temps)
    pct = round(in_range / total * 100, 1)
    out = total - in_range
    hot = sum(1 for t in all_temps if t > cfg.TEMP_HIGH)
    cold = sum(1 for t in all_temps if t < cfg.TEMP_LOW)
    gauge_label = "Last Known Compliance" if all_offline else "Live Compliance"
    gauge = compliance_gauge(pct, gauge_label)
    trend = compliance_trend(comp_history or [])

    stats_row = html.Div([_stat("Total", str(total), cfg.COLORS["text"]),
                           _stat("In Range", str(in_range), cfg.COLORS["success"]),
                           _stat("Out", str(out), cfg.COLORS["warning"] if out else cfg.COLORS["success"]),
                           _stat("Too Hot", str(hot), cfg.COLORS["danger"] if hot else cfg.COLORS["success"]),
                           _stat("Too Cold", str(cold), cfg.COLORS["primary_light"] if cold else cfg.COLORS["success"])],
                          style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "justifyContent": "center", "padding": "4px 0"})
    return dbc.Row([
        dbc.Col(dbc.Card([dbc.CardHeader(gauge_label, style={"backgroundColor": cfg.COLORS["card"], "border": "none",
            "fontWeight": "600", "fontSize": "0.82rem", "color": cfg.COLORS["text_muted"]}),
            dbc.CardBody([dcc.Graph(figure=gauge, config={"displayModeBar": False}), stats_row])], style=cfg.CARD_STYLE), lg=5, className="mb-3"),
        dbc.Col(dbc.Card([dbc.CardHeader("7-Day Trend", style={"backgroundColor": cfg.COLORS["card"], "border": "none",
            "fontWeight": "600", "fontSize": "0.82rem", "color": cfg.COLORS["text_muted"]}),
            dbc.CardBody(dcc.Graph(figure=trend, config={"displayModeBar": False}))], style=cfg.CARD_STYLE), lg=7, className="mb-3"),
    ], className="g-3 mt-1")


# ── DISPLAY: Alert history table ────────────────────────────────────────────

@callback(Output("mon-alert-table", "children"), Input("store-readings", "data"))
def render_alert_table(readings_data):
    if not readings_data:
        return html.Div()
    alerts = readings_data.get("alerts", [])
    if not alerts:
        return html.Div()

    table_data = []
    for a in alerts[:30]:
        sev = a.get("severity", "")
        table_data.append({
            "Priority": cfg.SEVERITY_LABELS.get(sev, sev),
            "Type": a.get("alert_type", ""),
            "What": a.get("message", "")[:42],
            "When": _fmt_time(a.get("triggered_at", "")),
            "Status": a.get("state", "ACTIVE").title(),
        })
    tbl = dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in ["Priority", "Type", "What", "When", "Status"]],
        data=table_data, sort_action="native", page_size=8,
        style_header={"backgroundColor": cfg.COLORS["card"], "color": cfg.COLORS["text_muted"],
                       "fontWeight": "600", "border": f"1px solid {cfg.COLORS['card_border']}",
                       "fontSize": "0.72rem", "textTransform": "uppercase"},
        style_cell={"backgroundColor": cfg.COLORS["bg"], "color": cfg.COLORS["text"],
                     "border": f"1px solid {cfg.COLORS['card_border']}", "fontSize": "0.82rem",
                     "padding": "7px 10px", "textAlign": "left"},
        style_data_conditional=[
            {"if": {"filter_query": "{Priority} = Urgent"}, "color": cfg.COLORS["critical"], "fontWeight": "600"},
            {"if": {"filter_query": "{Status} = Active"}, "backgroundColor": cfg.COLORS["danger_dim"]},
            {"if": {"filter_query": "{Status} = Dismissed"}, "color": cfg.COLORS["text_muted"]},
        ],
    )
    return dbc.Card([
        dbc.CardHeader("Alert History", style={"backgroundColor": cfg.COLORS["card"], "border": "none",
                                                "fontWeight": "600", "fontSize": "0.82rem", "color": cfg.COLORS["text_muted"]}),
        dbc.CardBody(tbl),
    ], style=cfg.CARD_STYLE, className="mb-3")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pill(v, l, c):
    return html.Div([html.Span(v, style={"color": c, "fontWeight": "700", "fontSize": "1.05rem", "marginRight": "4px"}),
                      html.Span(l, style={"color": cfg.COLORS["text_muted"], "fontSize": "0.72rem"})])

def _kpi(label, value, color):
    ls = {"fontSize": "0.58rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase", "letterSpacing": "1px"}
    return html.Div([html.Div(label, style=ls),
                      html.Div(value, style={"fontSize": "0.88rem", "fontWeight": "600", "color": color})],
                     style={**cfg.CARD_STYLE, "padding": "7px 10px", "textAlign": "center"})

def _stat(label, value, color):
    return html.Div([html.Div(value, style={"fontWeight": "700", "fontSize": "0.9rem", "color": color}),
                      html.Div(label, style={"fontSize": "0.55rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase"})],
                     style={"textAlign": "center", "minWidth": "55px"})

def _fmt_time(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %H:%M")
    except Exception:
        return ""
