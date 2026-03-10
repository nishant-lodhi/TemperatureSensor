"""Lambda handler for Kinesis batch processing.

Triggered by Kinesis Data Stream with batches of 100-500 sensor records.
Per batch: decode → validate → enrich → update state → aggregate → alert → archive.
"""

import base64
import binascii
import json
import logging
from collections import defaultdict

from config import settings
from config.tenant_config import get_device_info, get_tenant_thresholds, get_tenant_features
from ingestion.validator import validate_event
from ingestion.normalizer import normalize_event
from storage import dynamodb_store, s3_store
from alerts.alert_engine import evaluate_critical, evaluate_thresholds, aggregate_zone_alerts, should_fire
from alerts.notifier import send_alert
from utils import parse_timestamp

logger = logging.getLogger(__name__)
logger.setLevel(settings.LOG_LEVEL)


def lambda_handler(event, context):
    """Kinesis batch event handler."""
    records = event.get("Records", [])
    logger.info("Processing batch of %d Kinesis records", len(records))

    decoded = _decode_records(records)
    valid, invalid = _validate_batch(decoded)
    if invalid:
        logger.warning("Rejected %d invalid records", len(invalid))

    enriched = _enrich_batch(valid)
    _update_states(enriched)
    _store_aggregates(enriched)

    features_cache = {}
    _check_alerts(enriched, features_cache)

    if settings.FEATURE_ARCHIVAL_ENABLED:
        _archive(enriched, features_cache)
    else:
        logger.info("Archival disabled by feature flag")

    return {"statusCode": 200, "processed": len(valid), "rejected": len(invalid)}


def _decode_records(records: list[dict]) -> list[dict]:
    decoded = []
    for record in records:
        try:
            payload = base64.b64decode(record["kinesis"]["data"])
            decoded.append(json.loads(payload))
        except (KeyError, json.JSONDecodeError, binascii.Error) as e:
            logger.error("Failed to decode record: %s", e)
    return decoded


def _validate_batch(raw_events: list[dict]) -> tuple[list, list]:
    valid, invalid = [], []
    for raw in raw_events:
        event = normalize_event(raw)
        ok, reason = validate_event(event)
        if ok:
            valid.append(event)
        else:
            invalid.append({"event": raw, "reason": reason})
    return valid, invalid


def _enrich_batch(events: list[dict]) -> list[dict]:
    enriched = []
    for event in events:
        device_info = get_device_info(event["device_id"])
        if device_info is None:
            if settings.FEATURE_AUTO_PROVISION:
                device_info = _auto_provision(event["device_id"], event.get("client_id", ""))
            else:
                logger.warning("Skipping unregistered device: %s", event["device_id"])
                continue
        event.update(device_info)
        enriched.append(event)
    return enriched


def _auto_provision(device_id: str, event_client_id: str = "") -> dict:
    """Register an unknown device, preserving client_id from the incoming event."""
    logger.info("Auto-provisioning device: %s (client: %s)", device_id, event_client_id or "unassigned")
    client_id = event_client_id or "unassigned"
    info = {
        "device_id": device_id,
        "client_id": client_id,
        "facility_id": "unassigned",
        "zone_id": "unassigned",
        "sensor_type": "temp_sensor",
        "status": "active",
    }
    dynamodb_store.update_sensor_state(device_id, {
        "client_id": client_id,
        "facility_id": info["facility_id"],
        "zone_id": info["zone_id"],
        "status": "active",
        "auto_provisioned": True,
    })
    return info


