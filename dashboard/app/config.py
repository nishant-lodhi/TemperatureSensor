"""Dashboard configuration — theme, refresh intervals, thresholds."""

import base64
import os

AWS_MODE = os.environ.get("AWS_MODE", "false").lower() == "true"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

PLATFORM_CONFIG_TABLE = os.environ.get("PLATFORM_CONFIG_TABLE", "")
SENSOR_DATA_TABLE = os.environ.get("SENSOR_DATA_TABLE", "")
ALERTS_TABLE = os.environ.get("ALERTS_TABLE", "")
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

FACILITY_NAME = os.environ.get("FACILITY_NAME", "")

REFRESH_MONITOR_MS = 10_000
REFRESH_HISTORY_MS = 30_000

TEMP_HIGH = 85.0
TEMP_LOW = 65.0
TEMP_CRITICAL_HIGH = 95.0
TEMP_CRITICAL_LOW = 50.0
COMPLIANCE_TARGET = 95.0

BATTERY_LOW = 20
BATTERY_WARN = 40
SIGNAL_WEAK = -80

COLORS = {
    "bg": "#0D0D0D",
    "bg_subtle": "#111111",
    "card": "#181818",
    "card_hover": "#1F1F1F",
    "card_border": "#262626",
    "text": "#F0EBE3",
    "text_muted": "#807A72",
    "primary": "#FF6B00",
    "primary_light": "#FF8F3F",
    "primary_dim": "rgba(255,107,0,0.10)",
    "primary_glow": "rgba(255,107,0,0.22)",
    "success": "#43A047",
    "success_dim": "rgba(67,160,71,0.10)",
    "warning": "#FB8C00",
    "warning_dim": "rgba(251,140,0,0.10)",
    "danger": "#E53935",
    "danger_dim": "rgba(229,57,53,0.10)",
    "critical": "#C62828",
    "safe_zone": "rgba(255,107,0,0.05)",
    "selected": "rgba(255,107,0,0.18)",
}

CARD_STYLE = {
    "backgroundColor": COLORS["card"],
    "border": f"1px solid {COLORS['card_border']}",
    "borderRadius": "14px",
    "boxShadow": "0 4px 20px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.03)",
}

STATUS_COLORS = {
    "normal": COLORS["success"],
    "warning": COLORS["warning"],
    "alert": COLORS["danger"],
    "critical": COLORS["critical"],
    "offline": COLORS["text_muted"],
}

SEVERITY_LABELS = {
    "CRITICAL": "Urgent",
    "HIGH": "Important",
    "MEDIUM": "Moderate",
    "WARNING": "Notice",
    "LOW": "Info",
}

SEVERITY_COLORS = {
    "CRITICAL": COLORS["critical"],
    "HIGH": COLORS["danger"],
    "MEDIUM": COLORS["warning"],
    "WARNING": "#FFB74D",
    "LOW": COLORS["primary_light"],
}

CHART_TEMPLATE = "plotly_dark"
CHART_PAPER_BG = "rgba(0,0,0,0)"
CHART_PLOT_BG = "rgba(0,0,0,0)"
CHART_GRID_COLOR = "rgba(255,255,255,0.04)"
CHART_FONT = dict(family="'DM Sans', system-ui, sans-serif", color=COLORS["text"])

def _wifi_svg(arcs=3, color="#43A047"):
    """Generate a small WiFi icon SVG as a data URI. arcs: 0-3 lit arcs."""
    dim = "rgba(255,255,255,0.12)"
    c = [dim, dim, dim]
    for i in range(arcs):
        c[i] = color
    paths = (
        f'<path d="M8 13a1 1 0 1 0 0 2 1 1 0 0 0 0-2z" fill="{c[0]}"/>',
        f'<path d="M4.93 10.07a5 5 0 0 1 6.14 0" stroke="{c[1]}" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
        f'<path d="M2.1 7.22a9 9 0 0 1 11.8 0" stroke="{c[2]}" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">{"".join(paths)}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


SIGNAL_ICONS = {
    "Strong": _wifi_svg(3, COLORS["success"]),
    "Good": _wifi_svg(2, COLORS["success"]),
    "Weak": _wifi_svg(1, COLORS["warning"]),
    "No Signal": _wifi_svg(0, COLORS["danger"]),
}

HOVER_LABEL = dict(
    bgcolor="rgba(24,24,24,0.92)",
    bordercolor=COLORS["card_border"],
    font=dict(family="'DM Sans', system-ui, sans-serif", size=13, color=COLORS["text"]),
)
