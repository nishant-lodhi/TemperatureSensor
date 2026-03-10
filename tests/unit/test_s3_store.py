"""Unit tests for storage/s3_store.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")


import boto3

from storage.s3_store import archive_batch, get_report, store_report


def test_archive_batch(aws_mock):
    """archive records, verify S3 object created."""
    records = [
        {"device_id": "C30000301A80", "temperature": 82.5, "timestamp": "2024-10-01T12:00:00Z"},
        {"device_id": "C30000301A80", "temperature": 83.0, "timestamp": "2024-10-01T12:01:00Z"},
    ]
    client_id = "client_1"
    archive_batch(records, client_id)
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ["DATA_BUCKET"]
    resp = s3.list_objects_v2(Bucket=bucket)
    assert "Contents" in resp
    assert len(resp["Contents"]) >= 1
    key = resp["Contents"][0]["Key"]
    assert "client_1" in key
    assert "C30000301A80" in key
    assert key.endswith(".json.gz")


def test_archive_empty(aws_mock):
    """empty list → no S3 write."""
    bucket = os.environ["DATA_BUCKET"]
    s3 = boto3.client("s3", region_name="us-east-1")
    archive_batch([], "client_1")
    resp = s3.list_objects_v2(Bucket=bucket)
    contents = resp.get("Contents", [])
    archive_keys = [c["Key"] for c in contents if "reports" not in c["Key"]]
    assert len(archive_keys) == 0


def test_store_and_get_report(aws_mock):
    """store report, retrieve it, verify content matches."""
    report = {"overall_compliance_pct": 95.5, "zones": {"zone_a": {"compliance_pct": 98.0}}}
    client_id = "client_1"
    report_type = "daily"
    date_str = "2024-10-01"
    store_report(report, client_id, report_type, date_str)
    result = get_report(client_id, report_type, date_str)
    assert result is not None
    assert result["overall_compliance_pct"] == 95.5
    assert result["zones"]["zone_a"]["compliance_pct"] == 98.0


def test_get_report_not_found(aws_mock):
    """unknown report → None."""
    result = get_report("client_1", "daily", "2099-01-01")
    assert result is None
