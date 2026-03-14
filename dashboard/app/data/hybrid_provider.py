"""Hybrid data provider — thin orchestrator.

Routes calls to mysql_reader / parquet_reader based on DATA_SOURCE flag
(or per-client registry config), applies analytics, integrates with
alert_manager.  Uses ``client_id`` consistently — never ``customer_key``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from app import config as cfg
from app.data import analytics
from app.data.alert_manager import AlertManager

logger = logging.getLogger(__name__)


class HybridProvider:
    """DataProvider backed by MySQL + optional Parquet + DynamoDB alerts."""

    def __init__(self, client_id: str):
        self._client_id = client_id

        from app.data.client_registry import get_client_config
        cc = get_client_config(client_id)

        self._data_source = (cc.data_source if cc else cfg.DATA_SOURCE).lower()
        self._pq_bucket = cc.parquet_bucket if cc else cfg.PARQUET_BUCKET
        self._pq_prefix = cc.parquet_prefix if cc else cfg.PARQUET_PREFIX

        self._thresholds = {
            "temp_high": cfg.TEMP_HIGH, "temp_low": cfg.TEMP_LOW,
            "critical_high": cfg.TEMP_CRITICAL_HIGH, "critical_low": cfg.TEMP_CRITICAL_LOW,
            "degraded_sec": cfg.ALERT_DEGRADED_THRESHOLD_SEC,
            "offline_sec": cfg.ALERT_OFFLINE_THRESHOLD_SEC,
        }
        table = (cc.alerts_table if cc else cfg.ALERTS_TABLE) or f"TempMonitor-Alerts-local-{client_id}"
        self._alerts = AlertManager(client_id, table, self._thresholds)

        self._cache: dict = {"states": None, "ts": 0, "ttl": cfg.CACHE_TTL_STATES}
        self._readings_cache: dict = {}
        self._loc_cache: dict = {}
        self._loc_ts: float = 0
        self._locations_cache: list[str] = []
        self._locations_ts: float = 0
        self._compliance_cache: dict = {"data": None, "ts": 0, "ttl": cfg.CACHE_TTL_COMPLIANCE}
        self._alerts_cache: dict = {"data": None, "ts": 0, "ttl": cfg.CACHE_TTL_ALERTS}
        self._last_reading_tracker: dict[str, dict] = {}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _cid(self) -> str | None:
        """Return client_id for SQL filtering (None when default/local = no filter)."""
        return self._client_id if self._client_id and self._client_id != "default" else None

    def _db_now(self) -> datetime:
        """Get current time from DB server — avoids timezone mismatch."""
        if self._use_mysql():
            from app.data import mysql_reader as db
            try:
                db_time = db.fetch_db_now()
                if db_time:
                    return db_time
            except Exception:
                pass
        return datetime.now()

    def _use_parquet(self) -> bool:
        return self._data_source in ("parquet", "hybrid") and bool(self._pq_bucket)

    def _use_mysql(self) -> bool:
        return self._data_source in ("mysql", "hybrid")

    def _tag_locations(self) -> dict:
        now = time.time()
        if self._loc_cache and (now - self._loc_ts) < cfg.CACHE_TTL_TAG_LOCATIONS:
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

    # ── locations + sensors ──────────────────────────────────────────────────

    def get_locations(self) -> list[str]:
        now = time.time()
        if self._locations_cache and (now - self._locations_ts) < cfg.CACHE_TTL_LOCATIONS:
            return self._locations_cache
        if not self._use_mysql():
            return []
        from app.data import mysql_reader as db
        try:
            self._locations_cache = db.fetch_distinct_locations(self._cid())
            self._locations_ts = now
        except Exception as exc:
            logger.warning("fetch_distinct_locations failed: %s", exc)
        return self._locations_cache

    def get_sensors_for_location(self, location: str | None = None) -> list[str]:
        if not self._use_mysql():
            return []
        from app.data import mysql_reader as db
        try:
            return db.fetch_sensors_by_location(self._cid(), location)
        except Exception as exc:
            logger.warning("fetch_sensors_by_location failed: %s", exc)
            return []

    # ── sensor states ───────────────────────────────────────────────────────

    def get_all_sensor_states(self) -> list[dict]:
        now_ts = time.time()
        if self._cache["states"] and (now_ts - self._cache["ts"]) < self._cache["ttl"]:
            return self._cache["states"]

        from app.data import mysql_reader as db

        db_now = self._db_now()
        latest_rows = db.fetch_latest_per_sensor(self._cid())
        if not latest_rows:
            self._cache.update(states=[], ts=now_ts)
            return []

        loc_map = self._tag_locations()
        mac_list = [r["mac"] for r in latest_rows]
        earliest = min(
            (r["date_added"] for r in latest_rows if isinstance(r["date_added"], datetime)),
            default=db_now,
        ) - timedelta(hours=1)
        hist = db.fetch_batch_history(mac_list, earliest, self._cid())

        states = []
        for row in latest_rows:
            loc = loc_map.get(row.get("tags_id"), {})
            s = analytics.build_sensor_state(
                row, hist.get(row["mac"], []), db_now, self._thresholds, self._client_id, loc,
            )
            if s:
                states.append(s)

        self._cache.update(states=states, ts=now_ts)
        return states

    # ── readings (Parquet → MySQL) ──────────────────────────────────────────

    def get_db_time(self) -> datetime:
        """Expose DB time for callers that need correct anchoring."""
        return self._db_now()

    def get_readings(self, device_id: str, since_iso: str, until_iso: str | None = None) -> list[dict]:
        since = datetime.fromisoformat(since_iso.replace("Z", ""))
        if until_iso:
            until = datetime.fromisoformat(until_iso.replace("Z", ""))
        else:
            until = self._db_now()

        cache_key = f"{device_id}|{since_iso}|{until_iso or 'now'}"
        cached = self._readings_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < cfg.CACHE_TTL_READINGS:
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
            rows = db.fetch_readings_range(device_id, since, until, client_id=self._cid())
        else:
            rows = db.fetch_readings(device_id, since, client_id=self._cid())
        out = []
        for r in rows:
            try:
                temp = float(r["body_temperature"])
            except (ValueError, TypeError):
                continue
            ts = r["date_added"]
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(ts, datetime) else str(ts)
            out.append({"timestamp": ts_str, "temperature": temp})
        return out

    # ── forecast ────────────────────────────────────────────────────────────

    def get_forecast(self, device_id: str, horizon: str) -> dict | None:
        from app.data import mysql_reader as db
        ref = db.fetch_max_date(device_id, client_id=self._cid())
        if not ref or not isinstance(ref, datetime):
            return None
        readings = self.get_readings(device_id, (ref - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"))
        params = analytics.forecast_params(readings)
        if not params:
            return None
        return analytics.forecast_point(params, horizon)

    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]:
        fc = self.get_forecast(device_id, horizon)
        if not fc or "model_params" not in fc:
            return []
        from app.data import mysql_reader as db
        ref = db.fetch_max_date(device_id, client_id=self._cid())
        ref_dt = ref if isinstance(ref, datetime) else self._db_now()
        return analytics.forecast_series(fc["model_params"], ref_dt, steps)

    # ── compliance (Parquet for past days, MySQL for today) ─────────────────

    def get_compliance_history(self, days: int) -> list[dict]:
        now_ts = time.time()
        cc = self._compliance_cache
        if cc["data"] is not None and (now_ts - cc["ts"]) < cc["ttl"]:
            return cc["data"]

        db_now = self._db_now()
        start = db_now - timedelta(days=days)

        history: list[dict] = []
        if self._use_parquet():
            from app.data import parquet_reader as pq
            history = pq.compliance_for_range(
                self._pq_bucket, self._pq_prefix, start, db_now, cfg.TEMP_LOW, cfg.TEMP_HIGH,
            )

        if not history and self._use_mysql():
            from app.data import mysql_reader as db
            rows = db.fetch_compliance_batch(
                start.strftime("%Y-%m-%d 00:00:00"), db_now.strftime("%Y-%m-%d 23:59:59"),
                cfg.TEMP_LOW, cfg.TEMP_HIGH, self._cid(),
            )
            for r in rows:
                total = int(r["total"])
                comp = int(r["compliant"])
                day = r["day"]
                history.append({
                    "date": day.isoformat() if hasattr(day, "isoformat") else str(day),
                    "compliance_pct": round(comp / total * 100, 1) if total else 0.0,
                })

        seen: set[str] = set()
        deduped: list[dict] = []
        for h in history:
            if h["date"] not in seen:
                seen.add(h["date"])
                deduped.append(h)
        by_date = {h["date"]: h for h in deduped}

        filled: list[dict] = []
        cursor = start.date() if hasattr(start, "date") else start
        end_d = db_now.date() if hasattr(db_now, "date") else db_now
        one_day = timedelta(days=1)
        while cursor <= end_d:
            ds = cursor.isoformat()
            filled.append(by_date.get(ds, {"date": ds, "compliance_pct": 0.0}))
            cursor += one_day

        cc.update(data=filled, ts=now_ts)
        return filled

    # ── devices ─────────────────────────────────────────────────────────────

    def get_all_devices(self) -> list[str]:
        from app.data import mysql_reader as db
        return db.fetch_all_devices(self._cid())

    def get_zones(self) -> list[str]:
        loc = self._tag_locations()
        return sorted({v["zone_id"] for v in loc.values()})

    # ── alerts (delegate to AlertManager) ───────────────────────────────────

    def get_live_alerts(self) -> list[dict]:
        now = time.time()
        ac = self._alerts_cache
        if ac["data"] is not None and (now - ac["ts"]) < ac["ttl"]:
            return ac["data"]
        states = self.get_all_sensor_states()
        result = self._alerts.evaluate(states, now_dt=self._db_now())
        ac.update(data=result, ts=now)
        return result

    def get_alert_history(self, device_id: Optional[str] = None, days: int = 7) -> list[dict]:
        return self._alerts.get_history(device_id, days)

    def dismiss_alert(self, device_id: str, alert_type: str) -> None:
        self._alerts.dismiss(device_id, alert_type)
        self._alerts_cache["data"] = None

    def send_alert_note(self, device_id: str, alert_type: str, context: dict) -> bool:
        result = self._alerts.send_note_and_dismiss(device_id, alert_type, context)
        self._alerts_cache["data"] = None
        return result
