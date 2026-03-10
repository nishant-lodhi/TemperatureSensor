"""Lambda handler for scheduled analytics, forecasting, and reporting.

Triggered by EventBridge with mode parameter:
  mode=analytics  → every 15 min: rolling metrics, anomaly detection
  mode=forecast   → every 1 hr: temperature predictions
  mode=compliance → daily 6 AM: compliance report
  mode=shift      → shift changes: handoff summary
"""

import logging
from datetime import datetime, timedelta, timezone

from config import settings
from config.tenant_config import get_tenant_thresholds, get_tenant_features
from storage import dynamodb_store, s3_store
from analytics import rolling_metrics, anomaly_detection
from forecasting import forecast_model
from alerts.alert_engine import evaluate_analytics_alerts, should_fire
from alerts.notifier import send_alert
from reports import compliance

logger = logging.getLogger(__name__)
logger.setLevel(settings.LOG_LEVEL)


def lambda_handler(event, context):
    """Route to the correct handler based on event mode."""
    mode = event.get("mode", "analytics")
    logger.info("Scheduled processor running mode=%s", mode)
    handler = _MODE_HANDLERS.get(mode)
    if not handler:
        logger.error("Unknown mode: %s", mode)
        return {"statusCode": 400, "error": f"Unknown mode: {mode}"}
    return handler(event)


def _handle_analytics(event: dict) -> dict:
    if not settings.FEATURE_ANALYTICS_ENABLED:
        logger.info("Analytics disabled by global feature flag")
        return {"statusCode": 200, "mode": "analytics", "skipped": True}

    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=2)).isoformat() + "Z"
    states = dynamodb_store.get_all_sensor_states()
    processed = 0

    for state in states:
        device_id = state["pk"]
        client_id = state.get("client_id", "")
        features = get_tenant_features(client_id)
        if not features.get("analytics_enabled", True):
            continue

        readings = dynamodb_store.get_readings(device_id, since)
        reading_dicts = _to_reading_dicts(readings)

        metrics = rolling_metrics.compute_all_metrics(reading_dicts)
        avg = metrics.get("rolling_avg_1h")
        std = metrics.get("rolling_std_1h")

        anomaly_result = {"is_anomaly": False}
        if avg is not None and std is not None:
            current_temp = float(state.get("last_temp", 0))
            anomaly_result = anomaly_detection.detect_anomaly(current_temp, avg, std)

        min_max_1h = metrics.get("min_max_1h") or {}
        dbm = float(state.get("signal_dbm", state.get("last_rssi", -50)))

        dynamodb_store.update_sensor_state(device_id, {
            "rolling_avg_10m": metrics.get("rolling_avg_10m"),
            "rolling_avg_1h": avg,
            "rolling_std_1h": std,
            "rate_of_change_10m": metrics.get("rate_of_change_10m"),
            "rate_of_change": metrics.get("rate_of_change_10m"),
            "actual_high_1h": min_max_1h.get("max"),
            "actual_low_1h": min_max_1h.get("min"),
            "anomaly": anomaly_result.get("is_anomaly", False),
            "anomaly_flag": anomaly_result.get("is_anomaly", False),
            "anomaly_reason": anomaly_result.get("reason"),
            "signal_label": _classify_signal(dbm),
        })

        thresholds = get_tenant_thresholds(client_id)
        alerts = evaluate_analytics_alerts(
            device_id, state, anomaly_result, None, thresholds, now, features,
        )
        _fire_alerts(alerts, state, features)
        processed += 1

    logger.info("Analytics completed for %d devices", processed)
    return {"statusCode": 200, "mode": "analytics", "devices_processed": processed}


