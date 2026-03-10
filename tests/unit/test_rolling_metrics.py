"""Unit tests for analytics/rolling_metrics.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "test-table")
os.environ.setdefault("SENSOR_DATA_TABLE", "test-table")
os.environ.setdefault("ALERTS_TABLE", "test-table")
os.environ.setdefault("DATA_BUCKET", "test-bucket")

from datetime import datetime, timedelta

import numpy as np

from analytics.rolling_metrics import (
    compute_all_metrics,
    compute_min_max,
    compute_rate_of_change,
    compute_rolling_average,
    compute_rolling_std,
)


def make_readings(timestamps, temperatures):
    """Build list of reading dicts with timestamp (ISO string) and temperature."""
    return [
        {"timestamp": ts if isinstance(ts, str) else ts.isoformat(), "temperature": t}
        for ts, t in zip(timestamps, temperatures)
    ]


def make_readings_from_base(base_iso, minute_offsets, temperatures):
    """Build readings with timestamps at base + minute_offsets (minutes)."""
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    timestamps = [
        (base + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for m in minute_offsets
    ]
    return make_readings(timestamps, temperatures)


class TestRollingAverage:
    def test_rolling_average_basic(self):
        """10 readings over 10 min, verify average."""
        temps = [80.0, 81.0, 82.0, 83.0, 84.0, 85.0, 86.0, 87.0, 88.0, 89.0]
        readings = make_readings_from_base("2024-10-01T12:00:00Z", range(10), temps)
        avg = compute_rolling_average(readings, window_minutes=10)
        expected = np.mean(temps)
        assert avg is not None
        assert abs(avg - expected) < 0.001

    def test_rolling_average_window(self):
        """Only readings within window are included."""
        # 5 readings in window (last 10 min), 3 outside
        base = "2024-10-01T12:00:00Z"
        # Readings at 0, 2, 4, 6, 8, 10, 15, 20 min - latest at 20 min
        # Window = 10-20 min, so only readings at 10, 15, 20 are in window
        minute_offsets = [0, 2, 4, 6, 8, 10, 15, 20]
        temps = [70.0, 71.0, 72.0, 73.0, 74.0, 80.0, 82.0, 84.0]  # last 3 avg = 82
        readings = make_readings_from_base(base, minute_offsets, temps)
        avg = compute_rolling_average(readings, window_minutes=10)
        assert avg is not None
        assert abs(avg - 82.0) < 0.001

    def test_rolling_average_empty(self):
        """Returns None for empty list."""
        assert compute_rolling_average([], window_minutes=10) is None


class TestRollingStd:
    def test_rolling_std(self):
        """Verify standard deviation with known values (ddof=1)."""
        temps = [80.0, 82.0, 84.0, 86.0, 88.0]  # mean=84, std (ddof=1) = 3.162...
        readings = make_readings_from_base("2024-10-01T12:00:00Z", range(5), temps)
        std = compute_rolling_std(readings, window_minutes=10)
        expected = np.std(temps, ddof=1)
        assert std is not None
        assert abs(std - expected) < 0.001

    def test_rolling_std_single_point(self):
        """Returns None for single point (need >= 2 for ddof=1)."""
        readings = make_readings_from_base("2024-10-01T12:00:00Z", [0], [80.0])
        assert compute_rolling_std(readings, window_minutes=10) is None


class TestRateOfChange:
    def test_rate_of_change_rising(self):
        """Temp goes from 80 to 84 over 10 min → positive rate."""
        # First reading at 0 min (80), last at 10 min (84)
        minute_offsets = [0, 5, 10]
        temps = [80.0, 82.0, 84.0]
        readings = make_readings_from_base("2024-10-01T12:00:00Z", minute_offsets, temps)
        rate = compute_rate_of_change(readings, lookback_minutes=10)
        assert rate is not None
        assert abs(rate - 4.0) < 0.001

    def test_rate_of_change_falling(self):
        """Temp goes from 84 to 80 → negative rate."""
        minute_offsets = [0, 5, 10]
        temps = [84.0, 82.0, 80.0]
        readings = make_readings_from_base("2024-10-01T12:00:00Z", minute_offsets, temps)
        rate = compute_rate_of_change(readings, lookback_minutes=10)
        assert rate is not None
        assert abs(rate - (-4.0)) < 0.001

    def test_rate_of_change_insufficient(self):
        """Single reading: uses same reading for past and latest → returns 0.0."""
        readings = make_readings_from_base("2024-10-01T12:00:00Z", [0], [80.0])
        rate = compute_rate_of_change(readings, lookback_minutes=10)
        assert rate == 0.0


class TestMinMax:
    def test_min_max(self):
        """Verify min and max correctly computed."""
        temps = [78.0, 82.0, 85.0, 80.0, 90.0]
        readings = make_readings_from_base("2024-10-01T12:00:00Z", range(5), temps)
        result = compute_min_max(readings, window_minutes=10)
        assert result is not None
        assert result["min"] == 78.0
        assert result["max"] == 90.0

    def test_min_max_empty(self):
        """Returns None for empty."""
        assert compute_min_max([], window_minutes=10) is None


class TestComputeAllMetrics:
    def test_compute_all_metrics(self):
        """Verify all keys present."""
        temps = list(np.linspace(80, 84, 15))
        readings = make_readings_from_base("2024-10-01T12:00:00Z", range(15), temps)
        result = compute_all_metrics(readings)
        expected_keys = {
            "rolling_avg_10m",
            "rolling_avg_1h",
            "rolling_std_10m",
            "rolling_std_1h",
            "rate_of_change_10m",
            "min_max_10m",
            "min_max_1h",
            "reading_count_1h",
        }
        assert set(result.keys()) == expected_keys

    def test_count_in_window(self):
        """Correct count of readings in window."""
        # Latest at 65 min; 1h window = [5, 65] min
        # 5 readings in window (10, 20, 30, 40, 65), 2 outside (0, 1)
        minute_offsets = [0, 1, 10, 20, 30, 40, 65]
        temps = [70.0, 71.0, 72.0, 74.0, 76.0, 78.0, 82.0]
        readings = make_readings_from_base("2024-10-01T12:00:00Z", minute_offsets, temps)
        result = compute_all_metrics(readings)
        assert result["reading_count_1h"] == 5