def _update_states(events: list[dict]):
    latest_by_device = {}
    for e in events:
        did = e["device_id"]
        if did not in latest_by_device or e["timestamp"] > latest_by_device[did]["timestamp"]:
            latest_by_device[did] = e

    for device_id, event in latest_by_device.items():
        state = {
            "last_temp": event["temperature"],
            "last_rssi": event.get("rssi"),
            "last_seen": event["timestamp"],
            "zone_id": event.get("zone_id"),
            "client_id": event.get("client_id"),
            "facility_id": event.get("facility_id"),
            "status": "online",
        }
        if "signal_dbm" in event:
            state["signal_dbm"] = event["signal_dbm"]
            state["signal_label"] = _classify_signal(event["signal_dbm"])
        if "battery_pct" in event:
            state["battery_pct"] = event["battery_pct"]
        dynamodb_store.update_sensor_state(device_id, state)


def _classify_signal(dbm) -> str:
    dbm = float(dbm)
    if dbm >= -50:
        return "Strong"
    if dbm >= -70:
        return "Good"
    if dbm >= -90:
        return "Weak"
    return "No Signal"


def _store_aggregates(events: list[dict]):
    by_device_minute = defaultdict(list)
    for e in events:
        ts = parse_timestamp(e["timestamp"])
        if ts is None:
            continue
        minute_key = ts.strftime("%Y-%m-%dT%H:%M:00Z")
        by_device_minute[(e["device_id"], minute_key)].append(e)

    for (device_id, minute_key), group in by_device_minute.items():
        temps = [g["temperature"] for g in group]
        agg = {
            "temperature": sum(temps) / len(temps),
            "temp_min": min(temps),
            "temp_max": max(temps),
            "reading_count": len(temps),
        }
        signal_vals = [g["signal_dbm"] for g in group if "signal_dbm" in g]
        if signal_vals:
            agg["signal_dbm_avg"] = sum(signal_vals) / len(signal_vals)
        batt_vals = [g["battery_pct"] for g in group if "battery_pct" in g]
        if batt_vals:
            agg["battery_pct_avg"] = sum(batt_vals) / len(batt_vals)
        dynamodb_store.put_reading(device_id, minute_key, agg)


def _get_features(client_id: str, cache: dict) -> dict:
    if client_id not in cache:
        cache[client_id] = get_tenant_features(client_id)
    return cache[client_id]


def _check_alerts(events: list[dict], features_cache: dict):
    devices_in_batch = {e["device_id"] for e in events}
    zone_alerts = defaultdict(list)

    for device_id in devices_in_batch:
        device_events = [e for e in events if e["device_id"] == device_id]
        if not device_events:
            continue
        sample = device_events[0]
        client_id = sample.get("client_id", "")
        features = _get_features(client_id, features_cache)
        if not features.get("alerts_enabled", True):
            continue

        thresholds = get_tenant_thresholds(client_id)
        state = dynamodb_store.get_sensor_state(device_id) or {}
        alerts = evaluate_thresholds(device_id, state, device_events, thresholds, features)

        for evt in device_events:
            critical = evaluate_critical(evt, thresholds, features)
            if critical:
                critical["device_id"] = device_id
                critical["client_id"] = client_id
                alerts.append(critical)
                break

        zone_id = sample.get("zone_id", "unknown")
        facility_id = sample.get("facility_id", "unknown")
        for a in alerts:
            zone_alerts[(facility_id, zone_id)].append(a)

    for (facility_id, zone_id), device_alerts in zone_alerts.items():
        aggregated = aggregate_zone_alerts(device_alerts, zone_id, facility_id)
        active = dynamodb_store.get_active_alerts(f"{facility_id}#{zone_id}")
        for alert in aggregated:
            if "client_id" not in alert:
                alert["client_id"] = device_alerts[0].get("client_id", "")
            if should_fire(alert, active):
                dynamodb_store.put_alert(f"{facility_id}#{zone_id}", alert)
                send_alert(alert)


def _archive(events: list[dict], features_cache: dict):
    by_client = defaultdict(list)
    for e in events:
        by_client[e.get("client_id", "unknown")].append(e)
    for client_id, records in by_client.items():
        features = _get_features(client_id, features_cache)
        if not features.get("archival_enabled", True):
            logger.info("Archival disabled for tenant %s", client_id)
            continue
        s3_store.archive_batch(records, client_id)
