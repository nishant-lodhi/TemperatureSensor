"""Unit tests for analytics/anomaly_detection.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "test-table")
os.environ.setdefault("SENSOR_DATA_TABLE", "test-table")
os.environ.setdefault("ALERTS_TABLE", "test-table")
os.environ.setdefault("DATA_BUCKET", "test-bucket")


from analytics.anomaly_detection import (
    check_consecutive_anomalies,
    check_moving_avg_deviation,
    check_z_score_anomaly,
    detect_anomaly,
    z_score,
)


class TestZScore:
    def test_z_score_normal(self):
        """z_score(80, 80, 2) → 0.0"""
        assert z_score(80, 80, 2) == 0.0

    def test_z_score_high(self):
        """z_score(86, 80, 2) → 3.0"""
        assert z_score(86, 80, 2) == 3.0

    def test_z_score_zero_std(self):
        """Returns 0.0 when std is 0."""
        assert z_score(90, 80, 0) == 0.0

    def test_z_score_none_std(self):
        """Returns 0.0 when std is None."""
        assert z_score(90, 80, None) == 0.0


class TestCheckZScoreAnomaly:
    def test_check_z_score_anomaly_triggered(self):
        """z > 3 → is_anomaly True"""
        result = check_z_score_anomaly(86, 80, 2, threshold=3)
        assert result["is_anomaly"] is True
        assert result["z_score"] == 3.0

    def test_check_z_score_anomaly_normal(self):
        """z < 3 → is_anomaly False"""
        result = check_z_score_anomaly(85, 80, 2, threshold=3)
        assert result["is_anomaly"] is False
        assert result["z_score"] == 2.5


class TestCheckMovingAvgDeviation:
    def test_moving_avg_deviation_triggered(self):
        """deviation > 4 → True"""
        result = check_moving_avg_deviation(90, 85, threshold_f=4)
        assert result["is_anomaly"] is True
        assert result["deviation"] == 5.0

    def test_moving_avg_deviation_normal(self):
        """deviation < 4 → False"""
        result = check_moving_avg_deviation(87, 85, threshold_f=4)
        assert result["is_anomaly"] is False
        assert result["deviation"] == 2.0


class TestCheckConsecutiveAnomalies:
    def test_consecutive_anomalies_all_true(self):
        """[True, True, True] → True (min_consecutive=3)"""
        assert check_consecutive_anomalies([True, True, True], min_consecutive=3) is True

    def test_consecutive_anomalies_not_enough(self):
        """[True, True, False] → False"""
        assert check_consecutive_anomalies([True, True, False], min_consecutive=3) is False

    def test_consecutive_anomalies_too_few(self):
        """[True, True] with min=3 → False"""
        assert check_consecutive_anomalies([True, True], min_consecutive=3) is False


class TestDetectAnomaly:
    def test_detect_anomaly_full(self):
        """Combined check with z_score > 3 and consecutive flags."""
        # z_score(90, 80, 2) = 5 → anomaly
        # recent_z_flags = [True, True] so with current True → [True, True, True], confirmed
        result = detect_anomaly(
            current_temp=90,
            rolling_avg=80,
            rolling_std=2,
            recent_z_flags=[True, True],
        )
        assert result["is_anomaly"] is True
        assert result["z_anomaly"] is True
        assert result["z_confirmed"] is True

    def test_detect_anomaly_normal(self):
        """Normal reading → is_anomaly False"""
        result = detect_anomaly(
            current_temp=81,
            rolling_avg=80,
            rolling_std=2,
            recent_z_flags=[False, False],
        )
        assert result["is_anomaly"] is False
        assert result["z_anomaly"] is False
        assert result["z_confirmed"] is False
