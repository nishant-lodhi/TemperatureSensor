"""MySQL reader — per-client connection pool + all SQL for dg_gateway_data.

Thread-local connections with auto-retry, keyed by client_id so that
isolated-DB clients get their own connection while shared-DB clients
reuse one pool.  The DB column ``customer_key`` is referenced only in
``_client_clause()``; everywhere else the code says ``client_id``.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from app import config as cfg

logger = logging.getLogger(__name__)

_tls = threading.local()


# ── Per-client connection management ─────────────────────────────────────────

def _new_conn_for_client(client_id: str | None = None):
    """Create a pymysql connection using registry config for *client_id*."""
    import pymysql

    from app.data.client_registry import get_client_config

    cc = get_client_config(client_id) if client_id else None
    if cc:
        return pymysql.connect(
            host=cc.db_host, port=cc.db_port, user=cc.db_user,
            password=cc.db_password, database=cc.db_database,
            connect_timeout=cc.db_connect_timeout,
            read_timeout=cc.db_read_timeout,
            write_timeout=cc.db_write_timeout,
            autocommit=True, cursorclass=pymysql.cursors.DictCursor,
        )
    return pymysql.connect(
        host=cfg.MYSQL_HOST, port=cfg.MYSQL_PORT,
        user=cfg.MYSQL_USER, password=cfg.MYSQL_PASSWORD,
        database=cfg.MYSQL_DATABASE,
        connect_timeout=cfg.MYSQL_CONNECT_TIMEOUT,
        read_timeout=cfg.MYSQL_READ_TIMEOUT,
        write_timeout=cfg.MYSQL_WRITE_TIMEOUT,
        autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )


def _conn(client_id: str | None = None):
    """Return a thread-local connection for *client_id*, recycling after max age."""
    key = client_id or "_default"
    pool: dict = getattr(_tls, "pool", None) or {}
    entry = pool.get(key)
    if entry and (time.time() - entry["ts"]) < cfg.MYSQL_MAX_CONN_AGE:
        return entry["c"]
    if entry:
        try:
            entry["c"].close()
        except Exception:
            pass
    c = _new_conn_for_client(client_id)
    pool[key] = {"c": c, "ts": time.time()}
    _tls.pool = pool
    return c


def _close(client_id: str | None = None):
    key = client_id or "_default"
    pool: dict = getattr(_tls, "pool", None) or {}
    entry = pool.pop(key, None)
    _tls.pool = pool
    if entry:
        try:
            entry["c"].close()
        except Exception:
            pass


def query(sql: str, params: tuple = (), *, client_id: str | None = None) -> list[dict]:
    """Execute SQL with one retry on broken connection."""
    c = _conn(client_id)
    try:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:
        _close(client_id)
        c = _conn(client_id)
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def query_one(sql: str, params: tuple = (), *, client_id: str | None = None) -> Optional[dict]:
    rows = query(sql, params, client_id=client_id)
    return rows[0] if rows else None


def warmup(client_id: str | None = None):
    query("SELECT 1", client_id=client_id)
    logger.info("MySQL connection warmed up (client=%s)", client_id or "default")


# ── Client isolation (maps app-level client_id → DB column customer_key) ─────

def _client_clause(client_id: str | None) -> tuple[str, tuple]:
    """Build optional ``AND customer_key=%s`` clause.

    For isolated clients (own DB) this returns empty — no filter needed.
    For shared clients it adds the WHERE constraint.
    """
    if not client_id or client_id == "default":
        return "", ()
    from app.data.client_registry import get_client_config
    cc = get_client_config(client_id)
    if cc and not cc.needs_client_filter:
        return "", ()
    return " AND customer_key=%s", (client_id,)


def fetch_distinct_locations(client_id: str | None = None) -> list[str]:
    """Distinct location names for a client."""
    ck, params = _client_clause(client_id)
    rows = query(
        f"""SELECT DISTINCT name FROM dg_gateway_data
            WHERE mac_type='Temp-Sensor' AND name IS NOT NULL AND name != ''
            {ck} ORDER BY name""",
        params, client_id=client_id,
    )
    return [r["name"] for r in rows]


def fetch_sensors_by_location(
    client_id: str | None = None, location: str | None = None,
) -> list[str]:
    """Distinct MACs, optionally filtered by client and location (name)."""
    clauses = ["mac_type='Temp-Sensor'"]
    params: list = []
    ck, ck_params = _client_clause(client_id)
    if ck:
        clauses.append(ck.replace(" AND ", "", 1))
        params.extend(ck_params)
    if location:
        clauses.append("name=%s")
        params.append(location)
    where = " AND ".join(clauses)
    rows = query(
        f"SELECT DISTINCT mac FROM dg_gateway_data WHERE {where} ORDER BY mac",
        tuple(params), client_id=client_id,
    )
    return [r["mac"] for r in rows]


# ── Sensor queries ───────────────────────────────────────────────────────────

def fetch_latest_per_sensor(client_id: str | None = None) -> list[dict]:
    """Latest reading per Temp-Sensor MAC (de-duplicated), with location name."""
    ck, ck_params = _client_clause(client_id)
    rows = query(
        f"""SELECT g.mac, g.body_temperature, g.rssi, g.power,
                   g.date_added, g.tags_id, g.gateway_mac, g.name
            FROM dg_gateway_data g
            INNER JOIN (
                SELECT mac, MAX(date_added) AS max_da
                FROM dg_gateway_data
                WHERE mac_type='Temp-Sensor' {ck}
                GROUP BY mac
            ) latest ON g.mac = latest.mac AND g.date_added = latest.max_da
            WHERE g.mac_type='Temp-Sensor' {ck}""",
        ck_params + ck_params, client_id=client_id,
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r["mac"] not in seen:
            seen.add(r["mac"])
            out.append(r)
    return out


def fetch_batch_history(mac_list: list[str], since: datetime,
                        client_id: str | None = None) -> dict[str, list[dict]]:
    """Readings for multiple MACs since cutoff, grouped by MAC."""
    if not mac_list:
        return {}
    ck, ck_params = _client_clause(client_id)
    ph = ",".join(["%s"] * len(mac_list))
    rows = query(
        f"""SELECT mac, body_temperature, date_added
            FROM dg_gateway_data
            WHERE mac IN ({ph}) AND mac_type='Temp-Sensor' AND date_added >= %s {ck}
            ORDER BY mac, date_added DESC""",
        (*mac_list, since, *ck_params), client_id=client_id,
    )
    by_mac: dict[str, list[dict]] = {}
    for r in rows:
        by_mac.setdefault(r["mac"], []).append(r)
    return by_mac


def fetch_readings(device_id: str, since: datetime, *, client_id: str | None = None) -> list[dict]:
    """Ordered readings for a single device."""
    return query(
        """SELECT date_added, body_temperature FROM dg_gateway_data
           WHERE mac=%s AND mac_type='Temp-Sensor' AND date_added >= %s
           ORDER BY date_added ASC""",
        (device_id, since.strftime("%Y-%m-%d %H:%M:%S")),
        client_id=client_id,
    )


def fetch_readings_range(device_id: str, start: datetime, end: datetime,
                         limit: int | None = None, *, client_id: str | None = None) -> list[dict]:
    """Bounded query for historical ranges — caps response size."""
    limit = limit or cfg.MYSQL_QUERY_LIMIT
    return query(
        """SELECT date_added, body_temperature FROM dg_gateway_data
           WHERE mac=%s AND mac_type='Temp-Sensor'
                 AND date_added BETWEEN %s AND %s
           ORDER BY date_added ASC LIMIT %s""",
        (device_id, start.strftime("%Y-%m-%d %H:%M:%S"),
         end.strftime("%Y-%m-%d %H:%M:%S"), limit),
        client_id=client_id,
    )


def fetch_max_date(device_id: str, *, client_id: str | None = None) -> Optional[datetime]:
    row = query_one(
        "SELECT MAX(date_added) AS latest FROM dg_gateway_data WHERE mac=%s AND mac_type='Temp-Sensor'",
        (device_id,), client_id=client_id,
    )
    return row["latest"] if row and row["latest"] else None


def fetch_all_devices(client_id: str | None = None) -> list[str]:
    ck, params = _client_clause(client_id)
    return [r["mac"] for r in query(
        f"SELECT DISTINCT mac FROM dg_gateway_data WHERE mac_type='Temp-Sensor' {ck}",
        params, client_id=client_id,
    )]


def fetch_locations() -> list[dict]:
    return query("""
        SELECT t.tags_id, t.locations_id, t.facilities_id,
               l.location_name, l.location_address
        FROM dg_tags t
        LEFT JOIN dg_locations l ON t.locations_id = l.locations_id
        WHERE t.facilities_id IS NOT NULL
    """)


def fetch_compliance_batch(start: str, end: str, temp_low: float, temp_high: float,
                           client_id: str | None = None) -> list[dict]:
    """Compliance per day in one query."""
    ck, ck_params = _client_clause(client_id)
    return query(
        f"""SELECT DATE(date_added) AS day, COUNT(*) AS total,
                  SUM(CASE WHEN body_temperature BETWEEN %s AND %s THEN 1 ELSE 0 END) AS compliant
           FROM dg_gateway_data
           WHERE mac_type='Temp-Sensor' AND date_added BETWEEN %s AND %s {ck}
           GROUP BY DATE(date_added) ORDER BY day ASC""",
        (temp_low, temp_high, start, end, *ck_params),
        client_id=client_id,
    )
