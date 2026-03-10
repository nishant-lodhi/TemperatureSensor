"""Unit tests for forecasting/forecast_model.py."""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("PLATFORM_CONFIG_TABLE", "test-table")
os.environ.setdefault("SENSOR_DATA_TABLE", "test-table")
os.environ.setdefault("ALERTS_TABLE", "test-table")
os.environ.setdefault("DATA_BUCKET", "test-bucket")

import numpy as np
import pytest

from forecasting.forecast_model import (
    compute_accuracy_metrics,
    fit,
    forecast_temperature,
    predict,
    validate_forecast,
)


def make_readings(temperatures):
    """Build list of reading dicts with temperature values."""
    return [{"temperature": t} for t in temperatures]


class TestFit:
    def test_fit_basic(self):
        """Fit linear series [80, 81, 82, 83, 84], verify level ≈ 84, trend ≈ 1."""
        temps = [80.0, 81.0, 82.0, 83.0, 84.0]
        model = fit(temps)
        assert model is not None
        assert abs(model["level"] - 84) < 2
        assert abs(model["trend"] - 1) < 0.5

    def test_fit_constant(self):
        """Fit [80, 80, 80, 80], verify trend ≈ 0."""
        temps = [80.0, 80.0, 80.0, 80.0]
        model = fit(temps)
        assert model is not None
        assert abs(model["trend"]) < 0.1

    def test_fit_insufficient_data(self):
        """Less than 3 points → None."""
        assert fit([80, 81]) is None
        assert fit([80]) is None


class TestPredict:
    def test_predict_linear(self):
        """Fit linear series, predict 5 steps, verify predictions increase."""
        temps = [80.0, 81.0, 82.0, 83.0, 84.0]
        model = fit(temps)
        predictions = predict(model, steps=5)
        assert len(predictions) == 5
        pred_vals = [p["predicted"] for p in predictions]
        assert pred_vals == sorted(pred_vals)

    def test_predict_confidence_interval(self):
        """CI widens with steps."""
        temps = [80.0, 81.0, 82.0, 83.0, 84.0]
        model = fit(temps)
        predictions = predict(model, steps=5)
        ci_widths = [p["ci_upper"] - p["ci_lower"] for p in predictions]
        assert ci_widths == sorted(ci_widths)

    def test_predict_none_model(self):
        """Returns empty list."""
        assert predict(None, steps=5) == []


class TestForecastTemperature:
    def test_forecast_temperature(self):
        """Verify returns model_params, forecast_30min, forecast_2hr keys."""
        temps = list(np.linspace(80, 85, 15))
        readings = make_readings(temps)
        result = forecast_temperature(readings, interval_sec=60)
        assert result is not None
        assert "model_params" in result
        assert "forecast_30min" in result
        assert "forecast_2hr" in result

    def test_forecast_temperature_insufficient(self):
        """Less than 10 readings → None."""
        readings = make_readings([80, 81, 82, 83, 84])
        assert forecast_temperature(readings) is None


class TestValidateForecast:
    def test_validate_forecast(self):
        """predicted=83.0, actual=82.5, verify error=0.5."""
        result = validate_forecast(83.0, 82.5)
        assert result["error"] == 0.5
        assert result["abs_error"] == 0.5


class TestComputeAccuracyMetrics:
    def test_compute_accuracy_metrics(self):
        """List of errors, verify mae, rmse, max_error."""
        errors = [0.5, -0.3, 1.0, -0.2, 0.8]
        result = compute_accuracy_metrics(errors)
        assert result["mae"] == pytest.approx(np.mean(np.abs(errors)))
        assert result["rmse"] == pytest.approx(np.sqrt(np.mean(np.array(errors) ** 2)))
        assert result["max_error"] == 1.0
        assert result["n_forecasts"] == 5
