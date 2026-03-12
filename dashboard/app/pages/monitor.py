"""Single-page dashboard — unified Live + History view.

Performance-optimized callback architecture:
  - state_pump (tick only)     → states, alerts, compliance   [slow path, every 10s]
  - readings_pump (selection)  → readings for 1 sensor        [fast path, on click/range]
  - Clientside callbacks       → filter/range/select           [instant, no server]
  - Display callbacks          → pure render from stores       [fast, no DB]
"""

from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
import numpy as np
from dash import (
    Input,
    Output,
    State,
    callback,
    ctx,
    dash_table,
    dcc,
    html,
    no_update,
)

from app import config as cfg
from app.auth import get_client_id
from app.data.provider import get_provider

if "/" not in {v.get("path") for v in dash.page_registry.values()}:
    dash.register_page(__name__, path="/", name="Monitor")

_F = "'Inter', 'DM Sans', system-ui, sans-serif"
_RANGES = [
    {"label": "LIVE", "value": "live"},
    {"label": "1 h", "value": "1"},
    {"label": "6 h", "value": "6"},
    {"label": "12 h", "value": "12"},
    {"label": "24 h", "value": "24"},
]
_MAX_HISTORY_DAYS = 120
_TS = cfg.COLORS["text"]
_TM = cfg.COLORS["text_muted"]
_PR = cfg.COLORS["primary"]
_BD = cfg.COLORS["card_border"]


# ═══════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════

def layout(**kwargs):
    today = datetime.now(timezone.utc).date()
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
        _filter_bar(today - timedelta(days=_MAX_HISTORY_DAYS), today),
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
    dd = {
        "backgroundColor": "#fff", "color": _TS,
        "border": f"1px solid {_BD}", "borderRadius": "8px",
        "fontSize": "0.78rem",
    }
    lbl = {
        "fontSize": "0.62rem", "color": _TM,
        "textTransform": "uppercase", "letterSpacing": "0.8px",
        "fontWeight": "600", "marginBottom": "3px",
    }
    return html.Div([
        html.Div([
            html.Div([
                html.Label("Facility", style=lbl),
                dcc.Dropdown(
                    id="filter-location", placeholder="All Facilities",
                    searchable=True, clearable=True,
                    className="dash-dd", style=dd,
                ),
            ], style={"flex": "1", "minWidth": "160px"}),
            html.Div([
                html.Label("Sensor", style=lbl),
                dcc.Dropdown(
                    id="filter-mac", placeholder="All Sensors",
                    searchable=True, clearable=True,
                    className="dash-dd", style=dd,
                ),
            ], style={"flex": "1", "minWidth": "160px"}),
            html.Div([
                html.Label("Date Range", style=lbl),
                dcc.DatePickerRange(
                    id="date-range-picker",
                    min_date_allowed=str(min_date),
                    max_date_allowed=str(max_date),
                    initial_visible_month=str(max_date),
                    start_date=None, end_date=None,
                    display_format="MM/DD/YY",
                    number_of_months_shown=1,
                    className="dash-dp",
                ),
            ], style={"flex": "0.9", "minWidth": "180px"}),
            html.Button(
                "\u21BA Reset", id="filter-reset", n_clicks=0,
                className="btn-reset",
            ),
        ], style={
            "display": "flex", "gap": "12px",
            "flexWrap": "wrap", "alignItems": "flex-end",
        }),
    ], className="wcard fbar", style={
        "padding": "14px 18px", "marginBottom": "10px",
    })


# ═══════════════════════════════════════════════════════════════════════
# CLIENTSIDE CALLBACKS — zero server round-trip
# ═══════════════════════════════════════════════════════════════════════

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
        if (start && end) {
            return ["custom",
                    {start: start.substring(0,10), end: end.substring(0,10)}];
        }
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
    """function(mac, cur) {
        if (mac === undefined || mac === null || mac === cur)
            return dash_clientside.no_update;
        return mac;
    }""",
    Output("mon-selected", "data", allow_duplicate=True),
    Input("filter-mac", "value"),
    State("mon-selected", "data"),
    prevent_initial_call=True,
)

