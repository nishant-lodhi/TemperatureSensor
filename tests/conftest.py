"""Shared pytest fixtures for temp-sensor analytics platform tests.

Environment variables MUST be set before any src imports.
"""

import os

os.environ["ENVIRONMENT"] = "test"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["PROJECT_PREFIX"] = "temp-sensor"
os.environ["DEPLOYMENT_ID"] = "test000001"
os.environ["PLATFORM_CONFIG_TABLE"] = "temp-sensor-platform-config-test000001-test"
os.environ["SENSOR_DATA_TABLE"] = "temp-sensor-sensor-data-test000001-test"
os.environ["ALERTS_TABLE"] = "temp-sensor-alerts-test000001-test"
os.environ["DATA_BUCKET"] = "temp-sensor-data-lake-test000001-test"

import boto3
import pytest
from moto import mock_aws


def _create_platform_config_table(dynamodb):
    """Create platform_config table with pk/sk and zone-index GSI."""
    dynamodb.create_table(
        TableName=os.environ["PLATFORM_CONFIG_TABLE"],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "zone_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "zone-index",
                "KeySchema": [{"AttributeName": "zone_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_sensor_data_table(dynamodb):
    """Create sensor_data table with pk/sk."""
    dynamodb.create_table(
        TableName=os.environ["SENSOR_DATA_TABLE"],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_alerts_table(dynamodb):
    """Create alerts table with pk/sk."""
    dynamodb.create_table(
        TableName=os.environ["ALERTS_TABLE"],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_s3_bucket(s3_client):
    """Create S3 data bucket."""
    s3_client.create_bucket(Bucket=os.environ["DATA_BUCKET"])


@pytest.fixture
def aws_mock():
    """Mock AWS services with moto. Creates DynamoDB tables and S3 bucket."""
    with mock_aws():
        region = os.environ["AWS_REGION"]
        dynamodb = boto3.resource("dynamodb", region_name=region)
        s3_client = boto3.client("s3", region_name=region)

        _create_platform_config_table(dynamodb)
        _create_sensor_data_table(dynamodb)
        _create_alerts_table(dynamodb)
        _create_s3_bucket(s3_client)

        # Reset module caches so they pick up mocked AWS
        from storage import dynamodb_store
        from storage import s3_store
        from config import tenant_config
        from alerts import notifier
        from alerts import alert_engine

        dynamodb_store.reset()
        s3_store.reset()
        tenant_config.reset()
        notifier.reset()
        alert_engine.reset()

        yield


@pytest.fixture
def sample_event():
    """Standard sensor event in Lambda format."""
    return {
        "device_id": "C30000301A80",
        "temperature": 82.7,
        "rssi": -44,
        "power": 87,
        "timestamp": "2024-10-01T17:25:16.000Z",
        "gateway_id": "AC233FC170F4",
    }


@pytest.fixture
def sample_readings():
    """Generate 60 minutes of 1-minute readings with slight upward trend + noise."""
    from datetime import datetime, timezone, timedelta
    import random

    base_time = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    readings = []
    base_temp = 80.0
    for i in range(60):
        ts = base_time + timedelta(minutes=i)
        temp = base_temp + (i * 0.05) + random.uniform(-0.5, 0.5)
        readings.append({
            "temperature": round(temp, 2),
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        })
    return readings


@pytest.fixture
def sample_thresholds():
    """Default threshold values for alert rules."""
    return {
        "temp_critical_high": 95,
        "temp_critical_low": 50,
        "temp_high": 85,
        "temp_low": 65,
        "rapid_change_threshold_f": 4,
        "rapid_change_window_min": 10,
        "sustained_duration_min": 10,
        "sensor_offline_sec": 60,
        "battery_low_pct": 20,
        "anomaly_z_threshold": 3,
    }


@pytest.fixture
def seed_device(aws_mock):
    """Seed platform_config with one device and tenant config. Returns device_id."""
    from config import settings

    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.PLATFORM_CONFIG_TABLE)

    table.put_item(
        Item={
            "pk": "DEVICE#C30000301A80",
            "sk": "META",
            "client_id": "client_1",
            "facility_id": "facility_A",
            "zone_id": "zone_b",
            "sensor_type": "temp_sensor",
            "status": "active",
        }
    )

    table.put_item(
        Item={
            "pk": "TENANT#client_1",
            "sk": "CONFIG",
            "client_id": "client_1",
            "temp_critical_high": 95,
            "temp_critical_low": 50,
            "temp_high": 85,
            "temp_low": 65,
            "rapid_change_threshold_f": 4,
            "rapid_change_window_min": 10,
            "sustained_duration_min": 10,
            "sensor_offline_sec": 60,
            "battery_low_pct": 20,
            "anomaly_z_threshold": 3,
        }
    )

    return "C30000301A80"
