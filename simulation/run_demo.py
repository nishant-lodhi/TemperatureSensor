"""Entry point for full simulation demo."""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# Add project root and src/ to path before any imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_path = os.path.join(_project_root, "src")
for p in (_project_root, _src_path):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("ENVIRONMENT", "dev")
_deployment_id = "sim0000001"
os.environ.setdefault("PLATFORM_CONFIG_TABLE", f"temp-sensor-platform-config-{_deployment_id}-dev")
os.environ.setdefault("SENSOR_DATA_TABLE", f"temp-sensor-sensor-data-{_deployment_id}-dev")
os.environ.setdefault("ALERTS_TABLE", f"temp-sensor-alerts-{_deployment_id}-dev")
os.environ.setdefault("DATA_BUCKET", f"temp-sensor-data-lake-{_deployment_id}-dev")

logging.basicConfig(level=logging.INFO)

from moto import mock_aws

from .data_profile import extract_profile
from .generator import generate_facility
from .pipeline_runner import (
    run_analytics,
    run_compliance,
    run_forecast,
    run_pipeline,
    setup_mock_aws,
)
from .scenarios import HVACFailure, SensorOffline, SensorTamper


@mock_aws
def main():
    """Run full demo: reset caches, setup AWS, generate data, run pipeline, analytics, forecast, compliance."""
    from storage import dynamodb_store, s3_store
    from alerts import notifier
    from config import tenant_config

    dynamodb_store.reset()
    s3_store.reset()
    notifier.reset()
    tenant_config.reset()

    setup_mock_aws()

    profile = extract_profile()
    now = datetime.now(timezone.utc)
    start_time = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    zone_config = {
        "zone_a": {"count": 3, "temp_offset": -2.0},
        "zone_b": {"count": 3, "temp_offset": 0.0},
        "zone_c": {"count": 3, "temp_offset": 4.0},
    }
    scenarios = [
        HVACFailure("zone_c", start_hour=12),
        SensorOffline("TEMP_ZONE_A_003", start_hour=8, duration_min=30),
        SensorTamper("TEMP_ZONE_B_002", start_hour=15, duration_min=20),
    ]

    readings = generate_facility(
        zone_config, start_time, hours=24, profile=profile, interval_sec=15, scenarios=scenarios
    )

    pipeline_result = run_pipeline(readings, batch_size=500)
    analytics_result = run_analytics()
    forecast_result = run_forecast()
    compliance_result = run_compliance()

    # Summary: all sensor states, active alerts
    states = dynamodb_store.get_all_sensor_states()
    alerts = dynamodb_store.get_active_alerts()

    print("\n--- Demo Summary ---")
    print(f"Pipeline: processed={pipeline_result.get('processed')}, rejected={pipeline_result.get('rejected')}")
    print(f"Analytics: devices_processed={analytics_result.get('devices_processed')}")
    print(f"Forecast: devices_processed={forecast_result.get('devices_processed')}")
    print(f"Compliance: date={compliance_result.get('date')}")
    print(f"\nSensor states: {len(states)}")
    for s in states:
        print(f"  {s.get('pk')}: temp={s.get('last_temp')}, zone={s.get('zone_id')}, status={s.get('status')}")
    print(f"\nActive alerts: {len(alerts)}")
    for a in alerts:
        print(f"  {a.get('pk')} | {a.get('sk')} | {a.get('message', '')[:60]}")


if __name__ == "__main__":
    main()
