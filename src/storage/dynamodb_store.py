"""DynamoDB storage operations for sensor data.

Tables and single-table design for sensor_data:
  PK: device_id   SK: "STATE"               → current sensor state
  PK: device_id   SK: "R#<ISO timestamp>"    → 1-minute aggregate reading (TTL)
  PK: device_id   SK: "F#<horizon>"          → forecast for a horizon
"""

import json
import logging
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from config import settings

logger = logging.getLogger(__name__)

_tables = {}


def _get_table(table_name: str):
    if table_name not in _tables:
        dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
        _tables[table_name] = dynamodb.Table(table_name)
    return _tables[table_name]


def _sensor_table():
    return _get_table(settings.SENSOR_DATA_TABLE)


def _alerts_table():
    return _get_table(settings.ALERTS_TABLE)


def _decimal(value):
    if value is None:
        return None
    return Decimal(str(round(value, 6)))


# ── Sensor State ──────────────────────────────────────────


def get_sensor_state(device_id: str) -> dict | None:
    resp = _sensor_table().get_item(Key={"pk": device_id, "sk": "STATE"})
    return resp.get("Item")


def update_sensor_state(device_id: str, state: dict):
    expr_parts, names, values = [], {}, {}
    for key, value in state.items():
        if key in ("pk", "sk"):
            continue
        safe = f"#{key}"
        names[safe] = key
        values[f":{key}"] = _decimal(value) if isinstance(value, float) else value
        expr_parts.append(f"{safe} = :{key}")

    if not expr_parts:
        return
    _sensor_table().update_item(
        Key={"pk": device_id, "sk": "STATE"},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def get_all_sensor_states() -> list[dict]:
    table = _sensor_table()
    items = []
    resp = table.scan(FilterExpression=Key("sk").eq("STATE"))
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            FilterExpression=Key("sk").eq("STATE"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


# ── Readings ──────────────────────────────────────────────


def put_reading(device_id: str, timestamp_iso: str, reading: dict):
    ttl = int(time.time()) + (settings.READINGS_RETENTION_HOURS * 3600)
    item = {"pk": device_id, "sk": f"R#{timestamp_iso}", "ttl": ttl}
    for k, v in reading.items():
        item[k] = _decimal(v) if isinstance(v, float) else v
    _sensor_table().put_item(Item=item)


def get_readings(device_id: str, since_iso: str) -> list[dict]:
    resp = _sensor_table().query(
        KeyConditionExpression=(
            Key("pk").eq(device_id) & Key("sk").between(f"R#{since_iso}", "R#~")
        ),
    )
    return resp.get("Items", [])


# ── Forecasts ─────────────────────────────────────────────


def put_forecast(device_id: str, horizon: str, forecast: dict):
    item = {"pk": device_id, "sk": f"F#{horizon}"}
    for k, v in forecast.items():
        if isinstance(v, float):
            item[k] = _decimal(v)
        elif isinstance(v, dict):
            item[k] = json.loads(json.dumps(v), parse_float=Decimal)
        else:
            item[k] = v
    _sensor_table().put_item(Item=item)


def get_forecast(device_id: str, horizon: str) -> dict | None:
    resp = _sensor_table().get_item(Key={"pk": device_id, "sk": f"F#{horizon}"})
    return resp.get("Item")


# ── Alerts ────────────────────────────────────────────────


def put_alert(facility_zone: str, alert: dict):
    ts_type = f"{alert['triggered_at']}#{alert['alert_type']}"
    ttl = int(time.time()) + (90 * 24 * 3600)
    item = {"pk": facility_zone, "sk": ts_type, "ttl": ttl}
    for k, v in alert.items():
        if isinstance(v, float):
            item[k] = _decimal(v)
        elif isinstance(v, (list, dict)):
            item[k] = json.loads(json.dumps(v), parse_float=Decimal)
        else:
            item[k] = v
    _alerts_table().put_item(Item=item)


def get_active_alerts(facility_zone: str | None = None) -> list[dict]:
    table = _alerts_table()
    filter_expr = "#s = :active"
    expr_names = {"#s": "status"}
    expr_values = {":active": "ACTIVE"}

    items = []
    if facility_zone:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(facility_zone),
            FilterExpression=filter_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(facility_zone),
                FilterExpression=filter_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
    else:
        resp = table.scan(
            FilterExpression=filter_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.scan(
                FilterExpression=filter_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
    return items


def update_alert_status(facility_zone: str, sk: str, status: str, **extra):
    expr_parts = ["#s = :status"]
    names = {"#s": "status"}
    values = {":status": status}
    for k, v in extra.items():
        expr_parts.append(f"#{k} = :{k}")
        names[f"#{k}"] = k
        values[f":{k}"] = v
    _alerts_table().update_item(
        Key={"pk": facility_zone, "sk": sk},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def reset():
    """Clear cached table references. Called in tests."""
    _tables.clear()
