"""Parquet reader — S3 daily files with in-memory cache.

File layout: s3://{bucket}/{prefix}{YYYY-MM-DD}.parquet
Each file has all sensor readings for that UTC day.
Expected columns: mac, mac_type, body_temperature, rssi, power, date_added, tags_id
"""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime, timedelta

from app import config as cfg

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, object]] = {}


def read_day(bucket: str, prefix: str, date_str: str):
    """Read a single-day Parquet from S3, with in-memory cache. Returns DataFrame or None."""
    import pyarrow.parquet as pq

    key = f"{bucket}/{prefix}{date_str}"
    if key in _cache:
        ts, df = _cache[key]
        if (time.time() - ts) < cfg.PARQUET_CACHE_TTL:
            return df

    try:
        import boto3
        resp = boto3.client("s3").get_object(Bucket=bucket, Key=f"{prefix}{date_str}.parquet")
        table = pq.read_table(io.BytesIO(resp["Body"].read()))
        df = table.to_pandas()
        _cache[key] = (time.time(), df)
        return df
    except Exception as exc:
        logger.debug("Parquet unavailable for %s: %s", date_str, exc)
        return None


def read_range(bucket: str, prefix: str, start_dt: datetime, end_dt: datetime):
    """Concatenate daily Parquet files over a date range. Returns DataFrame or None."""
    import pandas as pd

    frames = []
    d = start_dt.date()
    while d <= end_dt.date():
        df = read_day(bucket, prefix, d.isoformat())
        if df is not None and len(df) > 0:
            frames.append(df)
        d += timedelta(days=1)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def readings_for_device(bucket: str, prefix: str, device_id: str,
                        since: datetime, end: datetime) -> list[dict]:
    """Filter Parquet data for one device, return [{timestamp, temperature}]."""
    import pandas as pd

    df = read_range(bucket, prefix, since, end)
    if df is None or df.empty:
        return []

    needed = {"mac", "body_temperature", "date_added"}
    if not needed.issubset(df.columns):
        logger.warning("Parquet schema mismatch — need %s, got %s", needed, set(df.columns))
        return []

    df["date_added"] = pd.to_datetime(df["date_added"], utc=True, errors="coerce")
    mask = (df["mac"] == device_id) & (df["date_added"] >= since)
    filtered = df.loc[mask].sort_values("date_added")

    out: list[dict] = []
    for _, row in filtered.iterrows():
        try:
            temp = float(row["body_temperature"])
        except (ValueError, TypeError):
            continue
        ts = row["date_added"]
        out.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(ts, "strftime") else str(ts),
            "temperature": temp,
        })
    return out


def compliance_for_range(bucket: str, prefix: str, start: datetime, end: datetime,
                         temp_low: float, temp_high: float) -> list[dict]:
    """Compute daily compliance from Parquet. Returns [{date, total, compliant}]."""
    import pandas as pd

    df = read_range(bucket, prefix, start, end)
    if df is None or df.empty:
        return []

    df["date_added"] = pd.to_datetime(df["date_added"], utc=True, errors="coerce")
    df = df[df["mac_type"] == "Temp-Sensor"].copy()
    df["day"] = df["date_added"].dt.date

    result: list[dict] = []
    for day, grp in df.groupby("day"):
        temps = pd.to_numeric(grp["body_temperature"], errors="coerce").dropna()
        total = len(temps)
        compliant = int(((temps >= temp_low) & (temps <= temp_high)).sum())
        result.append({"day": day.isoformat(), "total": total, "compliant": compliant})
    return sorted(result, key=lambda r: r["day"])
