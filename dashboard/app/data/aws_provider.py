"""AWS data provider — reads from real DynamoDB and S3, scoped by client_id.

Uses the client-index GSI for efficient per-client queries instead of table scans.
"""

import json
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from app import config as cfg


def _paginated_query(table, **kwargs) -> list[dict]:
    """Execute a DynamoDB query with automatic pagination."""
    items = []
    resp = table.query(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


def _paginated_scan(table, **kwargs) -> list[dict]:
    """Execute a DynamoDB scan with automatic pagination."""
    items = []
    resp = table.scan(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


class AWSProvider:
    def __init__(self, client_id: str):
        self._client_id = client_id
        dynamodb = boto3.resource("dynamodb", region_name=cfg.AWS_REGION)
        self._config_table = dynamodb.Table(cfg.PLATFORM_CONFIG_TABLE)
        self._sensor_table = dynamodb.Table(cfg.SENSOR_DATA_TABLE)
        self._alerts_table = dynamodb.Table(cfg.ALERTS_TABLE)
        self._s3 = boto3.client("s3", region_name=cfg.AWS_REGION)

    def get_zones(self) -> list[str]:
        items = _paginated_scan(
            self._config_table,
            FilterExpression=Key("sk").eq("META") & Key("client_id").eq(self._client_id),
            ProjectionExpression="zone_id, client_id",
        )
        return list({item["zone_id"] for item in items if "zone_id" in item})

    def get_all_devices(self) -> list[str]:
        items = _paginated_query(
            self._sensor_table,
            IndexName="client-index",
            KeyConditionExpression=Key("client_id").eq(self._client_id) & Key("sk").eq("STATE"),
            ProjectionExpression="pk",
        )
        return [item["pk"] for item in items]

    def get_devices_in_zone(self, zone_id: str) -> list[str]:
        items = _paginated_query(
            self._config_table,
            IndexName="zone-index",
            KeyConditionExpression=Key("zone_id").eq(zone_id),
        )
        return [item["pk"].split("#", 1)[1] for item in items]

    def get_all_sensor_states(self) -> list[dict]:
        items = _paginated_query(
            self._sensor_table,
            IndexName="client-index",
            KeyConditionExpression=Key("client_id").eq(self._client_id) & Key("sk").eq("STATE"),
        )
        for item in items:
            item["device_id"] = item["pk"]
            for k in ("last_temp", "rolling_avg_10m", "rolling_avg_1h", "rolling_std_1h",
                      "rate_of_change_10m", "rate_of_change", "actual_high_1h", "actual_low_1h"):
                if k in item and item[k] is not None:
                    item[k] = float(item[k])
            for k in ("battery_pct", "signal_dbm"):
                if k in item and item[k] is not None:
                    item[k] = float(item[k])
            temp = item.get("last_temp") or 0
            if isinstance(temp, str):
                temp = float(temp)
            defaults = {
                "temperature": temp,
                "actual_high_1h": temp,
                "actual_low_1h": temp,
                "rate_of_change": 0.0,
                "rate_of_change_10m": 0.0,
                "battery_pct": 100,
                "signal_dbm": -50,
                "signal_label": "Good",
                "anomaly": False,
                "anomaly_reason": None,
                "status": "online",
                "zone_id": "default",
            }
            for field, fallback in defaults.items():
                if item.get(field) is None:
                    item[field] = fallback
        return items

    def get_readings(self, device_id: str, since_iso: str) -> list[dict]:
        items = _paginated_query(
            self._sensor_table,
            KeyConditionExpression=Key("pk").eq(device_id) & Key("sk").between(f"R#{since_iso}", "R#~"),
        )
        for item in items:
            item["timestamp"] = item["sk"].split("#", 1)[1]
            item["temperature"] = float(item.get("temperature", 0))
        return items

    def get_active_alerts(self, facility_zone: str | None = None) -> list[dict]:
        return _paginated_query(
            self._alerts_table,
            IndexName="client-index",
            KeyConditionExpression=Key("client_id").eq(self._client_id),
            FilterExpression="#s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":active": "ACTIVE"},
        )

    def get_all_alerts(self) -> list[dict]:
        return _paginated_query(
            self._alerts_table,
            IndexName="client-index",
            KeyConditionExpression=Key("client_id").eq(self._client_id),
        )

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        resp = self._sensor_table.get_item(Key={"pk": device_id, "sk": f"F#{horizon}"})
        item = resp.get("Item")
        if item:
            for k in ("predicted_temp", "ci_lower", "ci_upper", "peak_temp", "min_temp"):
                if k in item:
                    item[k] = float(item[k])
        return item

    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]:
        fc = self.get_forecast(device_id, horizon)
        if not fc or "model_params" not in fc:
            return []
        params = fc["model_params"]
        level = float(params.get("level", 0))
        trend = float(params.get("trend", 0))
        std = float(params.get("residual_std", 0))
        now = datetime.now(timezone.utc)
        series = []
        for h in range(1, steps + 1):
            pred = level + h * trend
            ci = 1.96 * std * (h ** 0.5) * 0.1
            series.append({
                "step": h,
                "timestamp": (now + timedelta(minutes=h)).strftime("%Y-%m-%dT%H:%M:00Z"),
                "predicted": round(pred, 2),
                "ci_lower": round(pred - ci, 2),
                "ci_upper": round(pred + ci, 2),
            })
        return series

    def get_compliance_report(self, date_str: str) -> dict | None:
        key = f"{cfg.ENVIRONMENT}/reports/{self._client_id}/{date_str}_compliance.json"
        try:
            resp = self._s3.get_object(Bucket=cfg.DATA_BUCKET, Key=key)
            return json.loads(resp["Body"].read())
        except Exception:
            return None

    def get_compliance_history(self, days: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        history = []
        for d in range(days, 0, -1):
            dt = now - timedelta(days=d)
            report = self.get_compliance_report(dt.strftime("%Y-%m-%d"))
            if report:
                history.append({"date": dt.strftime("%Y-%m-%d"), "compliance_pct": report.get("overall_compliance_pct", 0)})
        return history