def _handle_forecast(event: dict) -> dict:
    if not settings.FEATURE_FORECASTING_ENABLED:
        logger.info("Forecasting disabled by global feature flag")
        return {"statusCode": 200, "mode": "forecast", "skipped": True}

    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=4)).isoformat() + "Z"
    states = dynamodb_store.get_all_sensor_states()
    processed = 0

    for state in states:
        device_id = state["pk"]
        client_id = state.get("client_id", "")
        features = get_tenant_features(client_id)
        if not features.get("forecasting_enabled", True):
            continue

        readings = dynamodb_store.get_readings(device_id, since)
        reading_dicts = _to_reading_dicts(readings)

        result = forecast_model.forecast_temperature(reading_dicts)
        if result is None:
            continue

        for horizon_key in ("forecast_30min", "forecast_2hr"):
            fc = result.get(horizon_key, {})
            if fc:
                fc["predicted_at"] = now.isoformat()
                fc["model_params"] = result["model_params"]
                dynamodb_store.put_forecast(
                    device_id, horizon_key.split("_", 1)[1], fc,
                )

        thresholds = get_tenant_thresholds(client_id)
        alerts = evaluate_analytics_alerts(
            device_id, state, {"is_anomaly": False}, result, thresholds, now, features,
        )
        _fire_alerts(alerts, state, features)
        processed += 1

    logger.info("Forecast completed for %d devices", processed)
    return {"statusCode": 200, "mode": "forecast", "devices_processed": processed}


def _handle_compliance(event: dict) -> dict:
    if not settings.FEATURE_COMPLIANCE_ENABLED:
        logger.info("Compliance disabled by global feature flag")
        return {"statusCode": 200, "mode": "compliance", "skipped": True}

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    since = yesterday.replace(hour=0, minute=0, second=0).isoformat() + "Z"

    states = dynamodb_store.get_all_sensor_states()
    zone_readings = {}
    facility_id = None
    client_id = None

    for state in states:
        device_id = state["pk"]
        zone_id = state.get("zone_id", "unknown")
        facility_id = facility_id or state.get("facility_id", "unknown")
        client_id = client_id or state.get("client_id", "unknown")

        readings = dynamodb_store.get_readings(device_id, since)
        zone_readings.setdefault(zone_id, []).extend(_to_reading_dicts(readings))

    features = get_tenant_features(client_id or "unknown")
    if not features.get("compliance_enabled", True):
        logger.info("Compliance disabled for tenant %s", client_id)
        return {"statusCode": 200, "mode": "compliance", "skipped": True}

    zone_compliance = {z: compliance.compute_compliance(r) for z, r in zone_readings.items()}
    report = compliance.generate_daily_report(
        zone_compliance, facility_id or "unknown", date_str,
    )
    s3_store.store_report(report, client_id or "unknown", "daily_compliance", date_str)
    logger.info("Compliance report generated for %s", date_str)
    return {"statusCode": 200, "mode": "compliance", "date": date_str}


def _handle_shift(event: dict) -> dict:
    logger.info("Shift summary generation — placeholder")
    return {"statusCode": 200, "mode": "shift", "status": "placeholder"}


# ── Helpers ───────────────────────────────────────────────


def _to_reading_dicts(raw_items: list[dict]) -> list[dict]:
    return [
        {"temperature": float(r.get("temperature", 0)), "timestamp": r["sk"].split("#", 1)[1]}
        for r in raw_items
        if r.get("sk", "").startswith("R#")
    ]


def _fire_alerts(alerts: list[dict], state: dict, features: dict | None = None):
    for alert in alerts:
        fz = f"{state.get('facility_id', 'unknown')}#{state.get('zone_id', 'unknown')}"
        active = dynamodb_store.get_active_alerts(fz)
        if should_fire(alert, active):
            alert["facility_zone"] = fz
            dynamodb_store.put_alert(fz, alert)
            notifications_on = (features or {}).get("notifications_enabled", True)
            if notifications_on and settings.FEATURE_NOTIFICATIONS_ENABLED:
                send_alert(alert)
            else:
                logger.info("Notification suppressed for alert %s", alert.get("alert_type"))


def _classify_signal(dbm: float) -> str:
    if dbm >= -50:
        return "Strong"
    if dbm >= -70:
        return "Good"
    if dbm >= -90:
        return "Weak"
    return "No Signal"


_MODE_HANDLERS = {
    "analytics": _handle_analytics,
    "forecast": _handle_forecast,
    "compliance": _handle_compliance,
    "shift": _handle_shift,
}