# Sensor card click — fully clientside, no server round-trip
dash.clientside_callback(
    """function() {
        var ctx = dash_clientside.callback_context;
        if (!ctx.triggered.length) return dash_clientside.no_update;
        var t = ctx.triggered[0];
        if (!t.value) return dash_clientside.no_update;
        try { return JSON.parse(t.prop_id.split('.')[0]).index; }
        catch(e) { return dash_clientside.no_update; }
    }""",
    Output("mon-selected", "data"),
    Input({"type": "sensor-card", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)


# ═══════════════════════════════════════════════════════════════════════
# DATA CALLBACKS — split into two independent paths
# ═══════════════════════════════════════════════════════════════════════

@callback(
    Output("store-locations", "data"),
    Input("mon-tick", "n_intervals"),
    prevent_initial_call="initial_duplicate",
)
def load_locations(_):
    return get_provider(get_client_id()).get_locations()


@callback(Output("filter-location", "options"), Input("store-locations", "data"))
def update_location_options(locations):
    return [{"label": loc, "value": loc} for loc in locations] if locations else []


@callback(
    Output("filter-mac", "options"),
    Input("filter-location", "value"),
    Input("store-states", "data"),
)
def update_mac_options(location, states):
    if not states:
        return []
    filt = (
        [s for s in states if s.get("location") == location]
        if location else states
    )
    return [{"label": s["device_id"], "value": s["device_id"]} for s in filt]


# ── SLOW PATH: tick-only — states, alerts, compliance ────
@callback(
    Output("store-states", "data"),
    Output("store-alerts", "data"),
    Output("store-compliance", "data"),
    Output("mon-selected", "data", allow_duplicate=True),
    Input("mon-tick", "n_intervals"),
    State("mon-selected", "data"),
    State("filter-location", "value"),
    prevent_initial_call="initial_duplicate",
)
def state_pump(_, selected_id, location_filter):
    prov = get_provider(get_client_id())
    states = prov.get_all_sensor_states()
    alerts = prov.get_live_alerts()
    compliance = prov.get_compliance_history(7)

    visible = (
        [s for s in states if s.get("location") == location_filter]
        if location_filter else states
    )
    auto = False
    if visible:
        vids = {s["device_id"] for s in visible}
        if not selected_id or selected_id not in vids:
            selected_id, auto = visible[0]["device_id"], True

    return states, alerts, compliance, (selected_id if auto else no_update)


# ── FAST PATH: selection/range changes — readings only ───
@callback(
    Output("store-readings", "data"),
    Input("mon-selected", "data"),
    Input("range-mode", "data"),
    Input("store-date-range", "data"),
    Input("mon-tick", "n_intervals"),
    State("store-states", "data"),
    prevent_initial_call="initial_duplicate",
)
def readings_pump(selected_id, range_mode, date_range, _, states):
    if not selected_id:
        return None
    if ctx.triggered_id == "mon-tick" and range_mode != "live":
        return no_update
    prov = get_provider(get_client_id())
    return _fetch_readings(prov, selected_id, range_mode, states, date_range)


def _fetch_readings(prov, device_id, range_mode, states, date_range=None):
    now = datetime.now(timezone.utc)
    state = (
        next((s for s in states if s["device_id"] == device_id), None)
        if states else None
    )
    is_offline = state and state.get("status") == "offline"
    anchor = now
    if is_offline and state.get("last_seen"):
        try:
            anchor = datetime.fromisoformat(
                state["last_seen"].replace("Z", "+00:00"),
            )
        except (ValueError, TypeError):
            pass

    if range_mode == "custom" and date_range:
        since = datetime.fromisoformat(date_range["start"]).replace(
            tzinfo=timezone.utc,
        )
        until = datetime.fromisoformat(date_range["end"]).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc,
        )
        hours = max(1, int((until - since).total_seconds() / 3600))
    else:
        hours = (
            2 if range_mode == "live"
            else int(range_mode) if range_mode and range_mode.isdigit()
            else 2
        )
        since = anchor - timedelta(hours=hours)
        until = anchor if is_offline else now

    readings = prov.get_readings(
        device_id,
        since.strftime("%Y-%m-%dT%H:%M:00Z"),
        until.strftime("%Y-%m-%dT%H:%M:00Z"),
    )
    show_fc = range_mode == "live" and not is_offline
    fc = prov.get_forecast_series(device_id, "30min", 30) if show_fc else []
    alert_hist = prov.get_alert_history(device_id, days=max(hours // 24, 7))
    fc_alerts = _build_forecast_alerts(fc, device_id) if fc else []

    return {
        "device_id": device_id, "readings": readings, "forecast": fc,
        "offline": bool(is_offline), "alerts": alert_hist + fc_alerts,
        "range_mode": range_mode, "forecast_alert_count": len(fc_alerts),
    }


def _build_forecast_alerts(fc_series, device_id):
    out = []
    for f in fc_series:
        pred = f.get("predicted", 0)
        if pred > cfg.TEMP_HIGH:
            out.append({
                "triggered_at": f["timestamp"], "temperature": str(pred),
                "alert_type": "FORECAST_HIGH", "severity": "FORECAST",
                "message": f"Forecast {pred:.1f}°F may exceed safe limit",
                "state": "FORECAST", "device_id": device_id,
            })
        elif pred < cfg.TEMP_LOW:
            out.append({
                "triggered_at": f["timestamp"], "temperature": str(pred),
                "alert_type": "FORECAST_LOW", "severity": "FORECAST",
                "message": f"Forecast {pred:.1f}°F may drop below safe limit",
                "state": "FORECAST", "device_id": device_id,
            })
    return out


# ═══════════════════════════════════════════════════════════════════════
# DISPLAY CALLBACKS — pure rendering, no DB calls
# ═══════════════════════════════════════════════════════════════════════

@callback(
    Output("mon-banner", "children"),
    Input("store-states", "data"), Input("store-alerts", "data"),
    Input("filter-location", "value"), Input("store-readings", "data"),
)
def render_banner(states, alerts, location_filter, readings_data):
    states, alerts = states or [], alerts or []
    if location_filter:
        fmacs = {s["device_id"] for s in states
                 if s.get("location") == location_filter}
        vis_s = [s for s in states if s["device_id"] in fmacs]
        vis_a = [a for a in alerts if a.get("device_id") in fmacs]
    else:
        vis_s, vis_a = states, alerts

    total = len(vis_s)
    online = sum(1 for s in vis_s if s.get("status") != "offline")
    temps = [s["temperature"] for s in vis_s if s.get("status") != "offline"]
    avg = float(np.mean(temps)) if temps else 0
    low_bat = sum(
        1 for s in vis_s
        if s.get("battery_pct", 100) < cfg.BATTERY_LOW
        and s.get("status") != "offline"
    )
    n_a = len(vis_a)
    fc_n = (readings_data.get("forecast_alert_count", 0)
            if readings_data else 0)
    title = location_filter or "All Facilities"

    if avg >= cfg.TEMP_CRITICAL_HIGH or n_a >= 5:
        accent = cfg.COLORS["danger"]
    elif avg >= cfg.TEMP_HIGH or avg <= cfg.TEMP_LOW or n_a > 0 or low_bat:
        accent = cfg.COLORS["warning"]
    else:
        accent = cfg.COLORS["success"]

    pills = [
        _pill(f"{online}/{total}", "Sensors",
              cfg.COLORS["success"] if online == total else cfg.COLORS["warning"]),
        _pill(str(n_a), "Alerts",
              cfg.COLORS["danger"] if n_a else cfg.COLORS["success"]),
    ]
    if fc_n:
        pills.append(_pill(str(fc_n), "Forecast", cfg.COLORS["accent"]))
    pills += [
        _pill(f"{avg:.1f}°F", "Avg Temp", _PR),
        _pill(str(low_bat), "Low Battery",
              cfg.COLORS["danger"] if low_bat else cfg.COLORS["success"]),
    ]

    return html.Div(
        dbc.Row([
            dbc.Col(html.Div([
                html.Div(title, style={
                    "fontWeight": "700", "fontSize": "1.05rem",
                    "color": _TS, "textTransform": "uppercase",
                    "letterSpacing": "1px",
                }),
            ]), lg=4),
            dbc.Col(html.Div(
                pills,
                className="d-flex gap-3 flex-wrap justify-content-end",
            ), lg=8),
        ], className="align-items-center"),
        className="wcard",
        style={
            "padding": "12px 18px", "marginBottom": "10px",
            "borderLeft": f"4px solid {accent}",
        },
    )


def _sensor_color(s, alert_devs):
    did = s["device_id"]
    st = s.get("status", "online")
    temp = s["temperature"]
    anom = s.get("anomaly")
    bat = s.get("battery_pct", 100)
    if (st == "offline" or did in alert_devs
            or temp >= cfg.TEMP_HIGH or temp <= cfg.TEMP_LOW):
        return "red"
    if anom or bat < cfg.BATTERY_WARN or st == "degraded":
        return "yellow"
    return "green"


@callback(
    Output("mon-status-bar", "children"),
    Input("store-states", "data"), Input("store-alerts", "data"),
    Input("status-filter", "data"), Input("filter-location", "value"),
)
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
        ("all", "All", str(total), None),
        ("red", "Critical", str(cm["red"]), cfg.COLORS["danger"]),
        ("yellow", "Warning", str(cm["yellow"]), cfg.COLORS["warning"]),
        ("green", "Normal", str(cm["green"]), cfg.COLORS["success"]),
    ]
    for val, label, count, dot_c in defs:
        active = sf == val
        cn = f"fpill{' fpill-on' if active else ''}"
        ch = []
        if dot_c:
            ch.append(html.Span(className="pdot", style={
                "backgroundColor": dot_c,
            }))
        ch.append(html.Span(f"{label} "))
        ch.append(html.Span(count, style={
            "fontWeight": "700", "fontSize": "0.78rem",
        }))
        pills.append(html.Button(
            ch, id={"type": "status-btn", "index": val},
            n_clicks=0, className=cn,
        ))

    return html.Div([
        html.Span(f"\u2609 {total} Sensors", style={
            "fontWeight": "600", "fontSize": "0.78rem",
            "color": _TM, "marginRight": "14px",
        }),
        html.Div(pills, style={"display": "flex", "gap": "6px"}),
    ], style={
        "display": "flex", "alignItems": "center",
        "marginBottom": "10px", "flexWrap": "wrap",
    })


# ── Alert cards ──────────────────────────────────────────

@callback(
    Output("mon-sensor-alerts", "children"),
    Input("store-alerts", "data"),
    Input("mon-selected", "data"),
    Input("note-feedback", "data"),
)
def render_alerts(alerts, selected_id, note_fb):
    if not alerts or not selected_id:
        return html.Div()
    sensor_alerts = sorted(
        [a for a in alerts if a.get("device_id") == selected_id],
        key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(
            x.get("severity", ""), 9,
        ),
    )
    if not sensor_alerts:
        return html.Div()
    items = []
    for a in sensor_alerts:
        sev = a.get("severity", "")
        sc = cfg.SEVERITY_COLORS.get(sev, _TM)
        idx = f"{a['device_id']}|{a['alert_type']}"
        noted = note_fb and note_fb.get("index") == idx
        if noted:
            action = html.Span("\u2705 Sent", style={
                "color": cfg.COLORS["success"],
                "fontWeight": "700", "fontSize": "0.7rem",
            })
        elif sev in ("CRITICAL", "HIGH"):
            action = html.Div([
                html.Button("\U0001f4cb Note", id={
                    "type": "alert-note", "index": idx,
                }, n_clicks=0, style={
                    "background": _PR, "color": "#fff", "border": "none",
                    "borderRadius": "6px", "padding": "3px 10px",
                    "fontSize": "0.62rem", "cursor": "pointer",
                    "marginRight": "6px",
                }),
                html.Button("\u2715", id={
                    "type": "alert-dismiss", "index": idx,
                }, n_clicks=0, style={
                    "background": cfg.COLORS["danger"],
                    "color": "#fff", "border": "none",
                    "borderRadius": "6px", "padding": "3px 8px",
                    "fontSize": "0.62rem", "cursor": "pointer",
                }),
            ], style={"display": "flex", "marginTop": "4px"})
        else:
            action = ""
        items.append(html.Div([
            html.Div([
                html.Span(cfg.SEVERITY_LABELS.get(sev, sev), style={
                    "backgroundColor": sc, "color": "#fff",
                    "padding": "2px 10px", "borderRadius": "10px",
                    "fontSize": "0.6rem", "fontWeight": "700",
                    "marginRight": "8px",
                }),
                html.Span(a.get("message", "")[:50], style={
                    "fontSize": "0.78rem", "color": _TS, "flex": "1",
                }),
                html.Span(_fmt_time(a.get("triggered_at", "")), style={
                    "fontSize": "0.66rem", "color": _TM, "marginLeft": "auto",
                }),
            ], style={
                "display": "flex", "alignItems": "center", "gap": "4px",
            }),
            action,
        ], className="acard", style={"borderLeft": f"3px solid {sc}"}))

    return html.Div([
        html.Div(html.Span(
            f"\u26A0 {len(sensor_alerts)} Alert"
            f"{'s' if len(sensor_alerts) != 1 else ''}",
            style={"fontWeight": "700", "fontSize": "0.8rem",
                    "color": cfg.COLORS["warning"]},
        ), style={"marginBottom": "6px"}),
        *items,
    ], style={"marginBottom": "10px"})


@callback(
    Output("store-alerts", "data", allow_duplicate=True),
    Input({"type": "alert-dismiss", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def handle_dismiss(clicks):
    if not ctx.triggered or not any(clicks):
        return no_update
    tid = ctx.triggered_id
    if tid and isinstance(tid, dict):
        parts = tid["index"].split("|", 1)
        if len(parts) == 2:
            get_provider(get_client_id()).dismiss_alert(parts[0], parts[1])
    return get_provider(get_client_id()).get_live_alerts()


@callback(
    Output("note-feedback", "data"),
    Output("store-alerts", "data", allow_duplicate=True),
    Input({"type": "alert-note", "index": dash.ALL}, "n_clicks"),
    State("store-states", "data"),
    prevent_initial_call=True,
)
def handle_note(clicks, states):
    if not ctx.triggered or not any(clicks):
        return no_update, no_update
    tid = ctx.triggered_id
    if tid and isinstance(tid, dict):
        parts = tid["index"].split("|", 1)
        if len(parts) == 2:
            st = next((s for s in (states or [])
                        if s["device_id"] == parts[0]), {})
            prov = get_provider(get_client_id())
            prov.send_alert_note(parts[0], parts[1], {
                "device_id": parts[0], "alert_type": parts[1],
                "sensor_state": st,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return (
                {"index": tid["index"],
                 "ts": datetime.now(timezone.utc).isoformat()},
                prov.get_live_alerts(),
            )
    return no_update, no_update


# ── Sensor grid ──────────────────────────────────────────

@callback(
    Output("mon-grid", "children"),
    Input("store-states", "data"), Input("store-alerts", "data"),
    Input("mon-selected", "data"), Input("status-filter", "data"),
    Input("filter-location", "value"),
)
def render_grid(states, alerts, selected_id, status_filter, location_filter):
    states = states or []
    if location_filter:
        states = [s for s in states if s.get("location") == location_filter]
    alert_devs = {a.get("device_id") for a in (alerts or [])}
    for s in states:
        s["_color"] = _sensor_color(s, alert_devs)
    if status_filter and status_filter != "all":
        states = [s for s in states if s.get("_color") == status_filter]
    states.sort(key=lambda s: (
        {"red": 0, "yellow": 1, "green": 2}.get(s.get("_color"), 2),
        -s["temperature"],
    ))

    tiles = []
    for s in states:
        temp = s["temperature"]
        did = s["device_id"]
        st = s.get("status", "online")
        bat = s.get("battery_pct", 100)
        sig = s.get("signal_label", "Good")
        loc = s.get("location", "")
        c = {
            "green": cfg.COLORS["success"],
            "yellow": cfg.COLORS["warning"],
            "red": cfg.COLORS["danger"],
        }.get(s.get("_color"), _TM)
        if st == "offline":
            c = "#94a3b8"
        bat_c = (
            cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW
            else cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN
            else _TM
        )
        is_sel = did == selected_id
        cn = f"stile{' stile-sel' if is_sel else ''}"
        loc_el = (
            html.Div(loc, style={
                "fontSize": "0.48rem", "color": _TM,
                "overflow": "hidden", "textOverflow": "ellipsis",
                "whiteSpace": "nowrap",
            }) if loc else ""
        )
        tiles.append(html.Div([
            html.Div([
                html.Span("\u25CF ", style={
                    "color": c, "fontSize": "0.5rem",
                }),
                html.Span(did, style={
                    "fontFamily": "monospace", "fontSize": "0.58rem",
                    "color": _TM,
                }),
            ], style={
                "lineHeight": "1.2", "overflow": "hidden",
                "textOverflow": "ellipsis", "whiteSpace": "nowrap",
            }),
            html.Div(
                f"{temp:.1f}°F{'*' if st == 'offline' else ''}",
                style={
                    "fontWeight": "700", "fontSize": "1rem",
                    "color": c, "lineHeight": "1.3",
                },
            ),
            loc_el,
            html.Div([
                html.Span(f"\U0001F50B{bat}%", style={
                    "fontSize": "0.52rem", "color": bat_c,
                    "marginRight": "4px",
                }),
                html.Img(src=cfg.SIGNAL_ICONS.get(sig, ""), style={
                    "height": "11px", "verticalAlign": "middle",
                }),
            ], style={"lineHeight": "1.2"}),
        ], id={"type": "sensor-card", "index": did}, n_clicks=0,
            className=cn, style={"borderTop": f"3px solid {c}"}))

    if not tiles:
        grid = html.Div("No sensors match this filter.", style={
            "color": _TM, "fontSize": "0.82rem", "padding": "14px 0",
        })
    else:
        grid = html.Div(tiles, style={
            "display": "flex", "flexWrap": "wrap", "gap": "8px",
            "maxHeight": "240px", "overflowY": "auto", "paddingBottom": "4px",
        })
    return html.Div(grid, style={"marginBottom": "10px"})


# ── KPIs ─────────────────────────────────────────────────

@callback(
    Output("mon-kpis", "children"),
    Input("store-readings", "data"),
    Input("store-states", "data"),
    Input("mon-selected", "data"),
)
def render_kpis(rd, states, selected_id):
    if not rd or not rd.get("readings"):
        return html.Div()
    readings = rd["readings"]
    is_off = rd.get("offline", False)
    did = rd.get("device_id", selected_id)
    state = next((s for s in (states or []) if s["device_id"] == did), None)
    temps = [r["temperature"] for r in readings]
    if not temps:
        return html.Div()
    arr = np.array(temps, dtype=float)
    cur = temps[-1]
    hi, lo, avg = float(np.max(arr)), float(np.min(arr)), float(np.mean(arr))
    fc = rd.get("forecast", [])
    if fc:
        pred = fc[-1].get("predicted", cur)
        fl = "Forecast"
        fv = f"{pred:.1f}°F"
        fc_c = cfg.COLORS["danger"] if pred > cfg.TEMP_HIGH else cfg.COLORS["accent"]
    elif is_off:
        fl, fv, fc_c = "Last", f"{cur:.1f}°F", _TM
    else:
        fl, fv, fc_c = "Forecast", "N/A", _TM
    in_r = sum(1 for t in temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    cp = round(in_r / len(temps) * 100, 1)
    roc = state.get("rate_of_change", 0) if state else 0
    trend = (
        "\u2191 Rising" if roc > 0.5
        else "\u2193 Falling" if roc < -0.5
        else "\u2192 Steady"
    )
    tc = (
        cfg.COLORS["warning"] if roc > 0.5
        else _PR if roc < -0.5
        else cfg.COLORS["success"]
    )
    st = state.get("status", "online") if state else "online"
    sc = (
        cfg.COLORS["success"] if st == "online"
        else cfg.COLORS["warning"] if st == "degraded"
        else _TM
    )
    bat = state.get("battery_pct", 0) if state else 0
    bc = (
        cfg.COLORS["danger"] if bat < cfg.BATTERY_LOW
        else cfg.COLORS["warning"] if bat < cfg.BATTERY_WARN
        else cfg.COLORS["success"]
    )
    sig = state.get("signal_label", "Good") if state else "Good"
    loc = state.get("location", "") if state else ""
    loc_badge = (
        html.Span(f" \u2022 {loc}", style={
            "color": _TM, "fontSize": "0.68rem",
        }) if loc else ""
    )

    header = html.Div([
        html.Span(f"\u25CF {st.upper()}", style={
            "color": sc, "fontWeight": "600",
            "fontSize": "0.68rem", "marginRight": "8px",
        }),
        html.Span(did or "", style={
            "fontFamily": "monospace", "color": _TM, "fontSize": "0.78rem",
        }),
        loc_badge,
        html.Span(f"{cur:.1f}°F", style={
            "color": _PR, "fontWeight": "700",
            "fontSize": "1.4rem", "marginLeft": "12px",
        }),
    ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"})

    data = [
        ("High", f"{hi:.1f}°F",
         cfg.COLORS["danger"] if hi > cfg.TEMP_HIGH else _TS),
        ("Low", f"{lo:.1f}°F",
         _PR if lo < cfg.TEMP_LOW else _TS),
        ("Avg", f"{avg:.1f}°F", _PR),
        ("Trend", trend if st == "online" else "N/A",
         tc if st == "online" else _TM),
        (fl, fv, fc_c),
        ("In Range", f"{cp}%",
         cfg.COLORS["success"] if cp >= cfg.COMPLIANCE_TARGET
         else cfg.COLORS["warning"]),
        ("Battery", f"{bat}%" if st != "offline" else "N/A",
         bc if st != "offline" else _TM),
        ("Signal", sig,
         cfg.COLORS["success"] if sig in ("Strong", "Good")
         else cfg.COLORS["warning"]),
    ]
    krow = dbc.Row(
        [dbc.Col(_kpi(lb, v, c), xs=4, md=True, className="mb-2")
         for lb, v, c in data],
        className="g-2",
    )
    abox = html.Div()
    if state and state.get("anomaly") and state.get("anomaly_reason"):
        abox = html.Div([
            html.Span("\u26A0 Anomaly: ", style={
                "fontWeight": "700", "color": cfg.COLORS["warning"],
            }),
            html.Span(state["anomaly_reason"], style={"color": _TS}),
        ], className="wcard", style={
            "backgroundColor": cfg.COLORS["warning_dim"],
            "borderLeft": f"3px solid {cfg.COLORS['warning']}",
            "padding": "8px 12px", "marginBottom": "8px",
            "fontSize": "0.8rem",
        })
    return html.Div([header, abox, krow], style={"marginBottom": "10px"})


# ── Range bar ────────────────────────────────────────────

@callback(Output("mon-range-bar", "children"), Input("range-mode", "data"))
def render_range_bar(current):
    btns = []
    for r in _RANGES:
        is_a = r["value"] == current
        is_l = r["value"] == "live"
        cn = "rbtn"
        if is_a and is_l:
            cn += " rbtn-live"
        elif is_a:
            cn += " rbtn-on"
        btns.append(html.Button(
            r["label"],
            id={"type": "range-btn", "index": r["value"]},
            n_clicks=0, className=cn,
        ))
    return html.Div(btns, style={
        "display": "flex", "gap": "6px", "flexWrap": "wrap",
        "marginBottom": "10px", "padding": "4px 0",
    })


# ── Chart ────────────────────────────────────────────────

@callback(
    Output("mon-chart-container", "children"),
    Input("store-readings", "data"),
)
def render_chart(rd):
    if not rd or not rd.get("readings"):
        return html.Div(
            "Select a sensor to view chart", className="wcard",
            style={"padding": "30px", "textAlign": "center",
                    "color": _TM, "fontSize": "0.85rem",
                    "marginBottom": "10px"},
        )
    from app.pages.charts import unified_chart
    rm = rd.get("range_mode", "live")
    h = 2 if rm == "live" else int(rm) if rm and rm.isdigit() else 2
    fig = unified_chart(
        rd["readings"], rd.get("forecast", []), rd.get("alerts", []),
        rm, rd.get("offline", False), 360 if h <= 48 else 400,
    )
    return dbc.Card(
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        className="wcard mb-2",
    )


# ── Compliance — reacts to facility filter ───────────────

@callback(
    Output("mon-compliance", "children"),
    Input("store-states", "data"),
    Input("store-compliance", "data"),
    Input("filter-location", "value"),
)
def render_compliance(states, comp, location_filter):
    from app.pages.charts import compliance_gauge, compliance_trend
    if not states:
        return html.Div()

    if location_filter:
        fmacs = {s["device_id"]
                 for s in states if s.get("location") == location_filter}
        states = [s for s in states if s["device_id"] in fmacs]
    if not states:
        return html.Div()

    total = len(states)
    online = [s for s in states if s.get("status") != "offline"]
    offline_n = total - len(online)
    all_off = not online

    online_temps = [s["temperature"] for s in online]
    in_r = sum(1 for t in online_temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    hot = sum(1 for t in online_temps if t > cfg.TEMP_HIGH)
    cold = sum(1 for t in online_temps if t < cfg.TEMP_LOW)
    issue = hot + cold
    pct = round(in_r / len(online) * 100, 1) if online else 0.0

    scope = location_filter if location_filter else "All Facilities"
    gl = (
        f"Last Known — {scope}" if all_off
        else f"Live Compliance — {scope}"
    )

    stats = html.Div([
        _stat("Total", str(total), _TS),
        _stat("In Range", str(in_r), cfg.COLORS["success"]),
        _stat("Issue", str(issue),
              cfg.COLORS["warning"] if issue else cfg.COLORS["success"]),
        _stat("Too Hot", str(hot),
              cfg.COLORS["danger"] if hot else cfg.COLORS["success"]),
        _stat("Too Cold", str(cold),
              _PR if cold else cfg.COLORS["success"]),
        _stat("Offline", str(offline_n),
              "#94a3b8" if offline_n else cfg.COLORS["success"]),
    ], style={
        "display": "flex", "gap": "10px", "flexWrap": "wrap",
        "justifyContent": "center", "padding": "4px 0",
    })

    trend_data = comp or []
    return dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader(gl, style={
                "backgroundColor": "#f8fafc", "border": "none",
                "fontWeight": "600", "fontSize": "0.78rem", "color": _TM,
            }),
            dbc.CardBody([
                dcc.Graph(figure=compliance_gauge(pct, gl),
                          config={"displayModeBar": False}),
                stats,
            ]),
        ], className="wcard"), lg=5, className="mb-3"),
        dbc.Col(dbc.Card([
            dbc.CardHeader("7-Day Compliance Trend", style={
                "backgroundColor": "#f8fafc", "border": "none",
                "fontWeight": "600", "fontSize": "0.78rem", "color": _TM,
            }),
            dbc.CardBody(dcc.Graph(
                figure=compliance_trend(trend_data),
                config={"displayModeBar": False},
            )),
        ], className="wcard"), lg=7, className="mb-3"),
    ], className="g-3 mt-1")


# ── Alert table ──────────────────────────────────────────

@callback(
    Output("mon-alert-table", "children"),
    Input("store-readings", "data"),
)
def render_alert_table(rd):
    if not rd:
        return html.Div()
    alerts = rd.get("alerts", [])
    if not alerts:
        return html.Div()
    td = [{
        "Priority": cfg.SEVERITY_LABELS.get(
            a.get("severity", ""), a.get("severity", ""),
        ),
        "Type": a.get("alert_type", ""),
        "What": a.get("message", "")[:42],
        "When": _fmt_time(a.get("triggered_at", "")),
        "Status": a.get("state", "ACTIVE").title(),
    } for a in alerts[:30]]
    tbl = dash_table.DataTable(
        columns=[{"name": c, "id": c}
                 for c in ["Priority", "Type", "What", "When", "Status"]],
        data=td, sort_action="native", page_size=8,
        style_header={
            "backgroundColor": "#f8fafc", "color": _TM,
            "fontWeight": "600",
            "border": f"1px solid {_BD}",
            "fontSize": "0.7rem", "textTransform": "uppercase",
        },
        style_cell={
            "backgroundColor": "#fff", "color": _TS,
            "border": f"1px solid {_BD}",
            "fontSize": "0.8rem", "padding": "7px 10px",
            "textAlign": "left",
        },
        style_data_conditional=[
            {"if": {"filter_query": "{Priority} = Urgent"},
             "color": cfg.COLORS["critical"], "fontWeight": "600"},
            {"if": {"filter_query": "{Priority} = Forecast"},
             "color": cfg.COLORS["accent"], "fontWeight": "600"},
            {"if": {"filter_query": "{Status} = Active"},
             "backgroundColor": cfg.COLORS["danger_dim"]},
            {"if": {"filter_query": "{Status} = Forecast"},
             "backgroundColor": cfg.COLORS["accent_dim"]},
            {"if": {"filter_query": "{Status} = Dismissed"},
             "color": _TM},
        ],
    )
    return dbc.Card([
        dbc.CardHeader("Alert History", style={
            "backgroundColor": "#f8fafc", "border": "none",
            "fontWeight": "600", "fontSize": "0.78rem", "color": _TM,
        }),
        dbc.CardBody(tbl),
    ], className="wcard mb-3")


# ── Helpers ──────────────────────────────────────────────

def _pill(v, label, c):
    return html.Div([
        html.Span(v, style={
            "color": c, "fontWeight": "700",
            "fontSize": "1rem", "marginRight": "4px",
        }),
        html.Span(label, style={
            "color": _TM, "fontSize": "0.68rem",
        }),
    ])


def _kpi(label, value, color):
    return html.Div([
        html.Div(label, style={
            "fontSize": "0.56rem", "color": _TM,
            "textTransform": "uppercase", "letterSpacing": "1px",
        }),
        html.Div(value, style={
            "fontSize": "0.86rem", "fontWeight": "600", "color": color,
        }),
    ], className="kcard")


def _stat(label, value, color):
    return html.Div([
        html.Div(value, style={
            "fontWeight": "700", "fontSize": "0.88rem", "color": color,
        }),
        html.Div(label, style={
            "fontSize": "0.52rem", "color": _TM,
            "textTransform": "uppercase",
        }),
    ], style={"textAlign": "center", "minWidth": "52px"})


def _fmt_time(iso):
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00"),
        ).strftime("%b %d, %H:%M")
    except Exception:
        return ""
