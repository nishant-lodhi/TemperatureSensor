"""Page 2: History & Reports — sensor history, forecast, compliance, alerts."""

from datetime import datetime, timedelta, timezone

import dash
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dash_table, dcc, html, no_update

from app import config as cfg
from app.auth import get_client_id
from app.data.provider import get_provider

dash.register_page(__name__, path="/history", name="History & Reports")

_FONT = "'DM Sans', system-ui, sans-serif"


def layout(**kwargs):
    return html.Div([
        dcc.Interval(id="hist-tick", interval=cfg.REFRESH_HISTORY_MS),
        dbc.Row([
            dbc.Col([
                html.Label("Sensor", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.75rem", "fontFamily": _FONT}),
                dcc.Dropdown(id="hist-sensor", clearable=False,
                             style={"backgroundColor": cfg.COLORS["card"], "color": "#000"}),
            ], lg=3),
            dbc.Col([
                html.Label("Time Range", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.75rem", "fontFamily": _FONT}),
                dbc.RadioItems(id="hist-range", options=[
                    {"label": "6h", "value": 6}, {"label": "12h", "value": 12},
                    {"label": "24h", "value": 24}, {"label": "48h", "value": 48},
                ], value=6, inline=True, className="mt-1", input_style={"marginRight": "4px"},
                               label_style={"marginRight": "12px", "color": cfg.COLORS["text"], "fontSize": "0.82rem", "fontFamily": _FONT}),
            ], lg=4),
            dbc.Col([
                html.Label("Forecast", style={"color": cfg.COLORS["text_muted"], "fontSize": "0.75rem", "fontFamily": _FONT}),
                dbc.RadioItems(id="hist-horizon", options=[
                    {"label": "30 min", "value": "30min"}, {"label": "2 hours", "value": "2hr"},
                ], value="30min", inline=True, className="mt-1", input_style={"marginRight": "4px"},
                               label_style={"marginRight": "12px", "color": cfg.COLORS["text"], "fontSize": "0.82rem", "fontFamily": _FONT}),
            ], lg=3),
        ], className="mb-3"),
        html.Div(id="hist-content"),
    ])


@callback(Output("hist-sensor", "options"), Output("hist-sensor", "value"),
          Input("hist-tick", "n_intervals"), State("hist-sensor", "value"))
def populate_sensors(_, current_value):
    prov = get_provider(get_client_id())
    devices = prov.get_all_devices()
    options = [{"label": d, "value": d} for d in devices]
    if current_value and current_value in devices:
        return options, no_update
    return options, devices[0] if devices else None


def _get_anchor_time(prov, device_id):
    """For offline sensors return last_seen time; for online sensors return now."""
    states = prov.get_all_sensor_states()
    state = next((s for s in states if s.get("device_id") == device_id), None)
    if state and state.get("status") == "offline" and state.get("last_seen"):
        try:
            return datetime.fromisoformat(state["last_seen"].replace("Z", "+00:00")), True
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc), False


@callback(Output("hist-content", "children"),
          Input("hist-sensor", "value"), Input("hist-range", "value"), Input("hist-horizon", "value"))
def update_history(device_id, hours, horizon):
    if not device_id:
        return ""
    prov = get_provider(get_client_id())
    anchor, is_offline = _get_anchor_time(prov, device_id)
    readings = prov.get_readings(device_id, (anchor - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:00Z"))
    if not readings:
        return html.P("No data for this time range." + (" Sensor is offline." if is_offline else ""),
                       style={"color": cfg.COLORS["text_muted"], "fontFamily": _FONT})

    timestamps = [r["timestamp"] for r in readings]
    temps = [r["temperature"] for r in readings]
    arr = np.array(temps)
    hi, lo, avg, cur = float(np.max(arr)), float(np.min(arr)), float(np.mean(arr)), temps[-1]

    steps = 30 if horizon == "30min" else 120
    if is_offline:
        fc_series, fc, predicted = [], None, 0
    else:
        fc_series = prov.get_forecast_series(device_id, horizon, steps)
        fc = prov.get_forecast(device_id, horizon)
        predicted = fc.get("predicted_temp", 0) if fc else 0

    in_range = sum(1 for t in temps if cfg.TEMP_LOW <= t <= cfg.TEMP_HIGH)
    compliance_pct = round(in_range / len(temps) * 100, 1) if temps else 0
    out_of_range = len(temps) - in_range
    breach_high = sum(1 for t in temps if t > cfg.TEMP_HIGH)
    breach_low = sum(1 for t in temps if t < cfg.TEMP_LOW)

    if is_offline:
        fc_label, fc_value, fc_color = "Last Reading", f"{cur:.1f}°F", cfg.COLORS["text_muted"]
    else:
        fc_label = "Forecast"
        fc_value = f"{predicted:.1f}°F"
        fc_color = cfg.COLORS["danger"] if predicted > cfg.TEMP_HIGH else cfg.COLORS["primary_light"]

    kpis = dbc.Row([
        dbc.Col(_kpi("Current" if not is_offline else "Last", f"{cur:.1f}°F", cfg.COLORS["primary"]), xs=6, lg=2, className="mb-2"),
        dbc.Col(_kpi("High", f"{hi:.1f}°F", cfg.COLORS["danger"] if hi > cfg.TEMP_HIGH else cfg.COLORS["text"]), xs=6, lg=2, className="mb-2"),
        dbc.Col(_kpi("Low", f"{lo:.1f}°F", cfg.COLORS["primary_light"] if lo < cfg.TEMP_LOW else cfg.COLORS["text"]), xs=6, lg=2, className="mb-2"),
        dbc.Col(_kpi("Average", f"{avg:.1f}°F", cfg.COLORS["primary"]), xs=6, lg=2, className="mb-2"),
        dbc.Col(_kpi(fc_label, fc_value, fc_color), xs=6, lg=2, className="mb-2"),
        dbc.Col(_kpi("In Range", f"{compliance_pct}%",
                     cfg.COLORS["success"] if compliance_pct >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"]), xs=6, lg=2, className="mb-2"),
    ], className="g-2 mb-3")

    chart_card = dbc.Card(dcc.Graph(figure=_main_chart(prov, device_id, timestamps, temps, arr, hi, lo, fc_series, horizon, is_offline),
                                     config={"displayModeBar": False}), style=cfg.CARD_STYLE, className="mb-3")

    bottom = dbc.Row([
        dbc.Col(_compliance_section(prov, compliance_pct, out_of_range, breach_high, breach_low, len(temps)), lg=5, className="mb-3"),
        dbc.Col(_alerts_card(prov, device_id), lg=7, className="mb-3"),
    ], className="g-3")

    return html.Div([kpis, chart_card, bottom])


def _main_chart(prov, device_id, timestamps, temps, arr, hi, lo, fc_series, horizon, is_offline=False):
    fig = go.Figure()
    window = 30
    if len(temps) > window:
        hi_band = [float(np.max(arr[max(0, i - window):i + 1])) for i in range(len(arr))]
        lo_band = [float(np.min(arr[max(0, i - window):i + 1])) for i in range(len(arr))]
        fig.add_trace(go.Scatter(x=timestamps, y=hi_band, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=timestamps, y=lo_band, fill="tonexty", fillcolor="rgba(255,107,0,0.06)",
                                 line=dict(width=0), name="High/Low Band"))
    a_ts = timestamps + [f["timestamp"] for f in fc_series]
    if a_ts:
        fig.add_trace(go.Scatter(x=[a_ts[0], a_ts[-1], a_ts[-1], a_ts[0]], y=[cfg.TEMP_LOW]*2 + [cfg.TEMP_HIGH]*2,
                                 fill="toself", fillcolor=cfg.COLORS["safe_zone"], line=dict(width=0), showlegend=False, hoverinfo="skip"))

    fig.add_trace(go.Scatter(x=timestamps, y=temps, mode="lines", name="Actual", line=dict(color=cfg.COLORS["primary"], width=2.5)))

    states = prov.get_all_sensor_states()
    state = next((s for s in states if s["device_id"] == device_id), None)
    if state and state.get("anomaly"):
        fig.add_trace(go.Scatter(x=[timestamps[-1]], y=[temps[-1]], mode="markers", name="Anomaly",
                                 marker=dict(color=cfg.COLORS["warning"], size=12, symbol="diamond")))

    fig.add_hline(y=hi, line_dash="dash", line_color="rgba(229,57,53,0.35)", line_width=1,
                  annotation_text=f"High: {hi:.1f}°F", annotation_font_color=cfg.COLORS["danger"], annotation_font_size=9, annotation_position="top right")
    fig.add_hline(y=lo, line_dash="dash", line_color="rgba(255,143,63,0.35)", line_width=1,
                  annotation_text=f"Low: {lo:.1f}°F", annotation_font_color=cfg.COLORS["primary_light"], annotation_font_size=9, annotation_position="bottom right")

    if fc_series:
        f_ts = [f["timestamp"] for f in fc_series]
        f_pred = [f["predicted"] for f in fc_series]
        f_upper = [f["ci_upper"] for f in fc_series]
        f_lower = [f["ci_lower"] for f in fc_series]
        if timestamps and temps:
            bridge_ts, bridge_val = timestamps[-1], temps[-1]
            f_ts = [bridge_ts] + f_ts
            f_pred = [bridge_val] + f_pred
            f_upper = [bridge_val] + f_upper
            f_lower = [bridge_val] + f_lower
        fig.add_trace(go.Scatter(x=f_ts, y=f_upper, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=f_ts, y=f_lower, fill="tonexty", fillcolor=cfg.COLORS["primary_dim"], line=dict(width=0), name="Forecast Range"))
        fig.add_trace(go.Scatter(x=f_ts, y=f_pred, mode="lines", name=f"Forecast ({horizon})",
                                 line=dict(color=cfg.COLORS["primary_light"], width=2, dash="dot")))

    if timestamps:
        marker_label = "Last Reading" if is_offline else "Now"
        marker_color = cfg.COLORS["warning"] if is_offline else cfg.COLORS["text_muted"]
        fig.add_shape(type="line", x0=timestamps[-1], x1=timestamps[-1], y0=0, y1=1, yref="paper",
                      line=dict(dash="dash", color=marker_color, width=1))
        fig.add_annotation(x=timestamps[-1], y=1, yref="paper", text=marker_label, showarrow=False,
                           font=dict(color=marker_color, size=9), yshift=8)

    fig.add_hline(y=cfg.TEMP_HIGH, line_dash="dot", line_color=cfg.COLORS["danger"], line_width=1)
    fig.add_hline(y=cfg.TEMP_LOW, line_dash="dot", line_color=cfg.COLORS["primary_light"], line_width=1)

    x_layout = dict(gridcolor=cfg.CHART_GRID_COLOR)
    if is_offline and timestamps:
        x_layout["range"] = [timestamps[0], timestamps[-1]]

    fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, plot_bgcolor=cfg.CHART_PLOT_BG,
                      font=cfg.CHART_FONT, height=360, margin=dict(l=42, r=12, t=18, b=32), hovermode="x unified",
                      hoverlabel=cfg.HOVER_LABEL,
                      xaxis=x_layout, yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, title="°F"),
                      legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, font=dict(size=9)))
    return fig


def _compliance_section(prov, compliance_pct, out_of_range, breach_high, breach_low, total):
    gauge = go.Figure(go.Indicator(
        mode="gauge+number", value=compliance_pct, number={"suffix": "%", "font": {"size": 28, "color": cfg.COLORS["text"], "family": _FONT}},
        gauge={"axis": {"range": [0, 100], "tickwidth": 0, "tickcolor": "rgba(0,0,0,0)"},
               "bar": {"color": cfg.COLORS["success"] if compliance_pct >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"], "thickness": 0.6},
               "bgcolor": cfg.COLORS["card_border"],
               "steps": [{"range": [0, cfg.COMPLIANCE_TARGET], "color": cfg.COLORS["danger_dim"]},
                          {"range": [cfg.COMPLIANCE_TARGET, 100], "color": cfg.COLORS["success_dim"]}],
               "threshold": {"line": {"color": cfg.COLORS["primary"], "width": 2}, "thickness": 0.8, "value": cfg.COMPLIANCE_TARGET}},
    ))
    gauge.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, font=cfg.CHART_FONT,
                        height=160, margin=dict(l=20, r=20, t=30, b=10))

    comp_history = prov.get_compliance_history(7)
    trend_fig = go.Figure()
    if comp_history:
        dates = [c["date"] for c in comp_history]
        pcts = [c["compliance_pct"] for c in comp_history]
        trend_fig.add_trace(go.Scatter(x=dates, y=pcts, mode="lines+markers",
                                       line=dict(color=cfg.COLORS["primary"], width=2.5, shape="spline"),
                                       marker=dict(size=6, color=[cfg.COLORS["success"] if p >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"] for p in pcts]),
                                       fill="tozeroy", fillcolor=cfg.COLORS["primary_dim"]))
        trend_fig.add_hline(y=cfg.COMPLIANCE_TARGET, line_dash="dot", line_color=cfg.COLORS["primary"], line_width=1,
                            annotation_text=f"Target {cfg.COMPLIANCE_TARGET}%", annotation_font_size=9, annotation_font_color=cfg.COLORS["primary"])
    trend_fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, plot_bgcolor=cfg.CHART_PLOT_BG,
                            font=cfg.CHART_FONT, height=150, margin=dict(l=35, r=8, t=8, b=25), showlegend=False,
                            hoverlabel=cfg.HOVER_LABEL,
                            xaxis=dict(gridcolor="rgba(0,0,0,0)"), yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, range=[85, 101]))

    breach = html.Div([
        html.Div([_stat("Total Readings", str(total), cfg.COLORS["text"]),
                  _stat("In Range", str(total - out_of_range), cfg.COLORS["success"]),
                  _stat("Out of Range", str(out_of_range), cfg.COLORS["warning"] if out_of_range else cfg.COLORS["success"]),
                  _stat("Too Hot", str(breach_high), cfg.COLORS["danger"] if breach_high else cfg.COLORS["success"]),
                  _stat("Too Cold", str(breach_low), cfg.COLORS["primary_light"] if breach_low else cfg.COLORS["success"])],
                 style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "justifyContent": "center"})
    ], style={"padding": "6px 0"})

    return dbc.Card([
        dbc.CardHeader("Compliance", style={"backgroundColor": cfg.COLORS["card"], "border": "none",
                                             "fontWeight": "600", "fontSize": "0.82rem", "color": cfg.COLORS["text_muted"], "fontFamily": _FONT}),
        dbc.CardBody([
            dcc.Graph(figure=gauge, config={"displayModeBar": False}),
            breach,
            html.Hr(style={"borderColor": cfg.COLORS["card_border"], "margin": "6px 0"}),
            html.Div("7-Day Trend", style={"fontSize": "0.72rem", "color": cfg.COLORS["text_muted"], "fontWeight": "600", "marginBottom": "4px", "fontFamily": _FONT}),
            dcc.Graph(figure=trend_fig, config={"displayModeBar": False}),
        ]),
    ], style=cfg.CARD_STYLE)


def _alerts_card(prov, device_id):
    all_alerts = prov.get_all_alerts()
    device_alerts = sorted([a for a in all_alerts if a.get("device_id") == device_id],
                           key=lambda a: a.get("triggered_at", ""), reverse=True)
    table_data = [{"Priority": cfg.SEVERITY_LABELS.get(a.get("severity", ""), a.get("severity", "")),
                   "What": a.get("message", "")[:42], "When": _fmt_time(a.get("triggered_at", "")),
                   "Status": "Active" if a.get("status") == "ACTIVE" else "Resolved"} for a in device_alerts[:20]]

    tbl = dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in ["Priority", "What", "When", "Status"]],
        data=table_data, sort_action="native", page_size=8,
        style_header={"backgroundColor": cfg.COLORS["card"], "color": cfg.COLORS["text_muted"],
                       "fontWeight": "600", "border": f"1px solid {cfg.COLORS['card_border']}",
                       "fontSize": "0.72rem", "textTransform": "uppercase", "fontFamily": _FONT},
        style_cell={"backgroundColor": cfg.COLORS["bg"], "color": cfg.COLORS["text"],
                     "border": f"1px solid {cfg.COLORS['card_border']}", "fontSize": "0.82rem",
                     "padding": "7px 10px", "textAlign": "left", "fontFamily": _FONT},
        style_data_conditional=[
            {"if": {"filter_query": "{Priority} = Urgent"}, "color": cfg.COLORS["critical"], "fontWeight": "600"},
            {"if": {"filter_query": "{Status} = Active"}, "backgroundColor": cfg.COLORS["danger_dim"]},
        ],
    )
    return dbc.Card([
        dbc.CardHeader("Alert History", style={"backgroundColor": cfg.COLORS["card"], "border": "none",
                                                "fontWeight": "600", "fontSize": "0.82rem", "color": cfg.COLORS["text_muted"], "fontFamily": _FONT}),
        dbc.CardBody(tbl),
    ], style=cfg.CARD_STYLE)


def _kpi(label, value, color):
    return html.Div([
        html.Div(label, style={"fontSize": "0.6rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase", "letterSpacing": "1px", "fontFamily": _FONT}),
        html.Div(value, style={"fontSize": "0.95rem", "fontWeight": "700", "color": color, "fontFamily": _FONT}),
    ], style={**cfg.CARD_STYLE, "padding": "7px 10px", "textAlign": "center"})


def _stat(label, value, color):
    return html.Div([
        html.Div(value, style={"fontWeight": "700", "fontSize": "0.9rem", "color": color, "fontFamily": _FONT}),
        html.Div(label, style={"fontSize": "0.55rem", "color": cfg.COLORS["text_muted"], "textTransform": "uppercase", "fontFamily": _FONT}),
    ], style={"textAlign": "center", "minWidth": "55px"})


def _fmt_time(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d %Y, %H:%M")
    except Exception:
        return ""
