"""Multi-tenant configuration management.

Reads device-to-tenant mappings and tenant-specific thresholds from DynamoDB.
For testing/simulation, use moto to mock DynamoDB with test data.
"""

import logging

import boto3
from boto3.dynamodb.conditions import Key

from config import settings

logger = logging.getLogger(__name__)

_table_cache = {}


def _get_table(table_name: str):
    if table_name not in _table_cache:
        dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
        _table_cache[table_name] = dynamodb.Table(table_name)
    return _table_cache[table_name]


def get_device_info(device_id: str) -> dict | None:
    """Look up device → client/facility/zone mapping."""
    table = _get_table(settings.PLATFORM_CONFIG_TABLE)
    resp = table.get_item(Key={"pk": f"DEVICE#{device_id}", "sk": "META"})
    item = resp.get("Item")
    if not item:
        logger.warning("Unknown device: %s", device_id)
        return None
    return {
        "device_id": device_id,
        "client_id": item["client_id"],
        "facility_id": item["facility_id"],
        "zone_id": item["zone_id"],
        "sensor_type": item.get("sensor_type", "temp_sensor"),
        "status": item.get("status", "active"),
    }


def get_tenant_thresholds(client_id: str) -> dict:
    """Get client-specific alert thresholds. Falls back to global defaults."""
    table = _get_table(settings.PLATFORM_CONFIG_TABLE)
    resp = table.get_item(Key={"pk": f"TENANT#{client_id}", "sk": "CONFIG"})
    item = resp.get("Item")
    defaults = default_thresholds()
    if not item:
        return defaults
    return {k: type(defaults[k])(item.get(k, defaults[k])) for k in defaults}


def default_thresholds() -> dict:
    """Global default thresholds from settings module."""
    return {
        "temp_critical_high": settings.TEMP_CRITICAL_HIGH,
        "temp_critical_low": settings.TEMP_CRITICAL_LOW,
        "temp_high": settings.TEMP_HIGH,
        "temp_low": settings.TEMP_LOW,
        "rapid_change_threshold_f": settings.RAPID_CHANGE_THRESHOLD_F,
        "rapid_change_window_min": settings.RAPID_CHANGE_WINDOW_MIN,
        "sustained_duration_min": settings.SUSTAINED_DURATION_MIN,
        "sensor_offline_sec": settings.SENSOR_OFFLINE_SEC,
        "battery_low_pct": settings.BATTERY_LOW_PCT,
        "anomaly_z_threshold": settings.ANOMALY_Z_THRESHOLD,
    }


def get_zone_devices(zone_id: str) -> list[str]:
    """Get all device_ids assigned to a zone (via GSI)."""
    table = _get_table(settings.PLATFORM_CONFIG_TABLE)
    resp = table.query(
        IndexName="zone-index",
        KeyConditionExpression=Key("zone_id").eq(zone_id),
    )
    return [item["pk"].split("#", 1)[1] for item in resp.get("Items", [])]


def default_features() -> dict:
    """Global default feature flags from settings module."""
    return {
        "alerts_enabled": settings.FEATURE_ALERTS_ENABLED,
        "alert_extreme_temp": settings.FEATURE_ALERT_EXTREME_TEMP,
        "alert_sustained_high": settings.FEATURE_ALERT_SUSTAINED_HIGH,
        "alert_rapid_change": settings.FEATURE_ALERT_RAPID_CHANGE,
        "alert_sensor_offline": settings.FEATURE_ALERT_SENSOR_OFFLINE,
        "alert_anomaly": settings.FEATURE_ALERT_ANOMALY,
        "alert_forecast_breach": settings.FEATURE_ALERT_FORECAST_BREACH,
        "analytics_enabled": settings.FEATURE_ANALYTICS_ENABLED,
        "forecasting_enabled": settings.FEATURE_FORECASTING_ENABLED,
        "compliance_enabled": settings.FEATURE_COMPLIANCE_ENABLED,
        "archival_enabled": settings.FEATURE_ARCHIVAL_ENABLED,
        "notifications_enabled": settings.FEATURE_NOTIFICATIONS_ENABLED,
        "auto_provision": settings.FEATURE_AUTO_PROVISION,
    }


def get_tenant_features(client_id: str) -> dict:
    """Get client-specific feature flags. Falls back to global defaults."""
    table = _get_table(settings.PLATFORM_CONFIG_TABLE)
    resp = table.get_item(Key={"pk": f"TENANT#{client_id}", "sk": "FEATURES"})
    item = resp.get("Item")
    defaults = default_features()
    if not item:
        return defaults
    merged = {}
    for k, default_val in defaults.items():
        raw = item.get(k)
        if raw is None:
            merged[k] = default_val
        elif isinstance(default_val, bool):
            merged[k] = raw if isinstance(raw, bool) else str(raw).lower() == "true"
        else:
            merged[k] = type(default_val)(raw)
    return merged


def reset():
    """Clear cached table references. Called in tests."""
    _table_cache.clear()
