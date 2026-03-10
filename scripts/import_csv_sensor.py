#!/usr/bin/env python3
"""Import real sensor CSV data into DynamoDB as offline historical sensors.

Reads the CSV, time-shifts readings to end ~2 hours ago (making sensor appear
offline), aggregates to per-minute readings, and writes:
  - STATE record (offline) with client_id
  - R# per-minute reading records (covering 48h+ for history views)
  - Alert records for readings that crossed thresholds

Usage:
    python scripts/import_csv_sensor.py \
        --csv data/temp-sensor-final.csv \
        --table temp-sensor-sensor-data-244d4b8211-dev \
        --alerts-table temp-sensor-alerts-244d4b8211-dev \
        --client-id 244d4b8211 \
        --region us-west-2 \
        --profile saas-deployment
"""

import argparse
import csv
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import boto3


def _decimal(v):
    return Decimal(str(v)) if v is not None else None


def _classify_signal(dbm):
    dbm = float(dbm)
    if dbm >= -50:
        return "Strong"
    if dbm >= -70:
        return "Good"
    if dbm >= -90:
        return "Weak"
    return "No Signal"


def parse_csv(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                temp = float(row["body_temperature"])
                rssi = int(row["rssi"])
                ts = row["timestamp"].strip()
                mac = row["mac"].strip()
                if temp and ts and mac:
                    rows.append({"mac": mac, "temperature": temp, "rssi": rssi, "timestamp": ts})
            except (ValueError, KeyError):
                continue
    return rows


def prepare_timestamps(rows, keep_original=True):
    """Parse timestamps. If keep_original=True, use original CSV dates."""
    for r in rows:
        r["_dt"] = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
    return rows


def aggregate_per_minute(rows):
    """Group readings by (mac, minute) and compute aggregates."""
    by_minute = defaultdict(list)
    for r in rows:
        minute_key = r["_dt"].strftime("%Y-%m-%dT%H:%M:00Z")
        by_minute[(r["mac"], minute_key)].append(r)

    aggregates = []
    for (mac, minute_key), group in sorted(by_minute.items()):
        temps = [g["temperature"] for g in group]
        rssis = [g["rssi"] for g in group]
        aggregates.append({
            "mac": mac,
            "minute_key": minute_key,
            "temperature": sum(temps) / len(temps),
            "temp_min": min(temps),
            "temp_max": max(temps),
            "reading_count": len(temps),
            "signal_dbm": sum(rssis) / len(rssis),
        })
    return aggregates


def build_state_record(mac, aggregates, client_id):
    """Build an offline STATE record from the last aggregate."""
    last = aggregates[-1]
    temps = [a["temperature"] for a in aggregates[-60:]]
    avg_1h = sum(temps) / len(temps) if temps else 0
    high_1h = max(temps) if temps else 0
    low_1h = min(temps) if temps else 0

    dbm = last["signal_dbm"]
    return {
        "pk": mac,
        "sk": "STATE",
        "client_id": client_id,
        "facility_id": "imported",
        "zone_id": "imported",
        "status": "offline",
        "last_temp": _decimal(last["temperature"]),
        "temperature": _decimal(last["temperature"]),
        "last_rssi": _decimal(dbm),
        "signal_dbm": _decimal(dbm),
        "signal_label": _classify_signal(dbm),
        "battery_pct": 0,
        "last_seen": last["minute_key"],
        "rolling_avg_1h": _decimal(avg_1h),
        "actual_high_1h": _decimal(high_1h),
        "actual_low_1h": _decimal(low_1h),
        "rate_of_change": _decimal(0),
        "rate_of_change_10m": _decimal(0),
        "anomaly": False,
        "anomaly_flag": False,
        "auto_provisioned": False,
    }


def build_reading_items(aggregates, mac):
    """Build R# items for DynamoDB."""
    items = []
    for agg in aggregates:
        item = {
            "pk": mac,
            "sk": f"R#{agg['minute_key']}",
            "temperature": _decimal(agg["temperature"]),
            "temp_min": _decimal(agg["temp_min"]),
            "temp_max": _decimal(agg["temp_max"]),
            "reading_count": agg["reading_count"],
            "signal_dbm_avg": _decimal(agg["signal_dbm"]),
            "ttl": int(time.time()) + (30 * 24 * 3600),
        }
        items.append(item)
    return items


def build_alert_items(aggregates, mac, client_id, temp_high=85.0, temp_critical=95.0):
    """Generate alert records for readings that crossed thresholds."""
    alerts = []
    in_breach = False
    breach_start = None

    for agg in aggregates:
        temp = agg["temperature"]
        ts = agg["minute_key"]

        if temp > temp_critical and not any(a["alert_type"] == "EXTREME_TEMPERATURE" and a.get("_near", "") == ts for a in alerts):
            alerts.append({
                "pk": f"imported#{mac}",
                "alert_type": "EXTREME_TEMPERATURE",
                "severity": "CRITICAL",
                "message": f"Temperature {temp:.1f}°F exceeds critical {temp_critical}°F",
                "device_id": mac,
                "client_id": client_id,
                "status": "RESOLVED",
                "triggered_at": ts,
                "resolved_at": ts,
                "_near": ts,
            })

        if temp > temp_high:
            if not in_breach:
                breach_start = ts
                in_breach = True
        else:
            if in_breach and breach_start:
                alerts.append({
                    "pk": f"imported#{mac}",
                    "alert_type": "SUSTAINED_HIGH",
                    "severity": "HIGH",
                    "message": f"Temperature exceeded {temp_high}°F from {breach_start}",
                    "device_id": mac,
                    "client_id": client_id,
                    "status": "RESOLVED",
                    "triggered_at": breach_start,
                    "resolved_at": ts,
                })
            in_breach = False
            breach_start = None

    # The sensor is now offline — add an active offline alert
    if aggregates:
        alerts.append({
            "pk": f"imported#{mac}",
            "alert_type": "SENSOR_OFFLINE",
            "severity": "WARNING",
            "message": f"Sensor {mac} has not reported since {aggregates[-1]['minute_key']}",
            "device_id": mac,
            "client_id": client_id,
            "status": "ACTIVE",
            "triggered_at": aggregates[-1]["minute_key"],
        })

    return alerts


def batch_write(table, items, label="items"):
    """Write items in batches of 25."""
    written = 0
    for i in range(0, len(items), 25):
        batch = items[i:i + 25]
        with table.batch_writer() as writer:
            for item in batch:
                clean = {k: v for k, v in item.items() if v is not None and not k.startswith("_")}
                writer.put_item(Item=clean)
        written += len(batch)
        if written % 500 == 0:
            print(f"  {label}: {written}/{len(items)}")
    print(f"  {label}: {written}/{len(items)} done")


def main():
    parser = argparse.ArgumentParser(description="Import CSV sensor data into DynamoDB")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--table", required=True, help="Sensor data DynamoDB table name")
    parser.add_argument("--alerts-table", required=True, help="Alerts DynamoDB table name")
    parser.add_argument("--client-id", required=True, help="Client ID to assign")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    dynamodb = session.resource("dynamodb")
    sensor_table = dynamodb.Table(args.table)
    alerts_table = dynamodb.Table(args.alerts_table)

    print(f"Reading CSV: {args.csv}")
    rows = parse_csv(args.csv)
    print(f"  Parsed {len(rows)} readings")

    macs = set(r["mac"] for r in rows)
    print(f"  Unique sensors: {', '.join(macs)}")

    print("Using original CSV timestamps")
    rows = prepare_timestamps(rows)

    for mac in macs:
        mac_rows = [r for r in rows if r["mac"] == mac]
        print(f"\nProcessing sensor {mac}: {len(mac_rows)} raw readings")

        aggregates = aggregate_per_minute(mac_rows)
        print(f"  Aggregated to {len(aggregates)} per-minute records")
        print(f"  Time range: {aggregates[0]['minute_key']} → {aggregates[-1]['minute_key']}")
        temps = [a["temperature"] for a in aggregates]
        print(f"  Temp range: {min(temps):.1f}°F → {max(temps):.1f}°F")

        state = build_state_record(mac, aggregates, args.client_id)
        print(f"  Writing STATE (offline, last_seen={state['last_seen']})")
        clean_state = {k: v for k, v in state.items() if v is not None}
        sensor_table.put_item(Item=clean_state)

        reading_items = build_reading_items(aggregates, mac)
        print(f"  Writing {len(reading_items)} R# reading records...")
        batch_write(sensor_table, reading_items, "readings")

        alert_items = build_alert_items(aggregates, mac, args.client_id)
        print(f"  Generated {len(alert_items)} alerts")
        for a in alert_items:
            a["sk"] = f"{a['triggered_at']}#{a['alert_type']}"
            a["ttl"] = int(time.time()) + (90 * 24 * 3600)
        if alert_items:
            batch_write(alerts_table, alert_items, "alerts")

    print("\nImport complete!")


if __name__ == "__main__":
    main()
