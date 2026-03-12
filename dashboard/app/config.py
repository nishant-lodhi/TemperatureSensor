"""Dashboard configuration — env vars, theme, thresholds, chart defaults."""

import base64
import os

AWS_MODE = os.environ.get("AWS_MODE", "false").lower() == "true"
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

DATA_SOURCE = os.environ.get("DATA_SOURCE", "mysql")
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "Demo_aurora")

PARQUET_BUCKET = os.environ.get("PARQUET_BUCKET", "")
PARQUET_PREFIX = os.environ.get("PARQUET_PREFIX", "sensor-data/")

ALERTS_TABLE = os.environ.get("ALERTS_TABLE", "")
NOTE_LAMBDA_ARN = os.environ.get("NOTE_LAMBDA_ARN", "")

FACILITY_NAME = os.environ.get("FACILITY_NAME", "")

REFRESH_MONITOR_MS = 15_000
REFRESH_HISTORY_MS = 30_000

TEMP_HIGH = 85.0
TEMP_LOW = 65.0
TEMP_CRITICAL_HIGH = 95.0
TEMP_CRITICAL_LOW = 50.0
COMPLIANCE_TARGET = 95.0

BATTERY_LOW = 20
BATTERY_WARN = 40
SIGNAL_WEAK = -80

ALERT_COOLDOWN_SEC = 300
ALERT_ESCALATE_AFTER_SEC = 900
ALERT_OFFLINE_THRESHOLD_SEC = 300
ALERT_DEGRADED_THRESHOLD_SEC = 120

# ── Light theme inspired by correctional facility admin panel ─────────────
COLORS = {
    "bg": "#f0f2f5",
    "bg_subtle": "#e8ecf0",
    "card": "#ffffff",
    "card_solid": "#ffffff",
    "card_hover": "#f8fafb",
    "card_border": "#e2e8f0",
    "text": "#1e293b",
    "text_muted": "#64748b",
    "primary": "#0d9488",
    "primary_light": "#14b8a6",
    "primary_dim": "rgba(13,148,136,0.07)",
    "primary_glow": "rgba(13,148,136,0.14)",
    "accent": "#f97316",
    "accent_dim": "rgba(249,115,22,0.07)",
    "success": "#16a34a",
    "success_dim": "rgba(22,163,74,0.06)",
    "warning": "#d97706",
    "warning_dim": "rgba(217,119,6,0.06)",
    "danger": "#dc2626",
    "danger_dim": "rgba(220,38,38,0.06)",
    "critical": "#b91c1c",
    "safe_zone": "rgba(13,148,136,0.04)",
    "selected": "rgba(13,148,136,0.10)",
    "header_bg": "#1e3a4a",
}

CARD_STYLE = {
    "backgroundColor": COLORS["card"],
    "border": f"1px solid {COLORS['card_border']}",
    "borderRadius": "10px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03)",
}

SEVERITY_LABELS = {
    "CRITICAL": "Urgent", "HIGH": "Important", "MEDIUM": "Moderate",
    "WARNING": "Notice", "LOW": "Info", "FORECAST": "Forecast",
}
SEVERITY_COLORS = {
    "CRITICAL": COLORS["critical"], "HIGH": COLORS["danger"],
    "MEDIUM": COLORS["warning"], "WARNING": "#d97706",
    "LOW": COLORS["primary_light"], "FORECAST": COLORS["accent"],
}

CHART_TEMPLATE = "simple_white"
CHART_PAPER_BG = "rgba(0,0,0,0)"
CHART_PLOT_BG = "rgba(0,0,0,0)"
CHART_GRID_COLOR = "rgba(0,0,0,0.04)"
CHART_FONT = dict(
    family="'Inter', 'DM Sans', system-ui, sans-serif",
    color=COLORS["text"],
)
HOVER_LABEL = dict(
    bgcolor="#ffffff", bordercolor=COLORS["card_border"],
    font=dict(family="'Inter', system-ui, sans-serif",
              size=13, color=COLORS["text"]),
)


def _wifi_svg(arcs=3, color="#16a34a"):
    dim = "rgba(0,0,0,0.08)"
    c = [dim, dim, dim]
    for i in range(arcs):
        c[i] = color
    paths = (
        f'<path d="M8 13a1 1 0 1 0 0 2 1 1 0 0 0 0-2z" fill="{c[0]}"/>',
        f'<path d="M4.93 10.07a5 5 0 0 1 6.14 0" '
        f'stroke="{c[1]}" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
        f'<path d="M2.1 7.22a9 9 0 0 1 11.8 0" '
        f'stroke="{c[2]}" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        f'viewBox="0 0 16 16">{"".join(paths)}</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


SIGNAL_ICONS = {
    "Strong": _wifi_svg(3, COLORS["success"]),
    "Good": _wifi_svg(2, COLORS["success"]),
    "Weak": _wifi_svg(1, COLORS["warning"]),
    "No Signal": _wifi_svg(0, COLORS["danger"]),
}
