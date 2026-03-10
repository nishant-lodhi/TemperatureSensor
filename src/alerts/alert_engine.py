"""Alert engine: evaluates rules, aggregates, manages lifecycle.

Every evaluation function accepts an optional `features` dict of boolean flags.
When a flag is False, that check is skipped entirely.  This lets operators
and per-tenant config disable individual alert types without code changes.
"""

from datetime import datetime, timezone

from config import settings
from config.tenant_config import default_features
from alerts.alert_rules import (
    EXTREME_TEMP,
    SUSTAINED_HIGH,
    SENSOR_OFFLINE,
    ANOMALY,
    check_extreme_temperature,
    check_sustained_high,
    check_rapid_change,
    check_sensor_offline,
    check_anomaly,
    check_forecast_breach,
)

ESCALATE_SUPERVISOR_SEC = getattr(settings, "ESCALATE_SUPERVISOR_SEC", 300)
ESCALATE_MANAGER_SEC = getattr(settings, "ESCALATE_MANAGER_SEC", 900)
HYSTERESIS_F = getattr(settings, "HYSTERESIS_F", 2.0)

_DEFAULT_FEATURES = None


def _get_default_features() -> dict:
    global _DEFAULT_FEATURES
    if _DEFAULT_FEATURES is None:
        _DEFAULT_FEATURES = default_features()
    return _DEFAULT_FEATURES


def _resolve_features(features: dict | None) -> dict:
    return features if features is not None else _get_default_features()


def reset():
    """Clear cached default features. Called in tests."""
    global _DEFAULT_FEATURES
    _DEFAULT_FEATURES = None


def _severity_rank(severity: str) -> int:
    """Lower is more severe."""
    ranks = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "WARNING": 3, "LOW": 4}
    return ranks.get(severity, 5)


def _thresholds_dict(overrides: dict | None = None) -> dict:
    """Build thresholds dict from settings."""
    d = {
        "temp_critical_high": getattr(settings, "TEMP_CRITICAL_HIGH", 95.0),
        "temp_critical_low": getattr(settings, "TEMP_CRITICAL_LOW", 50.0),
        "temp_high": getattr(settings, "TEMP_HIGH", 85.0),
        "temp_low": getattr(settings, "TEMP_LOW", 65.0),
        "sustained_duration_min": getattr(settings, "SUSTAINED_DURATION_MIN", 10),
        "rapid_change_threshold_f": getattr(settings, "RAPID_CHANGE_THRESHOLD_F", 4.0),
        "sensor_offline_sec": getattr(settings, "SENSOR_OFFLINE_SEC", 60),
    }
    if overrides:
        d.update(overrides)
    return d


def evaluate_critical(
    event: dict,
    thresholds: dict | None = None,
    features: dict | None = None,
) -> dict | None:
    """Evaluate extreme temperature for a single event. Skips if flags disabled."""
    feat = _resolve_features(features)
    if not feat.get("alerts_enabled", True) or not feat.get("alert_extreme_temp", True):
        return None
    thresh = thresholds or _thresholds_dict()
    temp = event.get("temperature")
    if temp is None:
        return None
    return check_extreme_temperature(float(temp), thresh)


def evaluate_thresholds(
    device_id: str,
    sensor_state: dict,
    readings: list[dict],
    thresholds: dict | None = None,
    features: dict | None = None,
) -> list[dict]:
    """Evaluate sustained high and rapid change. Skips disabled alert types."""
    feat = _resolve_features(features)
    if not feat.get("alerts_enabled", True):
        return []
    thresh = thresholds or _thresholds_dict()
    alerts = []

    if feat.get("alert_sustained_high", True):
        sustained = check_sustained_high(readings, thresh)
        if sustained:
            sustained["device_id"] = device_id
            alerts.append(sustained)

    rate = sensor_state.get("rate_of_change_10m") or sensor_state.get("rate_of_change_f_per_min")
    if rate is not None and feat.get("alert_rapid_change", True):
        rapid = check_rapid_change(rate, thresh)
        if rapid:
            rapid["device_id"] = device_id
            alerts.append(rapid)

    return alerts


