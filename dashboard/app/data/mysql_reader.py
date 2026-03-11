"""MySQL reader — connection pool + all SQL for dg_gateway_data.

Thread-local connections with auto-retry.  No analytics, no caching logic.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_tls = threading.local()
_MAX_CONN_AGE = 50


def _new_conn():
    import pymysql
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "Demo_aurora"),
        connect_timeout=5, read_timeout=15, write_timeout=10,
        autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )


def _conn():
    c = getattr(_tls, "c", None)
    ts = getattr(_tls, "ts", 0)
    if c is not None and (time.time() - ts) < _MAX_CONN_AGE:
        return c
    _close()
    c = _new_conn()
    _tls.c, _tls.ts = c, time.time()
    return c


def _close():
    c = getattr(_tls, "c", None)
    _tls.c, _tls.ts = None, 0
    if c:
        try:
            c.close()
        except Exception:
            pass


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute SQL with one retry on broken connection."""
    c = _conn()
    try:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:
        _close()
        c = _conn()
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def query_one(sql: str, params: tuple = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def warmup():
    query("SELECT 1")
    logger.info("MySQL connection warmed up")


# ── Sensor queries ──────────────────────────────────────────────────────────

def fetch_latest_per_sensor() -> list[dict]:
    """Latest reading per Temp-Sensor MAC (de-duplicated)."""
    rows = query("""
        SELECT g.mac, g.body_temperature, g.rssi, g.power,
               g.date_added, g.tags_id, g.gateway_mac
        FROM dg_gateway_data g
        INNER JOIN (
            SELECT mac, MAX(date_added) AS max_da
            FROM dg_gateway_data WHERE mac_type='Temp-Sensor' GROUP BY mac
        ) latest ON g.mac = latest.mac AND g.date_added = latest.max_da
        WHERE g.mac_type='Temp-Sensor'
    """)
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r["mac"] not in seen:
            seen.add(r["mac"])
            out.append(r)
    return out


def fetch_batch_history(mac_list: list[str], since: datetime) -> dict[str, list[dict]]:
    """Readings for multiple MACs since cutoff, grouped by MAC."""
    if not mac_list:
        return {}
    ph = ",".join(["%s"] * len(mac_list))
    rows = query(
        f"""SELECT mac, body_temperature, date_added
            FROM dg_gateway_data
            WHERE mac IN ({ph}) AND mac_type='Temp-Sensor' AND date_added >= %s
            ORDER BY mac, date_added DESC""",
        (*mac_list, since),
    )
    by_mac: dict[str, list[dict]] = {}
    for r in rows:
        by_mac.setdefault(r["mac"], []).append(r)
    return by_mac


def fetch_readings(device_id: str, since: datetime) -> list[dict]:
    """Ordered readings for a single device."""
    return query(
        """SELECT date_added, body_temperature FROM dg_gateway_data
           WHERE mac=%s AND mac_type='Temp-Sensor' AND date_added >= %s
           ORDER BY date_added ASC""",
        (device_id, since.strftime("%Y-%m-%d %H:%M:%S")),
    )


def fetch_readings_range(device_id: str, start: datetime, end: datetime, limit: int = 3000) -> list[dict]:
    """Bounded query for historical ranges — caps response size."""
    return query(
        """SELECT date_added, body_temperature FROM dg_gateway_data
           WHERE mac=%s AND mac_type='Temp-Sensor'
                 AND date_added BETWEEN %s AND %s
           ORDER BY date_added ASC LIMIT %s""",
        (device_id, start.strftime("%Y-%m-%d %H:%M:%S"),
         end.strftime("%Y-%m-%d %H:%M:%S"), limit),
    )


def fetch_max_date(device_id: str) -> Optional[datetime]:
    row = query_one(
        "SELECT MAX(date_added) AS latest FROM dg_gateway_data WHERE mac=%s AND mac_type='Temp-Sensor'",
        (device_id,),
    )
    return row["latest"] if row and row["latest"] else None


def fetch_all_devices() -> list[str]:
    return [r["mac"] for r in query("SELECT DISTINCT mac FROM dg_gateway_data WHERE mac_type='Temp-Sensor'")]


def fetch_locations() -> list[dict]:
    return query("""
        SELECT t.tags_id, t.locations_id, t.facilities_id,
               l.location_name, l.location_address
        FROM dg_tags t
        LEFT JOIN dg_locations l ON t.locations_id = l.locations_id
        WHERE t.facilities_id IS NOT NULL
    """)


def fetch_compliance_batch(start: str, end: str, temp_low: float, temp_high: float) -> list[dict]:
    """Compliance per day in one query."""
    return query(
        """SELECT DATE(date_added) AS day, COUNT(*) AS total,
                  SUM(CASE WHEN body_temperature BETWEEN %s AND %s THEN 1 ELSE 0 END) AS compliant
           FROM dg_gateway_data
           WHERE mac_type='Temp-Sensor' AND date_added BETWEEN %s AND %s
           GROUP BY DATE(date_added) ORDER BY day ASC""",
        (temp_low, temp_high, start, end),
    )
