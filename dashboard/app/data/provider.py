"""Abstract data provider interface with multi-tenant support.

All dashboard pages call get_provider(client_id) to get a client-scoped
data source. The active provider (mock or AWS) is selected based on
config.AWS_MODE at import time. Instances are cached per client_id.
"""

from __future__ import annotations

import importlib
from typing import Protocol


class DataProvider(Protocol):
    def get_all_sensor_states(self) -> list[dict]: ...
    def get_readings(self, device_id: str, since_iso: str) -> list[dict]: ...
    def get_active_alerts(self, facility_zone: str | None = None) -> list[dict]: ...
    def get_all_alerts(self) -> list[dict]: ...
    def get_forecast(self, device_id: str, horizon: str) -> dict | None: ...
    def get_forecast_series(self, device_id: str, horizon: str, steps: int) -> list[dict]: ...
    def get_compliance_report(self, date_str: str) -> dict | None: ...
    def get_compliance_history(self, days: int) -> list[dict]: ...
    def get_zones(self) -> list[str]: ...
    def get_devices_in_zone(self, zone_id: str) -> list[str]: ...
    def get_all_devices(self) -> list[str]: ...


_providers: dict[str, DataProvider] = {}


def get_provider(client_id: str | None = None) -> DataProvider:
    """Return a DataProvider scoped to the given client_id.

    Instances are cached per client_id. If client_id is None, falls back
    to 'demo_client_1' (mock mode default).
    """
    cid = client_id or "demo_client_1"

    if cid in _providers:
        return _providers[cid]

    from app import config as cfg

    if cfg.AWS_MODE:
        mod = importlib.import_module("app.data.aws_provider")
        _providers[cid] = mod.AWSProvider(cid)
    else:
        mod = importlib.import_module("app.data.mock_provider")
        _providers[cid] = mod.MockProvider(cid)

    return _providers[cid]
