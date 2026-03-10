"""Unit tests for analytics/zone_analytics.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "test-table")
os.environ.setdefault("SENSOR_DATA_TABLE", "test-table")
os.environ.setdefault("ALERTS_TABLE", "test-table")
os.environ.setdefault("DATA_BUCKET", "test-bucket")

import pytest

from analytics.zone_analytics import (
    classify_zone_condition,
    compute_zone_summary,
    detect_zone_outliers,
)


def make_device_state(device_id, last_temp, status="online", rate_of_change_10m=None):
    """Build device state dict."""
    d = {"device_id": device_id, "last_temp": last_temp, "status": status}
    if rate_of_change_10m is not None:
        d["rate_of_change_10m"] = rate_of_change_10m
    return d


class TestZoneSummary:
    def test_zone_summary_basic(self):
        """3 devices with known temps, verify avg/min/max."""
        devices = [
            make_device_state("d1", 78),
            make_device_state("d2", 80),
            make_device_state("d3", 82),
        ]
        summary = compute_zone_summary(devices)
        assert summary["sensor_count"] == 3
        assert summary["avg_temp"] == 80.0
        assert summary["min_temp"] == 78.0
        assert summary["max_temp"] == 82.0

    def test_zone_summary_with_trend(self):
        """Positive rate_of_change → "rising"."""
        devices = [
            make_device_state("d1", 78, rate_of_change_10m=0.5),
            make_device_state("d2", 80, rate_of_change_10m=0.4),
        ]
        summary = compute_zone_summary(devices)
        assert summary["trend"] == "rising"

    def test_zone_summary_stable(self):
        """Small rates → "stable"."""
        devices = [
            make_device_state("d1", 78, rate_of_change_10m=0.1),
            make_device_state("d2", 80, rate_of_change_10m=-0.1),
        ]
        summary = compute_zone_summary(devices)
        assert summary["trend"] == "stable"

    def test_zone_summary_empty(self):
        """Returns sensor_count=0."""
        summary = compute_zone_summary([])
        assert summary["sensor_count"] == 0
        assert summary["avg_temp"] is None

    def test_zone_summary_offline(self):
        """Device with status='offline' counted."""
        devices = [
            make_device_state("d1", 78, status="online"),
            make_device_state("d2", 80, status="offline"),
        ]
        summary = compute_zone_summary(devices)
        assert summary["sensor_count"] == 2
        assert summary["online_count"] == 1
        assert summary["offline_count"] == 1


class TestDetectOutliers:
    def test_detect_outliers_one_divergent(self):
        """6 devices where 1 deviates >2 std."""
        # [70, 70, 70, 70, 70, 150]: mean≈83.3, std≈32.7, (150-83.3)/32.7≈2.04 > 2
        devices = [
            make_device_state("d1", 70),
            make_device_state("d2", 70),
            make_device_state("d3", 70),
            make_device_state("d4", 70),
            make_device_state("d5", 70),
            make_device_state("d6", 150),
        ]
        outliers = detect_zone_outliers(devices, std_threshold=2.0)
        assert len(outliers) == 1
        assert outliers[0]["device_id"] == "d6"
        assert outliers[0]["temperature"] == 150
        assert outliers[0]["deviation_std"] > 2.0

    def test_detect_outliers_none(self):
        """All similar → empty list."""
        devices = [
            make_device_state("d1", 78),
            make_device_state("d2", 79),
            make_device_state("d3", 80),
        ]
        assert detect_zone_outliers(devices) == []

    def test_detect_outliers_too_few(self):
        """Less than 3 devices → empty."""
        devices = [
            make_device_state("d1", 78),
            make_device_state("d2", 90),
        ]
        assert detect_zone_outliers(devices) == []


class TestClassifyZoneCondition:
    @pytest.fixture
    def default_thresholds(self):
        return {
            "temp_high": 85,
            "temp_low": 65,
            "temp_critical_high": 95,
            "temp_critical_low": 50,
        }

    def test_classify_normal(self, default_thresholds):
        """avg temp 78 → "normal"."""
        summary = {"sensor_count": 3, "online_count": 3, "avg_temp": 78}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "normal"

    def test_classify_warning(self, default_thresholds):
        """avg temp 83 (within 3°F of 85 threshold) → "warning"."""
        summary = {"sensor_count": 3, "online_count": 3, "avg_temp": 83}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "warning"
        assert result["reason"] == "approaching_temp_high"

    def test_classify_alert(self, default_thresholds):
        """avg temp 86 → "alert"."""
        summary = {"sensor_count": 3, "online_count": 3, "avg_temp": 86}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "alert"
        assert result["reason"] == "temp_high"

    def test_classify_critical(self, default_thresholds):
        """avg temp 96 → "critical"."""
        summary = {"sensor_count": 3, "online_count": 3, "avg_temp": 96}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "critical"
        assert result["reason"] == "temp_critical_high"

    def test_classify_all_offline(self, default_thresholds):
        """0 online → "critical"."""
        summary = {"sensor_count": 3, "online_count": 0, "avg_temp": 78}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "critical"
        assert result["reason"] == "all_offline"

    def test_classify_no_sensors(self, default_thresholds):
        """Empty → "unknown"."""
        summary = {"sensor_count": 0, "online_count": 0, "avg_temp": None}
        result = classify_zone_condition(summary, default_thresholds)
        assert result["status"] == "unknown"
        assert result["reason"] == "no_sensors"
