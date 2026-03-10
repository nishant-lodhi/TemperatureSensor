"""Local pipeline orchestrator using moto to mock AWS services."""

import base64
import json
import os

import boto3

# Import after env setup - settings reads os.environ
from config import settings


def setup_mock_aws():
    """Create DynamoDB tables, S3 bucket, SNS topics. Seed device registry."""
    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)

    # PLATFORM_CONFIG_TABLE: pk, sk, zone-index GSI on zone_id
    try:
        dynamodb.create_table(
            TableName=settings.PLATFORM_CONFIG_TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
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
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        pass

    # SENSOR_DATA_TABLE: pk, sk
    try:
        dynamodb.create_table(
            TableName=settings.SENSOR_DATA_TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        pass

    # ALERTS_TABLE: pk, sk
    try:
        dynamodb.create_table(
            TableName=settings.ALERTS_TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        pass

    # S3 bucket
    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    try:
        s3.create_bucket(Bucket=settings.DATA_BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception:
        pass

    # SNS topics
    sns = boto3.client("sns", region_name=settings.AWS_REGION)
    critical_resp = sns.create_topic(Name="critical-alerts-sim")
    standard_resp = sns.create_topic(Name="standard-alerts-sim")
    os.environ["CRITICAL_ALERT_TOPIC_ARN"] = critical_resp["TopicArn"]
    os.environ["STANDARD_ALERT_TOPIC_ARN"] = standard_resp["TopicArn"]

    _seed_device_registry()


def _seed_device_registry(zone_config: dict | None = None):
    """Seed platform config with tenant and device entries."""
    zones = zone_config or {
        "zone_a": {"count": 3, "temp_offset": -2.0},
        "zone_b": {"count": 3, "temp_offset": 0.0},
        "zone_c": {"count": 3, "temp_offset": 4.0},
    }

    dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = dynamodb.Table(settings.PLATFORM_CONFIG_TABLE)

    table.put_item(
        Item={
            "pk": "TENANT#client_1",
            "sk": "CONFIG",
            "client_id": "client_1",
        }
    )

    for zone_id, cfg in zones.items():
        count = cfg.get("count", 1)
        zone_upper = zone_id.upper().replace("-", "_")
        for i in range(1, count + 1):
            device_id = f"TEMP_{zone_upper}_{i:03d}"
            table.put_item(
                Item={
                    "pk": f"DEVICE#{device_id}",
                    "sk": "META",
                    "client_id": "client_1",
                    "facility_id": "facility_1",
                    "zone_id": zone_id,
                    "sensor_type": "temp_sensor",
                    "status": "active",
                }
            )

    table.put_item(
        Item={
            "pk": "DEVICE#C30000301A80",
            "sk": "META",
            "client_id": "client_1",
            "facility_id": "facility_1",
            "zone_id": "zone_b",
            "sensor_type": "temp_sensor",
            "status": "active",
        }
    )


def run_pipeline(events: list[dict], batch_size: int = 500) -> dict:
    """Create Kinesis-formatted records and call batch_handler.lambda_handler."""
    from handlers.batch_handler import lambda_handler

    records = []
    for evt in events:
        payload = json.dumps(evt, default=str).encode()
        records.append(
            {
                "kinesis": {
                    "data": base64.b64encode(payload).decode(),
                }
            }
        )

    total_processed = 0
    total_rejected = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        result = lambda_handler({"Records": batch}, None)
        total_processed += result.get("processed", 0)
        total_rejected += result.get("rejected", 0)

    return {"processed": total_processed, "rejected": total_rejected}


def run_analytics() -> dict:
    """Call scheduled_handler with mode=analytics."""
    from handlers.scheduled_handler import lambda_handler

    return lambda_handler({"mode": "analytics"}, None)


def run_forecast() -> dict:
    """Call scheduled_handler with mode=forecast."""
    from handlers.scheduled_handler import lambda_handler

    return lambda_handler({"mode": "forecast"}, None)


def run_compliance() -> dict:
    """Call scheduled_handler with mode=compliance."""
    from handlers.scheduled_handler import lambda_handler

    return lambda_handler({"mode": "compliance"}, None)