def evaluate_analytics_alerts(
    device_id: str,
    sensor_state: dict,
    anomaly_result: dict | None,
    forecast: dict | None,
    thresholds: dict | None = None,
    current_time=None,
    features: dict | None = None,
) -> list[dict]:
    """Check offline, anomaly, forecast breach. Skips disabled alert types."""
    feat = _resolve_features(features)
    if not feat.get("alerts_enabled", True):
        return []
    thresh = thresholds or _thresholds_dict()
    alerts = []

    if feat.get("alert_sensor_offline", True):
        last_seen = sensor_state.get("last_seen")
        offline = check_sensor_offline(last_seen, current_time, thresh)
        if offline:
            offline["device_id"] = device_id
            alerts.append(offline)

    if anomaly_result and feat.get("alert_anomaly", True):
        anom = check_anomaly(anomaly_result)
        if anom:
            anom["device_id"] = device_id
            alerts.append(anom)

    if feat.get("alert_forecast_breach", True):
        for key in ("forecast_30min", "forecast_2hr"):
            fc = (forecast or {}).get(key) if isinstance(forecast, dict) else None
            if fc:
                breach = check_forecast_breach(fc, thresh)
                if breach:
                    breach["device_id"] = device_id
                    breach["forecast_horizon"] = key
                    alerts.append(breach)

    return alerts


def aggregate_zone_alerts(
    device_alerts: list[dict],
    zone_id: str,
    facility_id: str,
) -> list[dict]:
    """Group by alert_type. Merge 2+ same type into zone-level with affected_devices."""
    by_type: dict[str, list[dict]] = {}
    for a in device_alerts:
        t = a.get("alert_type", "UNKNOWN")
        by_type.setdefault(t, []).append(a)

    result = []
    for alert_type, group in by_type.items():
        if len(group) >= 2:
            merged = {
                "alert_type": alert_type,
                "severity": max(group, key=lambda x: 5 - _severity_rank(x.get("severity", ""))).get("severity", "MEDIUM"),
                "message": f"{len(group)} devices: {alert_type}",
                "triggered_at": group[0].get("triggered_at"),
                "status": "ACTIVE",
                "zone_id": zone_id,
                "facility_id": facility_id,
                "facility_zone": f"{facility_id}/{zone_id}",
                "affected_devices": [a.get("device_id") for a in group if a.get("device_id")],
                "device_count": len(group),
            }
            result.append(merged)
        else:
            single = dict(group[0])
            single["zone_id"] = zone_id
            single["facility_id"] = facility_id
            single["facility_zone"] = f"{facility_id}/{zone_id}"
            result.append(single)

    return result


def should_fire(new_alert: dict, active_alerts: list[dict]) -> bool:
    """False if same alert_type+device_id already active, or same type+zone_id with device_count>0."""
    atype = new_alert.get("alert_type")
    did = new_alert.get("device_id")
    zid = new_alert.get("zone_id")

    for a in active_alerts:
        if a.get("alert_type") != atype:
            continue
        if a.get("status") != "ACTIVE":
            continue
        if did and a.get("device_id") == did:
            return False
        if zid and a.get("zone_id") == zid and a.get("device_count", 0) > 0:
            return False
    return True


def check_escalation(alert: dict, current_time=None) -> str | None:
    """Return 'facility_manager' if elapsed > ESCALATE_MANAGER_SEC, 'supervisor' if > ESCALATE_SUPERVISOR_SEC."""
    if alert.get("acknowledged"):
        return None
    triggered = alert.get("triggered_at")
    if not triggered:
        return None
    from utils import parse_timestamp
    ts = parse_timestamp(triggered)
    if ts is None:
        return None
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    elapsed = (now - ts).total_seconds()

    if elapsed > ESCALATE_MANAGER_SEC:
        return "facility_manager"
    if elapsed > ESCALATE_SUPERVISOR_SEC:
        return "supervisor"
    return None


def check_auto_resolve(
    alert: dict,
    sensor_state: dict,
    thresholds: dict | None = None,
) -> bool:
    """True if condition cleared based on alert_type."""
    thresh = thresholds or _thresholds_dict()
    atype = alert.get("alert_type")

    if atype == SUSTAINED_HIGH:
        rolling = sensor_state.get("rolling_avg_10m")
        temp_high = thresh.get("temp_high")
        if rolling is not None and temp_high is not None:
            return rolling < temp_high - HYSTERESIS_F
        return False

    if atype == EXTREME_TEMP:
        temp = sensor_state.get("temperature")
        if temp is None:
            return False
        t = float(temp)
        high = thresh.get("temp_critical_high")
        low = thresh.get("temp_critical_low")
        if high is not None and t <= high - 5:
            return True
        if low is not None and t >= low + 5:
            return True
        return False

    if atype == SENSOR_OFFLINE:
        return sensor_state.get("status") != "offline"

    if atype == ANOMALY:
        return sensor_state.get("anomaly_flag") is False

    return False
