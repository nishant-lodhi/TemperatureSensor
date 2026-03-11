"""Hybrid data provider — thin orchestrator.

Routes calls to mysql_reader / parquet_reader based on DATA_SOURCE flag,
applies analytics, integrates with alert_manager.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.data import analytics
from app.data.alert_manager import AlertManager

logger = logging.getLogger(__name__)


class HybridProvider:
    """DataProvider backed by MySQL + optional Parquet + DynamoDB alerts."""

    def __init__(self, client_id: str):
        self._client_id = client_id
        self._data_source = os.environ.get("DATA_SOURCE", "mysql").lower()
        self._pq_bucket = os.environ.get("PARQUET_BUCKET", "")
        self._pq_prefix = os.environ.get("PARQUET_PREFIX", "sensor-data/")

        from app import config as cfg
        self._thresholds = {
            "temp_high": cfg.TEMP_HIGH, "temp_low": cfg.TEMP_LOW,
            "critical_high": cfg.TEMP_CRITICAL_HIGH, "critical_low": cfg.TEMP_CRITICAL_LOW,
            "degraded_sec": cfg.ALERT_DEGRADED_THRESHOLD_SEC,
            "offline_sec": cfg.ALERT_OFFLINE_THRESHOLD_SEC,
        }
        table = os.environ.get("ALERTS_TABLE", "") or f"TempMonitor-Alerts-local-{client_id}"
        self._alerts = AlertManager(client_id, table, self._thresholds)

        self._cache: dict = {"states": None, "ts": 0, "ttl": 20}
        self._readings_cache: dict = {}
        self._loc_cache: dict = {}
        self._loc_ts: float = 0

    # ── helpers ──────────────────────────────────────────────────────────────

    def _use_parquet(self) -> bool:
        return self._data_source in ("parquet", "hybrid") and bool(self._pq_bucket)

    def _use_mysql(self) -> bool:
        return self._data_source in ("mysql", "hybrid")

    def _locations(self) -> dict:
        now = time.time()
        if self._loc_cache and (now - self._loc_ts) < 300:
            return self._loc_cache
        if not self._use_mysql():
            return {}
        try:
            from app.data import mysql_reader as db
            rows = db.fetch_locations()
            self._loc_cache = {
                r["tags_id"]: {
                    "zone_id": str(r.get("locations_id") or r["tags_id"]),
                    "zone_label": r.get("location_name") or f"Zone {r['tags_id']}",
                    "facility_id": str(r.get("facilities_id") or "unknown"),
                }
                for r in rows
            }
            self._loc_ts = now
        except Exception as exc:
            logger.warning("Location load failed: %s", exc)
        return self._loc_cache

    # ── sensor states ───────────────────────────────────────────────────────

    def get_all_sensor_states(self) -> list[dict]:
        now_ts = time.time()
        if self._cache["states"] and (now_ts - self._cache["ts"]) < self._cache["ttl"]:
            return self._cache["states"]

        from app.data import mysql_reader as db

        now = datetime.now(timezone.utc)
        latest_rows = db.fetch_latest_per_sensor()
        if not latest_rows:
            self._cache.update(states=[], ts=now_ts)
            return []

        loc_map = self._locations()
        mac_list = [r["mac"] for r in latest_rows]
        earliest = min(
            (r["date_added"] for r in latest_rows if isinstance(r["date_added"], datetime)),
            default=now,
        ) - timedelta(hours=1)
        hist = db.fetch_batch_history(mac_list, earliest)

        states = []
        for row in latest_rows:
            loc = loc_map.get(row.get("tags_id"), {})
            s = analytics.build_sensor_state(
                row, hist.get(row["mac"], []), now, self._thresholds, self._client_id, loc,
            )
            if s:
                states.append(s)

        self._cache.update(states=states, ts=now_ts)
        return states

    # ── readings (Parquet → MySQL) ──────────────────────────────────────────

    def get_readings(self, device_id: str, since_iso: str, until_iso: str | None = None) -> list[dict]:
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        until = datetime.fromisoformat(until_iso.replace("Z", "+00:00")) if until_iso else now

        cache_key = f"{device_id}|{since_iso}|{until_iso or 'now'}"
        cached = self._readings_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < 60:
            return cached["data"]

        readings: list[dict] = []
        if self._use_parquet():
            from app.data import parquet_reader as pq
            readings = pq.readings_for_device(self._pq_bucket, self._pq_prefix, device_id, since, until)

        if not readings and self._use_mysql():
            readings = self._mysql_readings(device_id, since, until)

        if readings:
            self._readings_cache[cache_key] = {"data": readings, "ts": time.time()}
        return readings

    def _mysql_readings(self, device_id: str, since: datetime, until: datetime | None = None) -> list[dict]:
        from app.data import mysql_reader as db
        if until and until != since:
            rows = db.fetch_readings_range(device_id, since, until)
        else:
            rows = db.fetch_readings(device_id, since)
        out = []
        for r in rows:
            try:
                temp = float(r["body_temperature"])
            except (ValueError, TypeError):
                continue
            ts = r["date_added"]
            ts_str = ts.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ts, datetime) else str(ts)
            out.append({"timestamp": ts_str, "temperature": temp})
        return out

    # ── forecast ────────────────────────────────────────────────────────────

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        from app.data import mysql_reader as db
        ref = db.fetch_max_date(device_id)
        if not ref:
            return None
        ref_utc = ref.replace(tzinfo=timezone.utc) if isinstance(ref, datetime) else None
        if not ref_utc:
            return None
        readings = self.get_readings(device_id, (ref_utc - timedelta(minutes=30)).isoformat())
        params = analytics.forecast_params(readings)
        if not params:
            return None
        return analytics.forecast_point(params, horizon)

    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]:
        fc = self.get_forecast(device_id, horizon)
        if not fc or "model_params" not in fc:
            return []
        from app.data import mysql_reader as db
        ref = db.fetch_max_date(device_id)
        ref_utc = ref.replace(tzinfo=timezone.utc) if isinstance(ref, datetime) and ref else datetime.now(timezone.utc)
        return analytics.forecast_series(fc["model_params"], ref_utc, steps)

    # ── compliance (Parquet for past days, MySQL for today) ─────────────────

    def get_compliance_history(self, days: int) -> list[dict]:
        from app import config as cfg
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        history: list[dict] = []
        if self._use_parquet():
            from app.data import parquet_reader as pq
            history = pq.compliance_for_range(
                self._pq_bucket, self._pq_prefix, start, now, cfg.TEMP_LOW, cfg.TEMP_HIGH,
            )

        if not history and self._use_mysql():
            from app.data import mysql_reader as db
            rows = db.fetch_compliance_batch(
                start.strftime("%Y-%m-%d 00:00:00"), now.strftime("%Y-%m-%d 23:59:59"),
                cfg.TEMP_LOW, cfg.TEMP_HIGH,
            )
            for r in rows:
                total = int(r["total"])
                comp = int(r["compliant"])
                day = r["day"]
                history.append({
                    "date": day.isoformat() if hasattr(day, "isoformat") else str(day),
                    "compliance_pct": round(comp / total * 100, 1) if total else 0.0,
                })

        return history

    # ── devices ─────────────────────────────────────────────────────────────

    def get_all_devices(self) -> list[str]:
        from app.data import mysql_reader as db
        return db.fetch_all_devices()

    def get_zones(self) -> list[str]:
        loc = self._locations()
        return sorted({v["zone_id"] for v in loc.values()})

    # ── alerts (delegate to AlertManager) ───────────────────────────────────

    def get_live_alerts(self) -> list[dict]:
        states = self.get_all_sensor_states()
        return self._alerts.evaluate(states)

    def get_alert_history(self, device_id: Optional[str] = None, days: int = 7) -> list[dict]:
        return self._alerts.get_history(device_id, days)

    def dismiss_alert(self, device_id: str, alert_type: str) -> None:
        self._alerts.dismiss(device_id, alert_type)

    def send_alert_note(self, device_id: str, alert_type: str, context: dict) -> bool:
        return self._alerts.send_note_and_dismiss(device_id, alert_type, context)
