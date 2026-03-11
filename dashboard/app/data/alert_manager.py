"""Alert manager — stateful lifecycle with DynamoDB persistence.

States: ACTIVE → auto-RESOLVED | officer-DISMISSED
In local mode (no ALERTS_TABLE env var): uses moto-backed DynamoDB in-process.
Same code path everywhere — no conditional branching.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TABLE_SCHEMA = {
    "TableName": "",
    "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "client_id", "AttributeType": "S"}, {"AttributeName": "state_triggered", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [{
        "IndexName": "ClientActiveAlerts",
        "KeySchema": [{"AttributeName": "client_id", "KeyType": "HASH"}, {"AttributeName": "state_triggered", "KeyType": "RANGE"}],
        "Projection": {"ProjectionType": "ALL"},
    }],
    "BillingMode": "PAY_PER_REQUEST",
}

_moto_mock = None


def _ensure_table(table_name: str):
    """Create DynamoDB table via moto when running locally."""
    global _moto_mock
    if os.environ.get("AWS_MODE", "false").lower() == "true":
        return
    if _moto_mock is not None:
        return
    from moto import mock_aws
    _moto_mock = mock_aws()
    _moto_mock.start()
    import boto3
    ddb = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    schema = {**_TABLE_SCHEMA, "TableName": table_name}
    try:
        ddb.create_table(**schema)
        logger.info("Local moto DynamoDB table '%s' created", table_name)
    except ddb.exceptions.ResourceInUseException:
        pass


class AlertManager:
    """Evaluates sensor states, manages alert lifecycle in DynamoDB."""

    ALERT_CONDITIONS = [
        ("EXTREME_TEMPERATURE", "CRITICAL", lambda s, c: s["temperature"] > c["critical_high"]),
        ("EXTREME_TEMPERATURE_LOW", "CRITICAL", lambda s, c: s["temperature"] < c["critical_low"]),
        ("SUSTAINED_HIGH", "HIGH", lambda s, c: c["critical_high"] >= s["temperature"] > c["temp_high"]),
        ("LOW_TEMPERATURE", "MEDIUM", lambda s, c: c["critical_low"] <= s["temperature"] < c["temp_low"]),
        ("SENSOR_OFFLINE", "HIGH", lambda s, _: s["status"] == "offline"),
        ("RAPID_CHANGE", "MEDIUM", lambda s, _: abs(s.get("rate_of_change", 0)) > 4.0),
    ]

    def __init__(self, client_id: str, table_name: str, thresholds: dict):
        self._client_id = client_id
        self._table_name = table_name
        self._thresholds = thresholds
        self._cooldowns: dict[str, float] = {}
        self._memory: dict[str, dict] = {}
        self._resolved: list[dict] = []

        _ensure_table(table_name)
        import boto3
        self._table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"),
        ).Table(table_name)
        self._load_active()

    def _pk(self, device_id: str, alert_type: str) -> str:
        return f"ALERT#{device_id}#{alert_type}"

    def _load_active(self):
        """Hydrate memory from DynamoDB on cold start."""
        try:
            resp = self._table.query(
                IndexName="ClientActiveAlerts",
                KeyConditionExpression="client_id = :cid AND begins_with(state_triggered, :prefix)",
                ExpressionAttributeValues={":cid": self._client_id, ":prefix": "ACTIVE#"},
            )
            for item in resp.get("Items", []):
                self._memory[item["PK"]] = item
            logger.info("Loaded %d active alerts from DynamoDB", len(self._memory))
        except Exception as exc:
            logger.warning("Failed to load alerts from DynamoDB: %s", exc)

    def evaluate(self, sensor_states: list[dict]) -> list[dict]:
        """Check all conditions, create/resolve alerts. Returns live alerts."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        for state in sensor_states:
            did = state["device_id"]
            for atype, severity, condition_fn in self.ALERT_CONDITIONS:
                pk = self._pk(did, atype)
                try:
                    triggered = condition_fn(state, self._thresholds)
                except Exception:
                    triggered = False

                if triggered:
                    if pk not in self._memory:
                        if self._in_cooldown(pk):
                            continue
                        self._create_alert(pk, did, atype, severity, state, now_iso)
                else:
                    if pk in self._memory and self._memory[pk].get("state") == "ACTIVE":
                        self._resolve_alert(pk, now_iso)

        return self.get_live_alerts()

    def _in_cooldown(self, pk: str) -> bool:
        cd = self._cooldowns.get(pk, 0)
        cooldown_sec = int(os.environ.get("ALERT_COOLDOWN_SEC", "300"))
        return (time.time() - cd) < cooldown_sec

    def _create_alert(self, pk: str, device_id: str, alert_type: str,
                      severity: str, state: dict, now_iso: str):
        msg = self._build_message(alert_type, state)
        item = {
            "PK": pk, "SK": now_iso, "device_id": device_id,
            "alert_type": alert_type, "severity": severity,
            "message": msg, "temperature": str(state.get("temperature", 0)),
            "triggered_at": now_iso, "state": "ACTIVE",
            "state_triggered": f"ACTIVE#{now_iso}",
            "facility_id": state.get("facility_id", ""),
            "client_id": self._client_id,
            "TTL": int(time.time()) + 90 * 86400,
        }
        self._memory[pk] = item
        try:
            self._table.put_item(Item=item)
        except Exception as exc:
            logger.warning("DynamoDB put_item failed: %s", exc)

    def _resolve_alert(self, pk: str, now_iso: str):
        alert = self._memory.pop(pk, None)
        if not alert:
            return
        alert_copy = {**alert, "state": "RESOLVED", "resolved_at": now_iso}
        self._resolved.append(alert_copy)
        try:
            self._table.update_item(
                Key={"PK": pk, "SK": alert["SK"]},
                UpdateExpression="SET #st = :res, resolved_at = :now, state_triggered = :st",
                ExpressionAttributeNames={"#st": "state"},
                ExpressionAttributeValues={":res": "RESOLVED", ":now": now_iso, ":st": f"RESOLVED#{now_iso}"},
            )
        except Exception as exc:
            logger.warning("DynamoDB resolve failed: %s", exc)

    def _build_message(self, alert_type: str, state: dict) -> str:
        t = state.get("temperature", 0)
        did_short = state["device_id"][-8:]
        msgs = {
            "EXTREME_TEMPERATURE": f"Temperature {t:.1f}\u00b0F \u2014 exceeds safe limit",
            "EXTREME_TEMPERATURE_LOW": f"Temperature {t:.1f}\u00b0F \u2014 below safe limit",
            "SUSTAINED_HIGH": f"Temperature {t:.1f}\u00b0F \u2014 above normal range",
            "LOW_TEMPERATURE": f"Temperature {t:.1f}\u00b0F \u2014 below normal range",
            "SENSOR_OFFLINE": f"Sensor {did_short} not responding",
            "RAPID_CHANGE": f"Temperature changed {abs(state.get('rate_of_change', 0)):.1f}\u00b0F in 10 min",
        }
        return msgs.get(alert_type, f"Alert on {did_short}")

    # ── Officer actions ─────────────────────────────────────────────────────

    def dismiss(self, device_id: str, alert_type: str):
        """Officer removes alert from live screen."""
        pk = self._pk(device_id, alert_type)
        alert = self._memory.pop(pk, None)
        self._cooldowns[pk] = time.time()
        if alert:
            alert_copy = {**alert, "state": "DISMISSED", "resolved_at": datetime.now(timezone.utc).isoformat()}
            self._resolved.append(alert_copy)
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                self._table.update_item(
                    Key={"PK": pk, "SK": alert["SK"]},
                    UpdateExpression="SET #st = :dis, resolved_at = :now, state_triggered = :st",
                    ExpressionAttributeNames={"#st": "state"},
                    ExpressionAttributeValues={":dis": "DISMISSED", ":now": now_iso, ":st": f"DISMISSED#{now_iso}"},
                )
            except Exception as exc:
                logger.warning("DynamoDB dismiss failed: %s", exc)

    def send_note_and_dismiss(self, device_id: str, alert_type: str, context: dict) -> bool:
        """Send note to Lambda X then auto-dismiss. Returns True on success."""
        arn = os.environ.get("NOTE_LAMBDA_ARN", "")
        if arn:
            try:
                import boto3
                boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-east-1")).invoke(
                    FunctionName=arn, InvocationType="Event",
                    Payload=json.dumps(context),
                )
            except Exception as exc:
                logger.warning("Lambda invoke for note failed: %s", exc)
        else:
            logger.info("NOTE_LAMBDA_ARN not set — note logged locally: %s", device_id)
        self.dismiss(device_id, alert_type)
        return True

    # ── Reads ───────────────────────────────────────────────────────────────

    def get_live_alerts(self) -> list[dict]:
        return sorted(self._memory.values(), key=lambda a: a.get("triggered_at", ""), reverse=True)

    def get_history(self, device_id: Optional[str] = None, days: int = 7) -> list[dict]:
        """All alerts: query GSI filtered by device_id, plus in-memory resolved."""
        db_alerts: list[dict] = []
        try:
            resp = self._table.query(
                IndexName="ClientActiveAlerts",
                KeyConditionExpression="client_id = :cid",
                ExpressionAttributeValues={":cid": self._client_id},
                ScanIndexForward=False, Limit=200,
            )
            db_alerts = resp.get("Items", [])
        except Exception as exc:
            logger.warning("DynamoDB history query failed: %s", exc)

        all_alerts = {a["PK"] + a.get("SK", ""): a for a in self._resolved}
        for a in db_alerts:
            key = a["PK"] + a.get("SK", "")
            if key not in all_alerts:
                all_alerts[key] = a
        for a in self._memory.values():
            key = a["PK"] + a.get("SK", "")
            if key not in all_alerts:
                all_alerts[key] = a

        result = list(all_alerts.values())
        if device_id:
            result = [a for a in result if a.get("device_id") == device_id]
        result.sort(key=lambda a: a.get("triggered_at", ""), reverse=True)
        return result[:100]
