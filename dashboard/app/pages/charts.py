"""Plotly figure builders — all chart construction in one place.

Every function takes data + config, returns a go.Figure. No DB calls.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from app import config as cfg

_F = "'Inter', 'DM Sans', system-ui, sans-serif"

_SEVERITY_MARKER = {
    "CRITICAL": {"color": cfg.COLORS["critical"], "symbol": "diamond", "size": 12},
    "HIGH": {"color": cfg.COLORS["danger"], "symbol": "diamond", "size": 10},
    "MEDIUM": {"color": cfg.COLORS["warning"], "symbol": "circle", "size": 9},
    "WARNING": {"color": "#fbbf24", "symbol": "circle", "size": 8},
    "LOW": {"color": cfg.COLORS["primary_light"], "symbol": "circle", "size": 7},
    "FORECAST": {"color": cfg.COLORS["accent"], "symbol": "diamond-open", "size": 10},
}


def _downsample(readings: list[dict], target: int = 2000) -> list[dict]:
    """Min-max-mean downsampling that preserves peaks and valleys."""
    n = len(readings)
    if n <= target:
        return readings
    bucket_size = max(1, n // (target // 3))
    result = []
    for i in range(0, n, bucket_size):
        bucket = readings[i:i + bucket_size]
        idx_min = min(range(len(bucket)), key=lambda j: bucket[j]["temperature"])
        idx_max = max(range(len(bucket)), key=lambda j: bucket[j]["temperature"])
        ordered = sorted([(idx_min, bucket[idx_min]), (idx_max, bucket[idx_max])],
                         key=lambda x: x[0])
        for _, r in ordered:
            result.append(r)
        mid = bucket[len(bucket) // 2]
        if mid not in [ordered[0][1], ordered[1][1]] if len(ordered) > 1 else True:
            result.append(mid)
    result.sort(key=lambda r: r["timestamp"])
    seen = set()
    deduped = []
    for r in result:
        k = r["timestamp"]
        if k not in seen:
            seen.add(k)
            deduped.append(r)
    return deduped


def unified_chart(
    readings: list[dict],
    fc_series: list[dict],
    alerts: list[dict],
    range_mode: str = "live",
    is_offline: bool = False,
    height: int = 380,
) -> go.Figure:
    """Single chart: actual line + forecast torch + safe zone + alert markers."""
    if len(readings) > 2000:
        readings = _downsample(readings)

    h_ts = [r["timestamp"] for r in readings]
    h_t = [r["temperature"] for r in readings]
    fig = go.Figure()

    f_ts = [f["timestamp"] for f in fc_series]
    all_ts = h_ts + f_ts
    if all_ts:
        fig.add_trace(go.Scatter(
            x=[all_ts[0], all_ts[-1], all_ts[-1], all_ts[0]],
            y=[cfg.TEMP_LOW, cfg.TEMP_LOW, cfg.TEMP_HIGH, cfg.TEMP_HIGH],
            fill="toself", fillcolor=cfg.COLORS["safe_zone"],
            line=dict(width=0), showlegend=False, hoverinfo="skip",
            name="Safe Zone",
        ))

    line_color = cfg.COLORS["text_muted"] if is_offline else cfg.COLORS["primary"]
    line_style = "dot" if is_offline else "solid"
    fig.add_trace(go.Scatter(
        x=h_ts, y=h_t, mode="lines",
        name="Last Readings" if is_offline else "Actual",
        line=dict(color=line_color, width=2.5, dash=line_style),
    ))

    if fc_series and not is_offline:
        f_pred = [f["predicted"] for f in fc_series]
        f_up = [f["ci_upper"] for f in fc_series]
        f_lo = [f["ci_lower"] for f in fc_series]
        if h_ts and h_t:
            f_ts = [h_ts[-1]] + f_ts
            f_pred = [h_t[-1]] + f_pred
            f_up = [h_t[-1]] + f_up
            f_lo = [h_t[-1]] + f_lo

        fig.add_trace(go.Scatter(
            x=f_ts, y=f_up, mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=f_ts, y=f_lo, fill="tonexty",
            fillcolor="rgba(249,115,22,0.08)", line=dict(width=0),
            name="Forecast Range",
        ))

        # Torch glow — wide translucent line behind forecast
        fig.add_trace(go.Scatter(
            x=f_ts, y=f_pred, mode="lines",
            line=dict(color="rgba(249,115,22,0.12)", width=14),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=f_ts, y=f_pred, mode="lines",
            line=dict(color="rgba(249,115,22,0.25)", width=6),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=f_ts, y=f_pred, mode="lines", name="Forecast",
            line=dict(color=cfg.COLORS["accent"], width=2.5, dash="dot"),
        ))

    if h_t:
        arr = np.array(h_t, dtype=float)
        hi, lo = float(np.max(arr)), float(np.min(arr))
        _add_threshold_lines(fig, hi, lo)

    _add_safe_thresholds(fig)

    if alerts:
        _add_alert_markers(fig, alerts, h_ts, h_t)

    if h_ts:
        if is_offline:
            _add_marker_line(fig, h_ts[-1], "Last Reading", cfg.COLORS["warning"])
        elif range_mode == "live" and fc_series:
            _add_marker_line(fig, h_ts[-1], "Now", cfg.COLORS["text_muted"])

    _apply_layout(fig, height, range_mode, is_offline)
    return fig


def _add_threshold_lines(fig: go.Figure, hi: float, lo: float):
    fig.add_hline(
        y=hi, line_dash="dash", line_color="rgba(239,68,68,0.3)", line_width=1,
        annotation_text=f"High: {hi:.1f}°F",
        annotation_font_color=cfg.COLORS["danger"], annotation_font_size=9,
        annotation_position="top right",
    )
    fig.add_hline(
        y=lo, line_dash="dash", line_color="rgba(6,182,212,0.3)", line_width=1,
        annotation_text=f"Low: {lo:.1f}°F",
        annotation_font_color=cfg.COLORS["primary_light"], annotation_font_size=9,
        annotation_position="bottom right",
    )


def _add_safe_thresholds(fig: go.Figure):
    fig.add_hline(
        y=cfg.TEMP_HIGH, line_dash="dot", line_color=cfg.COLORS["danger"], line_width=1,
        annotation_text="Too Hot",
        annotation_font_color=cfg.COLORS["danger"], annotation_font_size=9,
        annotation_position="top left",
    )
    fig.add_hline(
        y=cfg.TEMP_LOW, line_dash="dot", line_color=cfg.COLORS["primary_light"], line_width=1,
        annotation_text="Too Cold",
        annotation_font_color=cfg.COLORS["primary_light"], annotation_font_size=9,
        annotation_position="bottom left",
    )


def _add_alert_markers(fig: go.Figure, alerts: list[dict], h_ts: list, h_t: list):
    a_ts, a_temp, a_text, a_color, a_symbol, a_size = [], [], [], [], [], []
    for a in alerts:
        ts = a.get("triggered_at", "")
        if not ts:
            continue
        temp = None
        try:
            temp = float(a.get("temperature", 0))
        except (ValueError, TypeError):
            pass
        if temp is None or temp == 0:
            if h_t:
                closest_idx = _find_closest_ts(h_ts, ts)
                temp = h_t[closest_idx] if closest_idx is not None else h_t[-1]
            else:
                temp = (cfg.TEMP_HIGH + cfg.TEMP_LOW) / 2
        sev = a.get("severity", "MEDIUM")
        marker = _SEVERITY_MARKER.get(sev, _SEVERITY_MARKER["MEDIUM"])
        sev_label = cfg.SEVERITY_LABELS.get(sev, sev)
        state = a.get("state", "ACTIVE")
        msg = a.get("message", "")[:50]
        hover = f"<b>{sev_label}</b> — {a.get('alert_type', '')}<br>{msg}<br>Status: {state}"

        a_ts.append(ts)
        a_temp.append(temp)
        a_text.append(hover)
        a_color.append(marker["color"])
        a_symbol.append(marker["symbol"])
        a_size.append(marker["size"])

    if a_ts:
        fig.add_trace(go.Scatter(
            x=a_ts, y=a_temp, mode="markers",
            marker=dict(color=a_color, symbol=a_symbol, size=a_size,
                        line=dict(width=1.5, color="rgba(255,255,255,0.3)")),
            name="Alerts", hovertext=a_text, hoverinfo="text",
            customdata=[{"device_id": a.get("device_id"), "alert_type": a.get("alert_type")} for a in alerts if a.get("triggered_at")],
        ))


def _find_closest_ts(h_ts: list[str], target_ts: str):
    if not h_ts:
        return None
    best_idx = 0
    for i, ts in enumerate(h_ts):
        if ts <= target_ts:
            best_idx = i
        else:
            break
    return best_idx


def _add_marker_line(fig: go.Figure, x: str, label: str, color: str):
    fig.add_shape(
        type="line", x0=x, x1=x, y0=0, y1=1, yref="paper",
        line=dict(dash="dash", color=color, width=1),
    )
    fig.add_annotation(
        x=x, y=1, yref="paper", text=label, showarrow=False,
        font=dict(color=color, size=9), yshift=8,
    )


def _apply_layout(fig: go.Figure, height: int, range_mode: str, is_offline: bool):
    title = None
    if is_offline:
        title = dict(text="Offline — Last Known Data", font=dict(size=10, color=cfg.COLORS["text_muted"]), x=0.5)

    fig.update_layout(
        template=cfg.CHART_TEMPLATE,
        paper_bgcolor=cfg.CHART_PAPER_BG,
        plot_bgcolor=cfg.CHART_PLOT_BG,
        font=cfg.CHART_FONT,
        height=height,
        margin=dict(l=40, r=50, t=25, b=28),
        hovermode="x unified",
        hoverlabel=cfg.HOVER_LABEL,
        xaxis=dict(gridcolor=cfg.CHART_GRID_COLOR),
        yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, title="°F"),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=9)),
        title=title,
    )


def compliance_gauge(pct: float, label: str = "Live Compliance") -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=pct,
        number={"suffix": "%", "font": {"size": 26, "color": cfg.COLORS["text"], "family": _F}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 0, "tickcolor": "rgba(0,0,0,0)"},
            "bar": {"color": cfg.COLORS["success"] if pct >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"], "thickness": 0.6},
            "bgcolor": "rgba(51,65,85,0.3)",
            "steps": [{"range": [0, cfg.COMPLIANCE_TARGET], "color": cfg.COLORS["danger_dim"]},
                       {"range": [cfg.COMPLIANCE_TARGET, 100], "color": cfg.COLORS["success_dim"]}],
            "threshold": {"line": {"color": cfg.COLORS["primary"], "width": 2}, "thickness": 0.8, "value": cfg.COMPLIANCE_TARGET},
        }))
    fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, font=cfg.CHART_FONT,
                      height=150, margin=dict(l=20, r=20, t=25, b=8))
    return fig


def compliance_trend(history: list[dict]) -> go.Figure:
    fig = go.Figure()
    if history:
        dates = [c["date"] for c in history]
        pcts = [c["compliance_pct"] for c in history]
        fig.add_trace(go.Scatter(
            x=dates, y=pcts, mode="lines+markers",
            line=dict(color=cfg.COLORS["primary"], width=2.5, shape="spline"),
            marker=dict(size=6, color=[cfg.COLORS["success"] if p >= cfg.COMPLIANCE_TARGET else cfg.COLORS["warning"] for p in pcts]),
            fill="tozeroy", fillcolor=cfg.COLORS["primary_dim"]))
        fig.add_hline(y=cfg.COMPLIANCE_TARGET, line_dash="dot", line_color=cfg.COLORS["primary"], line_width=1,
                      annotation_text=f"Target {cfg.COMPLIANCE_TARGET}%", annotation_font_size=9,
                      annotation_font_color=cfg.COLORS["primary"])
    fig.update_layout(template=cfg.CHART_TEMPLATE, paper_bgcolor=cfg.CHART_PAPER_BG, plot_bgcolor=cfg.CHART_PLOT_BG,
                      font=cfg.CHART_FONT, height=140, margin=dict(l=35, r=8, t=8, b=25), showlegend=False,
                      hoverlabel=cfg.HOVER_LABEL,
                      xaxis=dict(gridcolor="rgba(0,0,0,0)"), yaxis=dict(gridcolor=cfg.CHART_GRID_COLOR, range=[85, 101]))
    return fig
