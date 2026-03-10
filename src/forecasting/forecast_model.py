"""Temperature forecasting using Holt's Linear Method (Double Exponential Smoothing)."""

import numpy as np

from config import settings


def fit(
    temperatures: list[float],
    alpha: float | None = None,
    beta: float | None = None,
) -> dict | None:
    """Fit Holt's linear method. Needs >= 3 points."""
    if len(temperatures) < 3:
        return None

    alpha = alpha if alpha is not None else settings.FORECAST_SMOOTHING_ALPHA
    beta = beta if beta is not None else settings.FORECAST_SMOOTHING_BETA

    temps = np.array(temperatures, dtype=float)
    level = temps[0]
    trend = temps[1] - temps[0]

    residuals = []
    prev_level = level
    for obs in temps[1:]:
        level = alpha * obs + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        residuals.append(obs - (prev_level + trend))
        prev_level = level

    residual_std = float(np.std(residuals, ddof=1)) if len(residuals) >= 2 else 0.0

    return {
        "level": float(level),
        "trend": float(trend),
        "alpha": alpha,
        "beta": beta,
        "residual_std": residual_std,
        "n_points": len(temperatures),
    }


def predict(model_params: dict | None, steps: int) -> list[dict]:
    """Forecast: level + h*trend. 95% CI = 1.96 * std * sqrt(h)."""
    if model_params is None:
        return []

    level = model_params["level"]
    trend = model_params["trend"]
    std = model_params.get("residual_std", 0.0)

    result = []
    for h in range(1, steps + 1):
        pred = level + h * trend
        ci_half = 1.96 * std * (h ** 0.5)
        result.append({
            "step": h,
            "predicted": round(pred, 2),
            "ci_lower": round(pred - ci_half, 2),
            "ci_upper": round(pred + ci_half, 2),
        })
    return result


def forecast_temperature(
    readings: list[dict],
    interval_sec: int = 60,
) -> dict | None:
    """High-level: fit model, predict for 30min and 2hr horizons."""
    if len(readings) < 10:
        return None

    temps = []
    for r in readings:
        t = r.get("temperature")
        if t is not None:
            temps.append(float(t))

    if len(temps) < 10:
        return None

    model_params = fit(temps)
    if model_params is None:
        return None

    steps_30 = (settings.FORECAST_HORIZON_SHORT_MIN * 60) // interval_sec
    steps_120 = (settings.FORECAST_HORIZON_LONG_MIN * 60) // interval_sec

    forecast_30 = predict(model_params, steps_30)
    forecast_2hr = predict(model_params, steps_120)

    def summarize(forecast_list):
        if not forecast_list:
            return None
        preds = [f["predicted"] for f in forecast_list]
        ci_lows = [f["ci_lower"] for f in forecast_list]
        ci_highs = [f["ci_upper"] for f in forecast_list]
        return {
            "predicted_temp": forecast_list[-1]["predicted"],
            "ci_lower": min(ci_lows),
            "ci_upper": max(ci_highs),
            "peak_temp": round(max(preds), 2),
            "min_temp": round(min(preds), 2),
            "steps": len(forecast_list),
        }

    return {
        "model_params": model_params,
        "forecast_30min": summarize(forecast_30),
        "forecast_2hr": summarize(forecast_2hr),
    }


def validate_forecast(predicted: float, actual: float) -> dict:
    """Compute validation metrics for a single forecast."""
    error = predicted - actual
    abs_error = abs(error)
    pct_error = (error / actual * 100) if actual != 0 else 0.0
    return {
        "error": error,
        "abs_error": abs_error,
        "pct_error": pct_error,
    }


def compute_accuracy_metrics(errors: list[float]) -> dict:
    """Compute MAE, RMSE, max_error, mean_error from forecast errors."""
    if not errors:
        return {"mae": None, "rmse": None, "max_error": None, "mean_error": None, "n_forecasts": 0}

    arr = np.array(errors, dtype=float)
    abs_errors = np.abs(arr)
    return {
        "mae": float(np.mean(abs_errors)),
        "rmse": float(np.sqrt(np.mean(arr ** 2))),
        "max_error": float(np.max(abs_errors)),
        "mean_error": float(np.mean(arr)),
        "n_forecasts": len(errors),
    }
