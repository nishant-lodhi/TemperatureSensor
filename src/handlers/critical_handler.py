"""Lambda handler for critical alert processing.

Triggered directly by IoT Core rule when SQL filter matches extreme conditions.
Processes a single event with sub-second latency.
"""

import json
import logging

from config import settings
from config.tenant_config import get_device_info, get_tenant_thresholds, get_tenant_features
from ingestion.validator import validate_event
from ingestion.normalizer import normalize_event
from alerts.alert_engine import evaluate_critical
from alerts.notifier import send_alert
from storage import dynamodb_store

logger = logging.getLogger(__name__)
logger.setLevel(settings.LOG_LEVEL)


def lambda_handler(event, context):
    """IoT Core direct trigger handler for extreme temperature events."""
    logger.info("Critical alert check: %s", json.dumps(event, default=str))

    normalized = normalize_event(event)
    ok, reason = validate_event(normalized)
    if not ok:
        logger.error("Invalid critical event: %s", reason)
        return {"statusCode": 400, "error": reason}

    device_info = get_device_info(normalized["device_id"])
    client_id = ""
    if device_info:
        normalized.update(device_info)
        client_id = device_info["client_id"]
        thresholds = get_tenant_thresholds(client_id)
    else:
        logger.warning("Unregistered device in critical path: %s", normalized["device_id"])
        thresholds = get_tenant_thresholds("")

    features = get_tenant_features(client_id)
    alert = evaluate_critical(normalized, thresholds, features)
    if alert:
        alert["device_id"] = normalized["device_id"]
        alert["zone_id"] = normalized.get("zone_id", "unknown")
        alert["facility_id"] = normalized.get("facility_id", "unknown")
        fz = f"{alert['facility_id']}#{alert['zone_id']}"
        dynamodb_store.put_alert(fz, alert)
        if features.get("notifications_enabled", True) and settings.FEATURE_NOTIFICATIONS_ENABLED:
            send_alert(alert)
        logger.info("CRITICAL alert fired: %s", alert["message"])
        return {"statusCode": 200, "alert": alert}

    logger.info("No critical condition for device %s", normalized["device_id"])
    return {"statusCode": 200, "alert": None}
