"""S3 storage for raw data archival and compliance reports.

Archive path:
  s3://{bucket}/{env}/{client_id}/{device_id}/year=YYYY/month=MM/day=DD/
    hour=HH/{batch_id}.json.gz

Report path:
  s3://{bucket}/{env}/reports/{client_id}/{report_type}/{date}.json
"""

import gzip
import json
import logging
import uuid
from datetime import datetime, timezone

import boto3

from config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=settings.AWS_REGION)
    return _client


def archive_batch(records: list[dict], client_id: str):
    """Archive a batch of sensor records to S3 as gzipped JSON."""
    if not records:
        return
    now = datetime.now(timezone.utc)
    batch_id = uuid.uuid4().hex[:12]
    device_id = records[0].get("device_id", "unknown")
    key = (
        f"{settings.ENVIRONMENT}/{client_id}/{device_id}/"
        f"year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        f"hour={now.hour:02d}/{batch_id}.json.gz"
    )
    body = gzip.compress(json.dumps(records, default=str).encode())
    _get_client().put_object(Bucket=settings.DATA_BUCKET, Key=key, Body=body)
    logger.info("Archived %d records → s3://%s/%s", len(records), settings.DATA_BUCKET, key)


def store_report(report: dict, client_id: str, report_type: str, date_str: str):
    """Store a compliance/analytics report to S3."""
    key = f"{settings.ENVIRONMENT}/reports/{client_id}/{report_type}/{date_str}.json"
    body = json.dumps(report, default=str, indent=2).encode()
    _get_client().put_object(Bucket=settings.DATA_BUCKET, Key=key, Body=body)
    logger.info("Stored report → s3://%s/%s", settings.DATA_BUCKET, key)


def get_report(client_id: str, report_type: str, date_str: str) -> dict | None:
    """Retrieve a stored report from S3."""
    key = f"{settings.ENVIRONMENT}/reports/{client_id}/{report_type}/{date_str}.json"
    try:
        resp = _get_client().get_object(Bucket=settings.DATA_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except Exception:
        return None


def reset():
    """Clear cached client. Called in tests."""
    global _client
    _client = None
