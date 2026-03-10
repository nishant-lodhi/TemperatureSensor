"""Anomaly detection using Z-score and moving average deviation."""

from config import settings


def z_score(current_temp: float, mean: float, std: float | None) -> float:
    """Compute Z-score. Returns 0.0 if std is None or 0."""
    if std is None or std == 0:
        return 0.0
    return (current_temp - mean) / std


def check_z_score_anomaly(
    current_temp: float,
    mean: float,
    std: float | None,
    threshold: float | None = None,
) -> dict:
    """Check if current temp is a Z-score anomaly."""
    thresh = threshold if threshold is not None else settings.ANOMALY_Z_THRESHOLD
    z = z_score(current_temp, mean, std)
    is_anomaly = abs(z) >= thresh
    return {"is_anomaly": is_anomaly, "z_score": z, "method": "z_score"}


def check_moving_avg_deviation(
    current_temp: float,
    rolling_avg: float | None,
    threshold_f: float | None = None,
) -> dict:
    """Check if current temp deviates from rolling average beyond threshold."""
    thresh = threshold_f if threshold_f is not None else settings.RAPID_CHANGE_THRESHOLD_F
    if rolling_avg is None:
        return {"is_anomaly": False, "deviation": 0.0, "method": "moving_avg_deviation"}
    deviation = abs(current_temp - rolling_avg)
    is_anomaly = deviation >= thresh
    return {"is_anomaly": is_anomaly, "deviation": deviation, "method": "moving_avg_deviation"}


def check_consecutive_anomalies(
    recent_flags: list[bool],
    min_consecutive: int | None = None,
) -> bool:
    """Check if last N entries are all True."""
    n = min_consecutive if min_consecutive is not None else settings.ANOMALY_MIN_CONSECUTIVE
    if len(recent_flags) < n:
        return False
    return all(recent_flags[-n:])


def detect_anomaly(
    current_temp: float,
    rolling_avg: float | None,
    rolling_std: float | None,
    recent_z_flags: list[bool] | None = None,
) -> dict:
    """Combine z-score, consecutive check, and moving avg deviation."""
    recent_z_flags = recent_z_flags or []
    mean = rolling_avg if rolling_avg is not None else current_temp

    z_result = check_z_score_anomaly(current_temp, mean, rolling_std)
    z_anomaly = z_result["is_anomaly"]
    z_confirmed = check_consecutive_anomalies(recent_z_flags + [z_anomaly])

    ma_result = check_moving_avg_deviation(current_temp, rolling_avg)
    moving_avg_deviation = ma_result["deviation"]
    moving_avg_anomaly = ma_result["is_anomaly"]

    is_anomaly = z_confirmed or moving_avg_anomaly

    return {
        "is_anomaly": is_anomaly,
        "z_score": z_result["z_score"],
        "z_anomaly": z_anomaly,
        "z_confirmed": z_confirmed,
        "moving_avg_deviation": moving_avg_deviation,
        "moving_avg_anomaly": moving_avg_anomaly,
    }
