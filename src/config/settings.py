"""Central configuration for the temp-sensor analytics platform.

All settings are loaded from environment variables with sensible defaults.
In production (Lambda), SAM template injects env vars.
Locally, defaults are used or tests override via os.environ.
"""

import os

# --- Deployment Identity ---
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
PROJECT_PREFIX = os.environ.get("PROJECT_PREFIX", "temp-sensor")
DEPLOYMENT_ID = os.environ.get("DEPLOYMENT_ID", "0000000000")

# --- AWS Resource Names (injected by SAM or set manually) ---
PLATFORM_CONFIG_TABLE = os.environ.get("PLATFORM_CONFIG_TABLE", "")
SENSOR_DATA_TABLE = os.environ.get("SENSOR_DATA_TABLE", "")
ALERTS_TABLE = os.environ.get("ALERTS_TABLE", "")
DATA_STREAM_NAME = os.environ.get("DATA_STREAM_NAME", "")
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")
CRITICAL_ALERT_TOPIC_ARN = os.environ.get("CRITICAL_ALERT_TOPIC_ARN", "")
STANDARD_ALERT_TOPIC_ARN = os.environ.get("STANDARD_ALERT_TOPIC_ARN", "")

# --- Temperature Thresholds (°F) ---
TEMP_CRITICAL_HIGH = float(os.environ.get("TEMP_CRITICAL_HIGH", "95.0"))
TEMP_CRITICAL_LOW = float(os.environ.get("TEMP_CRITICAL_LOW", "50.0"))
TEMP_HIGH = float(os.environ.get("TEMP_HIGH", "85.0"))
TEMP_LOW = float(os.environ.get("TEMP_LOW", "65.0"))
TEMP_VALID_MIN = -40.0
TEMP_VALID_MAX = 150.0

# --- Alert Configuration ---
RAPID_CHANGE_THRESHOLD_F = float(os.environ.get("RAPID_CHANGE_THRESHOLD_F", "4.0"))
RAPID_CHANGE_WINDOW_MIN = int(os.environ.get("RAPID_CHANGE_WINDOW_MIN", "10"))
SUSTAINED_DURATION_MIN = int(os.environ.get("SUSTAINED_DURATION_MIN", "10"))
SENSOR_OFFLINE_SEC = int(os.environ.get("SENSOR_OFFLINE_SEC", "60"))
BATTERY_LOW_PCT = int(os.environ.get("BATTERY_LOW_PCT", "20"))
ANOMALY_Z_THRESHOLD = float(os.environ.get("ANOMALY_Z_THRESHOLD", "3.0"))
ANOMALY_MIN_CONSECUTIVE = int(os.environ.get("ANOMALY_MIN_CONSECUTIVE", "3"))

# --- Alert Escalation ---
ESCALATE_SUPERVISOR_SEC = int(os.environ.get("ESCALATE_SUPERVISOR_SEC", "300"))
ESCALATE_MANAGER_SEC = int(os.environ.get("ESCALATE_MANAGER_SEC", "900"))
ALERT_COOLDOWN_MIN = int(os.environ.get("ALERT_COOLDOWN_MIN", "5"))
HYSTERESIS_F = float(os.environ.get("HYSTERESIS_F", "2.0"))
ZONE_AGGREGATION_WINDOW_MIN = 5

# --- Analytics Windows ---
ROLLING_WINDOW_10M_MIN = 10
ROLLING_WINDOW_1H_MIN = 60
READING_INTERVAL_SEC = 5
READINGS_RETENTION_HOURS = int(os.environ.get("READINGS_RETENTION_HOURS", "48"))

# --- Forecasting ---
FORECAST_HORIZON_SHORT_MIN = 30
FORECAST_HORIZON_LONG_MIN = 120
FORECAST_SMOOTHING_ALPHA = float(os.environ.get("FORECAST_SMOOTHING_ALPHA", "0.3"))
FORECAST_SMOOTHING_BETA = float(os.environ.get("FORECAST_SMOOTHING_BETA", "0.05"))

# --- Compliance ---
COMPLIANCE_TEMP_LOW = float(os.environ.get("COMPLIANCE_TEMP_LOW", "65.0"))
COMPLIANCE_TEMP_HIGH = float(os.environ.get("COMPLIANCE_TEMP_HIGH", "85.0"))
SHIFT_TIMES = ["06:00", "14:00", "22:00"]

# --- CSV Column Mapping (raw gateway data → standard schema) ---
CSV_COLUMN_MAP = {
    "mac": "device_id",
    "body_temperature": "temperature",
    "rssi": "rssi",
    "power": "power",
    "timestamp": "timestamp",
    "gateway_mac": "gateway_id",
}

# --- Feature Flags (true/false — toggle features per deployment) ---
# Master switch: disables all alerts platform-wide when false
FEATURE_ALERTS_ENABLED = os.environ.get("FEATURE_ALERTS_ENABLED", "true").lower() == "true"

# Per-alert-type flags (only evaluated when FEATURE_ALERTS_ENABLED is true)
FEATURE_ALERT_EXTREME_TEMP = os.environ.get("FEATURE_ALERT_EXTREME_TEMP", "true").lower() == "true"
FEATURE_ALERT_SUSTAINED_HIGH = os.environ.get("FEATURE_ALERT_SUSTAINED_HIGH", "true").lower() == "true"
FEATURE_ALERT_RAPID_CHANGE = os.environ.get("FEATURE_ALERT_RAPID_CHANGE", "true").lower() == "true"
FEATURE_ALERT_SENSOR_OFFLINE = os.environ.get("FEATURE_ALERT_SENSOR_OFFLINE", "true").lower() == "true"
FEATURE_ALERT_ANOMALY = os.environ.get("FEATURE_ALERT_ANOMALY", "true").lower() == "true"
FEATURE_ALERT_FORECAST_BREACH = os.environ.get("FEATURE_ALERT_FORECAST_BREACH", "true").lower() == "true"

# Pipeline stage flags
FEATURE_ANALYTICS_ENABLED = os.environ.get("FEATURE_ANALYTICS_ENABLED", "true").lower() == "true"
FEATURE_FORECASTING_ENABLED = os.environ.get("FEATURE_FORECASTING_ENABLED", "true").lower() == "true"
FEATURE_COMPLIANCE_ENABLED = os.environ.get("FEATURE_COMPLIANCE_ENABLED", "true").lower() == "true"
FEATURE_ARCHIVAL_ENABLED = os.environ.get("FEATURE_ARCHIVAL_ENABLED", "true").lower() == "true"
FEATURE_NOTIFICATIONS_ENABLED = os.environ.get("FEATURE_NOTIFICATIONS_ENABLED", "true").lower() == "true"

# Auto-provision unknown devices into device registry (off by default for safety)
FEATURE_AUTO_PROVISION = os.environ.get("FEATURE_AUTO_PROVISION", "false").lower() == "true"

# --- Logging ---
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
