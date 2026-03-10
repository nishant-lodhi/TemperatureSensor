"""Compliance reporting for temperature sensor analytics."""

import numpy as np

from config import settings
from utils import parse_timestamp

COMPLIANCE_TEMP_LOW = getattr(settings, "COMPLIANCE_TEMP_LOW", 65.0)
COMPLIANCE_TEMP_HIGH = getattr(settings, "COMPLIANCE_TEMP_HIGH", 85.0)


def _find_breaches(
    readings: list[dict],
    temp_low: float,
    temp_high: float,
) -> list[dict]:
    """Find contiguous breach periods. Each: start, end, duration_min, reading_count, avg_temp, peak_temp, direction."""
    if not readings:
        return []
    breaches = []
    in_breach = False
    breach_start = None
    breach_temps = []

    for r in readings:
        ts = r.get("timestamp")
        temp = r.get("temperature")
        if temp is None:
            continue
        t = float(temp)
        dt = parse_timestamp(ts)
        if dt is None:
            continue

        is_high = t > temp_high
        is_low = t < temp_low
        is_breach = is_high or is_low

        if is_breach:
            if not in_breach:
                in_breach = True
                breach_start = dt
                breach_temps = [t]
            else:
                breach_temps.append(t)
        else:
            if in_breach:
                direction = "high" if any(x > temp_high for x in breach_temps) else "low"
                breaches.append({
                    "start": breach_start.isoformat(),
                    "end": dt.isoformat(),
                    "duration_min": (dt - breach_start).total_seconds() / 60,
                    "reading_count": len(breach_temps),
                    "avg_temp": float(np.mean(breach_temps)),
                    "peak_temp": max(breach_temps) if direction == "high" else min(breach_temps),
                    "direction": direction,
                })
                in_breach = False
                breach_temps = []

    if in_breach and breach_start and breach_temps:
        last_dt = parse_timestamp(readings[-1].get("timestamp")) or breach_start
        direction = "high" if any(x > temp_high for x in breach_temps) else "low"
        breaches.append({
            "start": breach_start.isoformat(),
            "end": last_dt.isoformat(),
            "duration_min": (last_dt - breach_start).total_seconds() / 60,
            "reading_count": len(breach_temps),
            "avg_temp": float(np.mean(breach_temps)),
            "peak_temp": max(breach_temps) if direction == "high" else min(breach_temps),
            "direction": direction,
        })

    return breaches


def compute_compliance(
    readings: list[dict],
    temp_low: float | None = None,
    temp_high: float | None = None,
) -> dict:
    """Return compliance_pct, total/compliant/non_compliant counts, breach_count, breaches list, temp_range."""
    low = temp_low if temp_low is not None else COMPLIANCE_TEMP_LOW
    high = temp_high if temp_high is not None else COMPLIANCE_TEMP_HIGH

    temps = [float(r["temperature"]) for r in readings if "temperature" in r]
    if not temps:
        return {
            "compliance_pct": 100.0,
            "total_readings": 0,
            "compliant_readings": 0,
            "non_compliant_readings": 0,
            "breach_count": 0,
            "breaches": [],
            "temp_range": None,
        }

    total = len(temps)
    compliant = sum(1 for t in temps if low <= t <= high)
    non_compliant = total - compliant
    pct = 100.0 * compliant / total if total else 100.0
    breaches = _find_breaches(readings, low, high)

    return {
        "compliance_pct": round(pct, 2),
        "total_readings": total,
        "compliant_readings": compliant,
        "non_compliant_readings": non_compliant,
        "breach_count": len(breaches),
        "breaches": breaches,
        "temp_range": (min(temps), max(temps)),
    }


def generate_daily_report(
    zone_compliance: dict[str, dict],
    facility_id: str,
    date_str: str,
    alert_summary: dict | None = None,
) -> dict:
    """Overall compliance, zones dict, zone_ranking (worst first), recommendations for zones below 95%."""
    zones = dict(zone_compliance)
    overall = 100.0
    if zones:
        overall = sum(z.get("compliance_pct", 0) for z in zones.values()) / len(zones)

    ranking = sorted(
        zones.items(),
        key=lambda x: x[1].get("compliance_pct", 100),
    )

    recommendations = []
    for zid, stats in zones.items():
        if stats.get("compliance_pct", 100) < 95:
            recommendations.append(f"Zone {zid}: compliance {stats.get('compliance_pct', 0):.1f}% - review thresholds and sensor placement")

    return {
        "overall_compliance_pct": round(overall, 2),
        "zones": zones,
        "zone_ranking": [{"zone_id": zid, "compliance_pct": s.get("compliance_pct")} for zid, s in ranking],
        "recommendations": recommendations,
        "facility_id": facility_id,
        "date": date_str,
        "alert_summary": alert_summary,
    }


def generate_shift_summary(
    zone_compliance: dict[str, dict],
    active_alerts: list[dict],
    resolved_alerts: list[dict],
    facility_id: str,
    shift_start: str,
    shift_end: str,
) -> dict:
    """Shift summary with compliance, active/resolved alerts."""
    overall = 100.0
    if zone_compliance:
        overall = sum(z.get("compliance_pct", 0) for z in zone_compliance.values()) / len(zone_compliance)

    return {
        "facility_id": facility_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "overall_compliance_pct": round(overall, 2),
        "zone_compliance": zone_compliance,
        "active_alerts_count": len(active_alerts),
        "active_alerts": active_alerts,
        "resolved_alerts_count": len(resolved_alerts),
        "resolved_alerts": resolved_alerts,
    }
