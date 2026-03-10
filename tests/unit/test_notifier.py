"""Unit tests for alerts/notifier.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "temp-sensor-platform-config-test000001-test")
os.environ.setdefault("SENSOR_DATA_TABLE", "temp-sensor-sensor-data-test000001-test")
os.environ.setdefault("ALERTS_TABLE", "temp-sensor-alerts-test000001-test")
os.environ.setdefault("DATA_BUCKET", "temp-sensor-data-lake-test000001-test")

from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from alerts.notifier import _format_message, reset, send_alert, send_escalation


@pytest.fixture(autouse=True)
def reset_notifier():
    """Reset notifier module state before each test."""
    reset()
    yield
    reset()


@mock_aws
def test_send_alert_critical_sns():
    """mock SNS, send CRITICAL alert, verify publish called."""
    sns = boto3.client("sns", region_name="us-east-1")
    topic_resp = sns.create_topic(Name="critical-alerts")
    topic_arn = topic_resp["TopicArn"]

    with patch("alerts.notifier.settings") as mock_settings:
        mock_settings.CRITICAL_ALERT_TOPIC_ARN = topic_arn
        mock_settings.STANDARD_ALERT_TOPIC_ARN = ""
        mock_settings.AWS_REGION = "us-east-1"

        from alerts import notifier

        notifier.reset()

        alert = {
            "alert_type": "EXTREME_TEMPERATURE",
            "severity": "CRITICAL",
            "message": "Temperature 96.0°F exceeds critical high 95°F",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
            "device_id": "dev1",
        }

        mock_publish = MagicMock(return_value={"MessageId": "test-id"})
        with patch.object(sns, "publish", mock_publish):
            with patch("alerts.notifier._get_client", return_value=sns):
                result = send_alert(alert)
                assert result is True
                mock_publish.assert_called_once()
                call_kwargs = mock_publish.call_args.kwargs
                assert call_kwargs["TopicArn"] == topic_arn
                assert "CRITICAL" in call_kwargs["Message"]
                assert "96.0" in call_kwargs["Message"]


def test_send_alert_local_mode():
    """empty topic ARN → logs instead of SNS."""
    with patch("alerts.notifier.settings") as mock_settings:
        mock_settings.CRITICAL_ALERT_TOPIC_ARN = ""
        mock_settings.STANDARD_ALERT_TOPIC_ARN = ""
        mock_settings.AWS_REGION = "us-east-1"

        alert = {
            "alert_type": "EXTREME_TEMPERATURE",
            "severity": "CRITICAL",
            "message": "Test alert",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
        }

        result = send_alert(alert)
        assert result is True


@mock_aws
def test_send_escalation():
    """verify escalation message includes target."""
    sns = boto3.client("sns", region_name="us-east-1")
    topic_resp = sns.create_topic(Name="critical-alerts")
    topic_arn = topic_resp["TopicArn"]

    with patch("alerts.notifier.settings") as mock_settings:
        mock_settings.CRITICAL_ALERT_TOPIC_ARN = topic_arn
        mock_settings.STANDARD_ALERT_TOPIC_ARN = ""
        mock_settings.AWS_REGION = "us-east-1"

        from alerts import notifier

        notifier.reset()

        alert = {
            "alert_type": "EXTREME_TEMPERATURE",
            "severity": "CRITICAL",
            "message": "Temperature high",
            "triggered_at": "2024-10-01T12:00:00Z",
            "status": "ACTIVE",
        }

        mock_publish = MagicMock(return_value={"MessageId": "test-id"})
        with patch.object(sns, "publish", mock_publish):
            with patch("alerts.notifier._get_client", return_value=sns):
                result = send_escalation(alert, "supervisor")
                assert result is True
                call_kwargs = mock_publish.call_args.kwargs
                assert "supervisor" in call_kwargs["Message"]
                assert "[ESCALATED" in call_kwargs["Message"]


def test_format_message():
    """verify all expected fields in formatted string."""
    alert = {
        "alert_type": "EXTREME_TEMPERATURE",
        "severity": "CRITICAL",
        "message": "Temperature 96.0°F exceeds critical high 95°F",
        "triggered_at": "2024-10-01T12:00:00Z",
        "status": "ACTIVE",
        "device_id": "dev1",
        "temperature": 96.0,
        "threshold": 95,
    }
    msg = _format_message(alert)
    assert "EXTREME_TEMPERATURE" in msg
    assert "CRITICAL" in msg
    assert "Temperature 96.0°F" in msg
    assert "2024-10-01T12:00:00Z" in msg
    assert "ACTIVE" in msg
    assert "device_id" in msg
    assert "dev1" in msg
    assert "temperature" in msg
    assert "96.0" in msg
    assert "threshold" in msg
    assert "95" in msg
