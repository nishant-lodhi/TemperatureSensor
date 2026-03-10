"""Unit tests for reports/compliance.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

from datetime import datetime, timedelta


from reports.compliance import compute_compliance, generate_daily_report, generate_shift_summary


def make_readings(base_iso, minute_offsets, temperatures):
    """Build readings with timestamps at base + minute_offsets (minutes)."""
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    return [
        {
            "timestamp": (base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temperature": t,
        }
        for m, t in zip(minute_offsets, temperatures)
    ]


def test_compliance_all_within():
    """all readings in range → 100%."""
    readings = make_readings("2024-10-01T12:00:00Z", range(10), [75.0] * 10)
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert result["compliance_pct"] == 100.0
    assert result["total_readings"] == 10
    assert result["compliant_readings"] == 10
    assert result["non_compliant_readings"] == 0
    assert result["breach_count"] == 0


def test_compliance_some_breaches():
    """readings with some outside range → correct %."""
    temps = [75.0, 76.0, 90.0, 91.0, 75.0]
    readings = make_readings("2024-10-01T12:00:00Z", range(5), temps)
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert result["compliance_pct"] == 60.0
    assert result["total_readings"] == 5
    assert result["compliant_readings"] == 3
    assert result["non_compliant_readings"] == 2


def test_compliance_empty():
    """empty readings → 100%, 0 total."""
    result = compute_compliance([], temp_low=65, temp_high=85)
    assert result["compliance_pct"] == 100.0
    assert result["total_readings"] == 0
    assert result["compliant_readings"] == 0
    assert result["non_compliant_readings"] == 0
    assert result["breaches"] == []


def test_find_breaches_single():
    """one contiguous breach period detected."""
    temps = [75.0, 76.0, 90.0, 91.0, 92.0, 75.0]
    readings = make_readings("2024-10-01T12:00:00Z", range(6), temps)
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert len(result["breaches"]) == 1
    b = result["breaches"][0]
    assert b["direction"] == "high"
    assert b["reading_count"] == 3
    assert b["duration_min"] == 3.0


def test_find_breaches_multiple():
    """two separate breach periods."""
    temps = [90.0, 91.0, 75.0, 76.0, 90.0, 91.0]
    readings = make_readings("2024-10-01T12:00:00Z", range(6), temps)
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert len(result["breaches"]) == 2


def test_find_breaches_none():
    """all within range → empty list."""
    readings = make_readings("2024-10-01T12:00:00Z", range(5), [75.0, 76.0, 80.0, 78.0, 77.0])
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert result["breaches"] == []


def test_breach_duration():
    """verify duration_min calculated correctly."""
    temps = [90.0, 91.0, 92.0]
    readings = make_readings("2024-10-01T12:00:00Z", [0, 1, 2], temps)
    result = compute_compliance(readings, temp_low=65, temp_high=85)
    assert len(result["breaches"]) == 1
    assert result["breaches"][0]["duration_min"] == 2.0
    assert result["breaches"][0]["reading_count"] == 3


def test_generate_daily_report():
    """verify structure with zones, ranking, recommendations."""
    zone_compliance = {
        "zone_a": {"compliance_pct": 98.5, "total_readings": 100, "breach_count": 1},
        "zone_b": {"compliance_pct": 92.0, "total_readings": 50, "breach_count": 2},
        "zone_c": {"compliance_pct": 100.0, "total_readings": 80, "breach_count": 0},
    }
    result = generate_daily_report(zone_compliance, "facility_A", "2024-10-01")
    assert "overall_compliance_pct" in result
    assert result["zones"] == zone_compliance
    assert "zone_ranking" in result
    assert len(result["zone_ranking"]) == 3
    assert result["zone_ranking"][0]["zone_id"] == "zone_b"
    assert result["zone_ranking"][0]["compliance_pct"] == 92.0
    assert "recommendations" in result
    assert any("zone_b" in r for r in result["recommendations"])
    assert result["facility_id"] == "facility_A"
    assert result["date"] == "2024-10-01"


def test_generate_shift_summary():
    """verify structure with active/resolved alerts."""
    zone_compliance = {"zone_a": {"compliance_pct": 95.0}}
    active_alerts = [{"alert_type": "EXTREME_TEMPERATURE", "severity": "CRITICAL"}]
    resolved_alerts = [{"alert_type": "SUSTAINED_HIGH", "severity": "HIGH"}]
    result = generate_shift_summary(
        zone_compliance,
        active_alerts,
        resolved_alerts,
        "facility_A",
        "2024-10-01T06:00:00Z",
        "2024-10-01T14:00:00Z",
    )
    assert result["facility_id"] == "facility_A"
    assert result["shift_start"] == "2024-10-01T06:00:00Z"
    assert result["shift_end"] == "2024-10-01T14:00:00Z"
    assert result["overall_compliance_pct"] == 95.0
    assert result["zone_compliance"] == zone_compliance
    assert result["active_alerts_count"] == 1
    assert result["active_alerts"] == active_alerts
    assert result["resolved_alerts_count"] == 1
    assert result["resolved_alerts"] == resolved_alerts
