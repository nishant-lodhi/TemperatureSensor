"""Single-page dashboard — unified Live + History view with data pump pattern.

Layout: Banner → Filters → StatusBar → Alerts → Grid → KPIs → Range → Chart → Compliance → AlertTable
Clientside callbacks handle clicks instantly; server callbacks fetch/render data.
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

_F = "'Inter', 'DM Sans', system-ui, sans-serif"
_RANGES = [
    {"label": "LIVE", "value": "live"},
    {"label": "1 h", "value": "1"}, {"label": "6 h", "value": "6"},
    {"label": "12 h", "value": "12"}, {"label": "24 h", "value": "24"},
]
_MAX_HISTORY_DAYS = 120


def layout(**kwargs):
    today = datetime.now(timezone.utc).date()
    min_date = today - timedelta(days=_MAX_HISTORY_DAYS)
    return html.Div([
        dcc.Interval(id="mon-tick", interval=cfg.REFRESH_MONITOR_MS),
        dcc.Store(id="store-states", data=[]),
        dcc.Store(id="store-alerts", data=[]),
        dcc.Store(id="store-compliance", data=[]),
        dcc.Store(id="store-readings", data=None),
        dcc.Store(id="mon-selected", data=None),
        dcc.Store(id="status-filter", data="all"),
        dcc.Store(id="range-mode", data="live"),
        dcc.Store(id="store-date-range", data=None),
        dcc.Store(id="note-feedback", data=None),
        dcc.Store(id="store-locations", data=[]),
        html.Div(id="mon-banner"),
        _filter_bar(min_date, today),
        html.Div(id="mon-status-bar"),
        html.Div(id="mon-sensor-alerts"),
        html.Div(id="mon-grid"),
        html.Div(id="mon-kpis"),
        html.Div(id="mon-range-bar"),
        html.Div(id="mon-chart-container"),
        html.Div(id="mon-compliance"),
        html.Div(id="mon-alert-table"),
    ])


def _filter_bar(min_date, max_date):
    dd = {"backgroundColor": cfg.COLORS["card"], "color": cfg.COLORS["text"],
          "border": f"1px solid {cfg.COLORS['card_border']}", "borderRadius": "10px",
          "fontSize": "0.76rem"}
    lbl = {"fontSize": "0.6rem", "color": cfg.COLORS["text_muted"],
           "textTransform": "uppercase", "letterSpacing": "1px", "marginBottom": "2px"}
    return html.Div([
        html.Div([
            html.Div([html.Label("Facility", style=lbl),
                       dcc.Dropdown(id="filter-location", placeholder="All Facilities",
                                    searchable=True, clearable=True, className="dash-dd-dark", style=dd)],
                     style={"flex": "1", "minWidth": "155px"}),
            html.Div([html.Label("Sensor", style=lbl),
                       dcc.Dropdown(id="filter-mac", placeholder="All Sensors",
                                    searchable=True, clearable=True, className="dash-dd-dark", style=dd)],
                     style={"flex": "1", "minWidth": "155px"}),
            html.Div([html.Label("Date Range", style=lbl),
                       dcc.DatePickerRange(
                           id="date-range-picker",
                           min_date_allowed=str(min_date), max_date_allowed=str(max_date),
                           initial_visible_month=str(max_date),
                           start_date=None, end_date=None,
                           display_format="MM/DD/YY", number_of_months_shown=1,
                           className="dash-datepicker-dark", style={"fontSize": "0.72rem"})],
                     style={"flex": "0.9", "minWidth": "170px"}),
            html.Button("\u21BA Reset", id="filter-reset", n_clicks=0,
                        className="glass-panel",
                        style={"color": cfg.COLORS["text_muted"], "padding": "5px 14px",
                               "fontSize": "0.72rem", "fontWeight": "600", "cursor": "pointer",
                               "alignSelf": "flex-end", "height": "34px"}),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "alignItems": "flex-end"}),
    ], className="glass-panel filter-bar-panel", style={"padding": "10px 16px", "marginBottom": "8px"})


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENTSIDE CALLBACKS — instant, zero server round-trip
# ═══════════════════════════════════════════════════════════════════════════════

dash.clientside_callback(
    """function() {
        var ctx = dash_clientside.callback_context;
        if (!ctx.triggered.length) return dash_clientside.no_update;
        var t = ctx.triggered[0];
        if (!t.value) return dash_clientside.no_update;
        try { return JSON.parse(t.prop_id.split('.')[0]).index; }
        catch(e) { return dash_clientside.no_update; }
    }""",
    Output("status-filter", "data"),
    Input({"type": "status-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)

dash.clientside_callback(
    """function() {
        var NU = dash_clientside.no_update;
        var ctx = dash_clientside.callback_context;
        if (!ctx.triggered.length) return [NU, NU, NU];
        var t = ctx.triggered[0];
        if (!t.value) return [NU, NU, NU];
        try { return [JSON.parse(t.prop_id.split('.')[0]).index, null, null]; }
        catch(e) { return [NU, NU, NU]; }
    }""",
    Output("range-mode", "data"),
    Output("date-range-picker", "start_date", allow_duplicate=True),
    Output("date-range-picker", "end_date", allow_duplicate=True),
    Input({"type": "range-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)

dash.clientside_callback(
    """function(start, end) {
        if (start && end) return ["custom", {start: start.substring(0,10), end: end.substring(0,10)}];
        return [dash_clientside.no_update, dash_clientside.no_update];
    }""",
    Output("range-mode", "data", allow_duplicate=True),
    Output("store-date-range", "data"),
    Input("date-range-picker", "start_date"),
    Input("date-range-picker", "end_date"),
    prevent_initial_call=True,
)

dash.clientside_callback(
    """function(n) {
        if (n) return [null, null, null, null, "live"];
        return Array(5).fill(dash_clientside.no_update);
    }""",
    Output("filter-location", "value"),
    Output("filter-mac", "value"),
    Output("date-range-picker", "start_date", allow_duplicate=True),
    Output("date-range-picker", "end_date", allow_duplicate=True),
    Output("range-mode", "data", allow_duplicate=True),
    Input("filter-reset", "n_clicks"),
    prevent_initial_call=True,
)

dash.clientside_callback(
    """function(mac, current) {
        if (mac === undefined || mac === null || mac === current) return dash_clientside.no_update;
        return mac;
    }""",
    Output("mon-selected", "data", allow_duplicate=True),
    Input("filter-mac", "value"),
    State("mon-selected", "data"),
    prevent_initial_call=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SERVER CALLBACKS — data fetching only
# ═══════════════════════════════════════════════════════════════════════════════

@callback(Output("store-locations", "data"), Input("mon-tick", "n_intervals"),
          prevent_initial_call="initial_duplicate")
def load_locations(_):
    return get_provider(get_client_id()).get_locations()


@callback(Output("filter-location", "options"), Input("store-locations", "data"))
def update_location_options(locations):
    return [{"label": loc, "value": loc} for loc in locations] if locations else []


@callback(Output("filter-mac", "options"),
          Input("filter-location", "value"), Input("store-states", "data"))
def update_mac_options(location, states):
    if not states:
        return []
    filtered = [s for s in states if s.get("location") == location] if location else states
    return [{"label": s["device_id"], "value": s["device_id"]} for s in filtered]


@callback(
    Output("store-states", "data"), Output("store-alerts", "data"),
    Output("store-compliance", "data"), Output("store-readings", "data"),
    Output("mon-selected", "data", allow_duplicate=True),
    Input("mon-tick", "n_intervals"), Input("mon-selected", "data"), Input("range-mode", "data"),
    Input("store-date-range", "data"),
    State("store-states", "data"), State("filter-location", "value"),
    prevent_initial_call="initial_duplicate",
)
def data_pump(_, selected_id, range_mode, date_range, prev_states, location_filter):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    alerts = prov.get_live_alerts()
    compliance = prov.get_compliance_history(7)

    visible = [s for s in states if s.get("location") == location_filter] if location_filter else states
    auto = False
    if visible:
        vids = {s["device_id"] for s in visible}
        if not selected_id or selected_id not in vids:
            selected_id, auto = visible[0]["device_id"], True

    rd = _fetch_readings(prov, selected_id, range_mode, states, date_range) if selected_id else None
    return states, alerts, compliance, rd, (selected_id if auto else no_update)


def _fetch_readings(prov, device_id, range_mode, states, date_range=None):
    now = datetime.now(timezone.utc)
    state = next((s for s in states if s["device_id"] == device_id), None) if states else None
    is_offline = state and state.get("status") == "offline"
    anchor = now
    if is_offline and state.get("last_seen"):
        try:
            anchor = datetime.fromisoformat(state["last_seen"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    if range_mode == "custom" and date_range:
        since = datetime.fromisoformat(date_range["start"]).replace(tzinfo=timezone.utc)
        until = datetime.fromisoformat(date_range["end"]).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        hours = max(1, int((until - since).total_seconds() / 3600))
    else:
        hours = 2 if range_mode == "live" else int(range_mode) if range_mode and range_mode.isdigit() else 2
        since = anchor - timedelta(hours=hours)
        until = anchor if is_offline else now

    readings = prov.get_readings(device_id, since.strftime("%Y-%m-%dT%H:%M:00Z"),
                                 until.strftime("%Y-%m-%dT%H:%M:00Z"))
    show_fc = range_mode == "live" and not is_offline
    fc = prov.get_forecast_series(device_id, "30min", 30) if show_fc else []
    alert_hist = prov.get_alert_history(device_id, days=max(hours // 24, 7))
    fc_alerts = _build_forecast_alerts(fc, device_id) if fc else []

    return {"device_id": device_id, "readings": readings, "forecast": fc,
            "offline": bool(is_offline), "alerts": alert_hist + fc_alerts,
            "range_mode": range_mode, "forecast_alert_count": len(fc_alerts)}


def _build_forecast_alerts(fc_series, device_id):
    out = []
    for f in fc_series:
        pred = f.get("predicted", 0)
        if pred > cfg.TEMP_HIGH:
            out.append({"triggered_at": f["timestamp"], "temperature": str(pred),
                        "alert_type": "FORECAST_HIGH", "severity": "FORECAST",
                        "message": f"Forecast {pred:.1f}°F may exceed safe limit",
                        "state": "FORECAST", "device_id": device_id})
        elif pred < cfg.TEMP_LOW:
            out.append({"triggered_at": f["timestamp"], "temperature": str(pred),
                        "alert_type": "FORECAST_LOW", "severity": "FORECAST",
                        "message": f"Forecast {pred:.1f}°F may drop below safe limit",
                        "state": "FORECAST", "device_id": device_id})
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# DISPLAY CALLBACKS — pure render, read from stores
# ═══════════════════════════════════════════════════════════════════════════════

@callback(Output("mon-banner", "children"),
          Input("store-states", "data"), Input("store-alerts", "data"),
          Input("filter-location", "value"), Input("store-readings", "data"))
def render_banner(states, alerts, location_filter, readings_data):
    states, alerts = states or [], alerts or []
    if location_filter:
        fmacs = {s["device_id"] for s in states if s.get("location") == location_filter}
        vis_s = [s for s in states if s["device_id"] in fmacs]
        vis_a = [a for a in alerts if a.get("device_id") in fmacs]
    else:
        vis_s, vis_a = states, alerts

    total = len(vis_s)
    online = sum(1 for s in vis_s if s.get("status") != "offline")
    temps = [s["temperature"] for s in vis_s if s.get("status") != "offline"]
    avg = float(np.mean(temps)) if temps else 0
    low_bat = sum(1 for s in vis_s if s.get("battery_pct", 100) < cfg.BATTERY_LOW and s.get("status") != "offline")
    n_a = len(vis_a)
    fc_n = readings_data.get("forecast_alert_count", 0) if readings_data else 0

    title = location_filter or "All Facilities"
    if avg >= cfg.TEMP_CRITICAL_HIGH or n_a >= 5:
        bg = cfg.COLORS["danger_dim"]
    elif avg >= cfg.TEMP_HIGH or avg <= cfg.TEMP_LOW or n_a > 0 or low_bat > 0:
        bg = cfg.COLORS["warning_dim"]
    else:
        bg = cfg.COLORS["success_dim"]

    pills = [
        _pill(f"{online}/{total}", "Sensors", cfg.COLORS["success"] if online == total else cfg.COLORS["warning"]),
        _pill(str(n_a), "Alerts", cfg.COLORS["danger"] if n_a else cfg.COLORS["success"]),
    ]
    if fc_n:
        pills.append(_pill(str(fc_n), "Forecast", cfg.COLORS["accent"]))
    pills += [
        _pill(f"{avg:.1f}°F", "Avg", cfg.COLORS["primary"]),
        _pill(str(low_bat), "Low Bat", cfg.COLORS["danger"] if low_bat else cfg.COLORS["success"]),
    ]
    return html.Div(dbc.Row([
        dbc.Col(html.Div(title, style={"fontWeight": "700", "fontSize": "1rem", "letterSpacing": "1.5px",
                                        "color": cfg.COLORS["text"], "textTransform": "uppercase", "fontFamily": _F}), lg=3),
        dbc.Col(html.Div(pills, className="d-flex gap-3 flex-wrap justify-content-end align-items-center"), lg=9),
    ], className="align-items-center"),
        className="glass-panel", style={"backgroundColor": bg, "padding": "10px 18px", "marginBottom": "8px"})


# ── Status bar (filter pills) ────────────────────────────────────────────────

def _sensor_color(s, alert_devs):
    did, st = s["device_id"], s.get("status", "online")
    temp, anom, bat = s["temperature"], s.get("anomaly"), s.get("battery_pct", 100)
    if st == "offline" or did in alert_devs or temp >= cfg.TEMP_HIGH or temp <= cfg.TEMP_LOW:
        return "red"
    if anom or bat < cfg.BATTERY_WARN or st == "degraded":
        return "yellow"
    return "green"


@callback(Output("mon-status-bar", "children"),
          Input("store-states", "data"), Input("store-alerts", "data"),
          Input("status-filter", "data"), Input("filter-location", "value"))
def render_status_bar(states, alerts, active_filter, location_filter):
    states = states or []
    if location_filter:
        states = [s for s in states if s.get("location") == location_filter]
    alert_devs = {a.get("device_id") for a in (alerts or [])}
    cm = {"green": 0, "yellow": 0, "red": 0}
    for s in states:
        cm[_sensor_color(s, alert_devs)] += 1
    total = sum(cm.values())
    sf = active_filter or "all"

    pills = []
    defs = [
        ("all", f"All  {total}", cfg.COLORS["text_muted"], None),
        ("red", f"Critical  {cm['red']}", cfg.COLORS["danger"], cfg.COLORS["danger"]),
        ("yellow", f"Warning  {cm['yellow']}", cfg.COLORS["warning"], cfg.COLORS["warning"]),
        ("green", f"Normal  {cm['green']}", cfg.COLORS["success"], cfg.COLORS["success"]),
    ]
    for val, label, clr, dot_c in defs:
        active = sf == val
        cn = f"filter-pill{' filter-pill-active' if active else ''}"
        children = []
        if dot_c:
            children.append(html.Span(className="pill-dot", style={"backgroundColor": dot_c}))
        children.append(html.Span(label))
        pills.append(html.Button(children, id={"type": "status-btn", "index": val}, n_clicks=0, className=cn))

    return html.Div([
        html.Span(f"\u2609 {total} Sensors", style={"fontWeight": "600", "fontSize": "0.78rem",
                                                      "color": cfg.COLORS["text_muted"], "marginRight": "14px"}),
        html.Div(pills, style={"display": "flex", "gap": "6px"}),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px", "flexWrap": "wrap"})


# ── Alert cards ──────────────────────────────────────────────────────────────

@callback(Output("mon-sensor-alerts", "children"),
          Input("store-alerts", "data"), Input("mon-selected", "data"), Input("note-feedback", "data"))
def render_alerts(alerts, selected_id, note_fb):
    if not alerts or not selected_id:
        return html.Div()
    sensor_alerts = sorted([a for a in alerts if a.get("device_id") == selected_id],
                           key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x.get("severity", ""), 9))
    if not sensor_alerts:
        return html.Div()
    items = []
    for a in sensor_alerts:
        sev = a.get("severity", "")
        sc = cfg.SEVERITY_COLORS.get(sev, cfg.COLORS["text_muted"])
        idx = f"{a['device_id']}|{a['alert_type']}"
        noted = note_fb and note_fb.get("index") == idx
        if noted:
            action = html.Span("\u2705 Note Sent", style={"color": cfg.COLORS["success"], "fontWeight": "700", "fontSize": "0.7rem"})
        elif sev in ("CRITICAL", "HIGH"):
            action = html.Div([
                html.Button("\U0001f4cb Note", id={"type": "alert-note", "index": idx}, n_clicks=0,
                            style={"background": cfg.COLORS["primary"], "color": "#fff", "border": "none",
                                   "borderRadius": "6px", "padding": "3px 10px", "fontSize": "0.62rem",
                                   "cursor": "pointer", "marginRight": "6px"}),
                html.Button("\u2715", id={"type": "alert-dismiss", "index": idx}, n_clicks=0,
                            style={"background": cfg.COLORS["danger"], "color": "#fff", "border": "none",
                                   "borderRadius": "6px", "padding": "3px 8px", "fontSize": "0.62rem", "cursor": "pointer"}),
            ], style={"display": "flex", "marginTop": "4px"})
        else:
            action = ""
        items.append(html.Div([
            html.Div([
                html.Span(cfg.SEVERITY_LABELS.get(sev, sev), style={
                    "backgroundColor": sc, "color": "#fff", "padding": "2px 10px",
                    "borderRadius": "10px", "fontSize": "0.6rem", "fontWeight": "700", "marginRight": "8px"}),
                html.Span(a.get("message", "")[:50], style={"fontSize": "0.78rem", "color": cfg.COLORS["text"], "flex": "1"}),
                html.Span(_fmt_time(a.get("triggered_at", "")), style={"fontSize": "0.66rem", "color": cfg.COLORS["text_muted"], "marginLeft": "auto"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "4px"}),
            action,
        ], className="alert-card", style={"borderLeft": f"3px solid {sc}"}))

    return html.Div([
        html.Div(html.Span(f"\u26A0 {len(sensor_alerts)} Alert{'s' if len(sensor_alerts) != 1 else ''}",
            style={"fontWeight": "700", "fontSize": "0.8rem", "color": cfg.COLORS["warning"]}), style={"marginBottom": "6px"}),
        *items,
    ], style={"marginBottom": "10px"})


@callback(Output("store-alerts", "data", allow_duplicate=True),
          Input({"type": "alert-dismiss", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def handle_dismiss(clicks):
    if not ctx.triggered or not any(clicks):
        return no_update
    tid = ctx.triggered_id
    if tid and isinstance(tid, dict):
        parts = tid["index"].split("|", 1)
        if len(parts) == 2:
            get_provider(get_client_id()).dismiss_alert(parts[0], parts[1])
    return get_provider(get_client_id()).get_live_alerts()


@callback(Output("note-feedback", "data"), Output("store-alerts", "data", allow_duplicate=True),
          Input({"type": "alert-note", "index": dash.ALL}, "n_clicks"),
          State("store-states", "data"), prevent_initial_call=True)
def handle_note(clicks, states):
    if not ctx.triggered or not any(clicks):
        return no_update, no_update
    tid = ctx.triggered_id
    if tid and isinstance(tid, dict):
        parts = tid["index"].split("|", 1)
        if len(parts) == 2:
            st = next((s for s in (states or []) if s["device_id"] == parts[0]), {})
            prov = get_provider(get_client_id())
            prov.send_alert_note(parts[0], parts[1], {
                "device_id": parts[0], "alert_type": parts[1],
                "sensor_state": st, "timestamp": datetime.now(timezone.utc).isoformat()})
            return {"index": tid["index"], "ts": datetime.now(timezone.utc).isoformat()}, prov.get_live_alerts()
    return no_update, no_update


# ── Sensor grid ──────────────────────────────────────────────────────────────

@callback(Output("mon-grid", "children"),
          Input("store-states", "data"), Input("store-alerts", "data"),
          Input("mon-selected", "data"), Input("status-filter", "data"),
          Input("filter-location", "value"))
def render_grid(states, alerts, selected_id, status_filter, location_filter):
    states = states or []
    if location_filter:
        states = [s for s in states if s.get("location") == location_filter]
    alert_devs = {a.get("device_id") for a in (alerts or [])}
    for s in states:
        s["_color"] = _sensor_color(s, alert_devs)
    if status_filter and status_filter != "all":
        states = [s for s in states if s.get("_color") == status_filter]
    states.sort(key=lambda s: ({"red": 0, "yellow": 1, "green": 2}.get(s.get("_color"), 2), -s["temperature"]))

    tiles = []
    for s in states:
        temp, did, st = s["temperature"], s["device_id"], s.get("status", "online")
        bat, sig, loc = s.get("battery_pct", 100), s.get("signal_label", "Good"), s.get("location", "")
        c = {"green": cfg.COLORS["success"], "yellow": cfg.COLORS["warning"],
             "red": cfg.COLORS["danger"]}.get(s.get("_color"), cfg.COLORS["text_muted"])
        if st == "offline":
            c = cfg.COLORS["text_muted"]
        bat_c = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["text_muted"])
        is_sel = did == selected_id
        cn = f"sensor-tile{' sensor-tile-selected' if is_sel else ''}"
        loc_el = html.Div(loc, style={"fontSize": "0.48rem", "color": cfg.COLORS["text_muted"],
                                       "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}) if loc else ""
        tiles.append(html.Div([
            html.Div([html.Span("\u25CF ", style={"color": c, "fontSize": "0.5rem"}),
                       html.Span(did, style={"fontFamily": "monospace", "fontSize": "0.58rem", "color": cfg.COLORS["text_muted"]})],
                     style={"lineHeight": "1.2", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Div(f"{temp:.1f}°F{'*' if st == 'offline' else ''}",
                     style={"fontWeight": "700", "fontSize": "1rem", "color": c, "lineHeight": "1.3"}),
            loc_el,
            html.Div([html.Span(f"\U0001F50B{bat}%", style={"fontSize": "0.52rem", "color": bat_c, "marginRight": "4px"}),
                       html.Img(src=cfg.SIGNAL_ICONS.get(sig, ""), style={"height": "11px", "verticalAlign": "middle"})],
                     style={"lineHeight": "1.2"}),
        ], id={"type": "sensor-card", "index": did}, n_clicks=0, className=cn,
            style={"borderTop": f"3px solid {c}"}))

    grid = html.Div(tiles, style={"display": "flex", "flexWrap": "wrap", "gap": "7px",
                                   "maxHeight": "230px", "overflowY": "auto", "paddingBottom": "4px"})
    if not tiles:
        grid = html.Div("No sensors match this filter.",
                         style={"color": cfg.COLORS["text_muted"], "fontSize": "0.82rem", "padding": "12px 0"})
    return html.Div(grid, style={"marginBottom": "10px"})


@callback(Output("mon-selected", "data"),
          Input({"type": "sensor-card", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def select_sensor(clicks):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    tid = ctx.triggered_id
    return tid["index"] if tid and isinstance(tid, dict) else no_update


# ── KPIs ─────────────────────────────────────────────────────────────────────

@callback(Output("mon-kpis", "children"),
          Input("store-readings", "data"), Input("store-states", "data"), Input("mon-selected", "data"))
def render_kpis(rd, states, selected_id):
    if not rd or not rd.get("readings"):
        return html.Div()
    readings, is_off = rd["readings"], rd.get("offline", False)
    did = rd.get("device_id", selected_id)
    state = next((s for s in (states or []) if s["device_id"] == did), None)
    temps = [r["temperature"] for r in readings]
    if not temps:
        return html.Div()
    arr = np.array(temps, dtype=float)
    cur, hi, lo, avg = temps[-1], float(np.max(arr)), float(np.min(arr)), float(np.mean(arr))
    fc = rd.get("forecast", [])
    if fc:
        pred = fc[-1].get("predicted", cur)
        fl, fv, fc_c = "Forecast", f"{pred:.1f}°F", cfg.COLORS["danger"] if pred > cfg.TEMP_HIGH else cfg.COLORS["accent"]
    elif is_off:
        fl, fv, fc_c = "Last", f"{cur:.1f}°F", cfg.COLORS["text_muted"]
    else:
        fl, fv, fc_c = "Forecast", "N/A", cfg.COLORS["text_muted"]
    in_r = sum(1 for t in temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    cp = round(in_r / len(temps) * 100, 1)
    roc = state.get("rate_of_change", 0) if state else 0
    trend = "\u2191 Rising" if roc > 0.5 else ("\u2193 Falling" if roc < -0.5 else "\u2192 Steady")
    tc = cfg.COLORS["warning"] if roc > 0.5 else (cfg.COLORS["primary_light"] if roc < -0.5 else cfg.COLORS["success"])
    st = state.get("status", "online") if state else "online"
    sc = cfg.COLORS["success"] if st == "online" else (cfg.COLORS["warning"] if st == "degraded" else cfg.COLORS["text_muted"])
    bat = state.get("battery_pct", 0) if state else 0
    bc = cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW else (cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN else cfg.COLORS["success"])
    sig = state.get("signal_label", "Good") if state else "Good"
    loc = state.get("location", "") if state else ""
    loc_badge = html.Span(f" \u2022 {loc}", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.66rem"}) if loc else ""
    header = html.Div([
        html.Span(f"\u25CF {st.upper()}", style={"color": sc, "fontWeight": "600", "fontSize": "0.68rem", "marginRight": "8px"}),
        html.Span(did or "", style={"fontFamily": "monospace", "color": cfg.COLORS["text_muted"], "fontSize": "0.76rem"}),
        loc_badge,
        html.Span(f"{cur:.1f}°F", style={"color": cfg.COLORS["primary"], "fontWeight": "700", "fontSize": "1.4rem", "marginLeft": "12px"}),
    ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"})
    data = [("High", f"{hi:.1f}°F", cfg.COLORS["danger"] if hi > cfg.TEMP_HIGH else cfg.COLORS["text"]),
            ("Low", f"{lo:.1f}°F", cfg.COLORS["primary_light"] if lo < cfg.TEMP_LOW else cfg.COLORS["text"]),
            ("Avg", f"{avg:.1f}°F", cfg.COLORS["primary"]),
            ("Trend", trend if st == "online" else "N/A", tc if st == "online" else cfg.COLORS["text_muted"]),
            (fl, fv, fc_c),
            ("In Range", f"{cp}%", cfg.COLORS["success"] if cp >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"]),
            ("Battery", f"{bat}%" if st != "offline" else "N/A", bc if st != "offline" else cfg.COLORS["text_muted"]),
            ("Signal", sig, cfg.COLORS["success"] if sig in ("Strong", "Good") else cfg.COLORS["warning"])]
    krow = dbc.Row([dbc.Col(_kpi(lb, v, c), xs=4, md=True, className="mb-2") for lb, v, c in data], className="g-2")
    abox = html.Div()
    if state and state.get("anomaly") and state.get("anomaly_reason"):
        abox = html.Div([html.Span("\u26A0 Anomaly: ", style={"fontWeight": "700", "color": cfg.COLORS["warning"]}),
                          html.Span(state["anomaly_reason"], style={"color": cfg.COLORS["text"]})],
                        className="glass-panel", style={"backgroundColor": cfg.COLORS["warning_dim"],
                                                        "borderLeft": f"3px solid {cfg.COLORS['warning']}",
                                                        "padding": "8px 12px", "marginBottom": "8px", "fontSize": "0.8rem"})
    return html.Div([header, abox, krow], style={"marginBottom": "10px"})


# ── Range bar ────────────────────────────────────────────────────────────────

@callback(Output("mon-range-bar", "children"), Input("range-mode", "data"))
def render_range_bar(current):
    btns = []
    for r in _RANGES:
        is_a = r["value"] == current
        is_l = r["value"] == "live"
        cn = "range-btn"
        if is_a and is_l:
            cn += " range-btn-live"
        elif is_a:
            cn += " range-btn-active"
        btns.append(html.Button(r["label"], id={"type": "range-btn", "index": r["value"]}, n_clicks=0, className=cn))
    return html.Div(btns, style={"display": "flex", "gap": "6px", "flexWrap": "wrap", "marginBottom": "10px", "padding": "4px 0"})


# ── Chart ────────────────────────────────────────────────────────────────────

@callback(Output("mon-chart-container", "children"), Input("store-readings", "data"))
def render_chart(rd):
    if not rd or not rd.get("readings"):
        return html.Div("Select a sensor to view chart", className="glass-panel",
                         style={"padding": "30px", "textAlign": "center", "color": cfg.COLORS["text_muted"],
                                "fontSize": "0.85rem", "marginBottom": "10px"})
    from app.pages.charts import unified_chart
    rm = rd.get("range_mode", "live")
    h = 2 if rm == "live" else int(rm) if rm and rm.isdigit() else 2
    fig = unified_chart(rd["readings"], rd.get("forecast", []), rd.get("alerts", []),
                        rm, rd.get("offline", False), 380 if h <= 48 else 420)
    return dbc.Card(dcc.Graph(figure=fig, config={"displayModeBar": False}),
                    className="glass-panel mb-2")


# ── Compliance ───────────────────────────────────────────────────────────────

@callback(Output("mon-compliance", "children"),
          Input("store-states", "data"), Input("store-compliance", "data"))
def render_compliance(states, comp):
    from app.pages.charts import compliance_gauge, compliance_trend
    if not states:
        return html.Div()
    temps = [s["temperature"] for s in states]
    if not temps:
        return html.Div()
    all_off = all(s.get("status") == "offline" for s in states)
    in_r = sum(1 for t in temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    total, pct = len(temps), round(in_r / len(temps) * 100, 1)
    out, hot, cold = total - in_r, sum(1 for t in temps if t > cfg.TEMP_HIGH), sum(1 for t in temps if t < cfg.TEMP_LOW)
    gl = "Last Known Compliance" if all_off else "Live Compliance"
    stats = html.Div([_stat("Total", str(total), cfg.COLORS["text"]),
                       _stat("In Range", str(in_r), cfg.COLORS["success"]),
                       _stat("Out", str(out), cfg.COLORS["warning"] if out else cfg.COLORS["success"]),
                       _stat("Too Hot", str(hot), cfg.COLORS["danger"] if hot else cfg.COLORS["success"]),
                       _stat("Too Cold", str(cold), cfg.COLORS["primary_light"] if cold else cfg.COLORS["success"])],
                      style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "justifyContent": "center", "padding": "4px 0"})
    return dbc.Row([
        dbc.Col(dbc.Card([dbc.CardHeader(gl, style={"backgroundColor": cfg.COLORS["card_solid"], "border": "none",
            "fontWeight": "600", "fontSize": "0.8rem", "color": cfg.COLORS["text_muted"]}),
            dbc.CardBody([dcc.Graph(figure=compliance_gauge(pct, gl), config={"displayModeBar": False}), stats])],
            className="glass-panel"), lg=5, className="mb-3"),
        dbc.Col(dbc.Card([dbc.CardHeader("7-Day Trend", style={"backgroundColor": cfg.COLORS["card_solid"], "border": "none",
            "fontWeight": "600", "fontSize": "0.8rem", "color": cfg.COLORS["text_muted"]}),
            dbc.CardBody(dcc.Graph(figure=compliance_trend(comp or []), config={"displayModeBar": False}))],
            className="glass-panel"), lg=7, className="mb-3"),
    ], className="g-3 mt-1")


# ── Alert table ──────────────────────────────────────────────────────────────

@callback(Output("mon-alert-table", "children"), Input("store-readings", "data"))
def render_alert_table(rd):
    if not rd:
        return html.Div()
    alerts = rd.get("alerts", [])
    if not alerts:
        return html.Div()
    td = [{"Priority": cfg.SEVERITY_LABELS.get(a.get("severity", ""), a.get("severity", "")),
           "Type": a.get("alert_type", ""), "What": a.get("message", "")[:42],
           "When": _fmt_time(a.get("triggered_at", "")), "Status": a.get("state", "ACTIVE").title()}
          for a in alerts[:30]]
    tbl = dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in ["Priority", "Type", "What", "When", "Status"]],
        data=td, sort_action="native", page_size=8,
        style_header={"backgroundColor": cfg.COLORS["card_solid"], "color": cfg.COLORS["text_muted"],
                       "fontWeight": "600", "border": f"1px solid {cfg.COLORS['card_border']}",
                       "fontSize": "0.7rem", "textTransform": "uppercase"},
        style_cell={"backgroundColor": cfg.COLORS["bg"], "color": cfg.COLORS["text"],
                     "border": f"1px solid {cfg.COLORS['card_border']}", "fontSize": "0.8rem",
                     "padding": "7px 10px", "textAlign": "left"},
        style_data_conditional=[
            {"if": {"filter_query": "{Priority} = Urgent"}, "color": cfg.COLORS["critical"], "fontWeight": "600"},
            {"if": {"filter_query": "{Priority} = Forecast"}, "color": cfg.COLORS["accent"], "fontWeight": "600"},
            {"if": {"filter_query": "{Status} = Active"}, "backgroundColor": cfg.COLORS["danger_dim"]},
            {"if": {"filter_query": "{Status} = Forecast"}, "backgroundColor": cfg.COLORS["accent_dim"]},
            {"if": {"filter_query": "{Status} = Dismissed"}, "color": cfg.COLORS["text_muted"]},
        ])
    return dbc.Card([
        dbc.CardHeader("Alert History", style={"backgroundColor": cfg.COLORS["card_solid"], "border": "none",
                                                "fontWeight": "600", "fontSize": "0.8rem", "color": cfg.COLORS["text_muted"]}),
        dbc.CardBody(tbl),
    ], className="glass-panel mb-3")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pill(v, label, c):
    return html.Div([
        html.Span(v, style={"color": c, "fontWeight": "700",
                             "fontSize": "1rem", "marginRight": "4px"}),
        html.Span(label, style={"color": cfg.COLORS["text_muted"],
                                 "fontSize": "0.68rem"})])

def _kpi(label, value, color):
    return html.Div([html.Div(label, style={"fontSize": "0.56rem", "color": cfg.COLORS["text_muted"],
                                             "textTransform": "uppercase", "letterSpacing": "1px"}),
                      html.Div(value, style={"fontSize": "0.86rem", "fontWeight": "600", "color": color})],
                     className="kpi-card")

def _stat(label, value, color):
    return html.Div([html.Div(value, style={"fontWeight": "700", "fontSize": "0.88rem", "color": color}),
                      html.Div(label, style={"fontSize": "0.52rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase"})],
                     style={"textAlign": "center", "minWidth": "52px"})

def _fmt_time(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %H:%M")
    except Exception:
        return ""
