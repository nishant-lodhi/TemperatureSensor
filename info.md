# TempMonitor — Technical Deep Dive

This document explains **every feature, module, and decision** in the TempMonitor platform.
Written for anyone — engineers, auditors, facility administrators — who needs to understand
exactly how the system works, end to end.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Configuration Layer](#2-configuration-layer)
3. [Data Layer](#3-data-layer)
4. [Analytics Engine](#4-analytics-engine)
5. [Alert Management](#5-alert-management)
6. [Authentication & Multi-Tenancy](#6-authentication--multi-tenancy)
7. [Dashboard UI](#7-dashboard-ui)
8. [Callback Architecture](#8-callback-architecture)
9. [Chart System](#9-chart-system)
10. [Simulator](#10-simulator)
11. [Testing Strategy](#11-testing-strategy)

---

## 1. System Overview

TempMonitor reads temperature sensor data from a MySQL database (or S3 Parquet files),
computes analytics in real-time, manages alerts through DynamoDB, and displays everything
on a single-page Plotly Dash dashboard.

**The core principle**: every computation happens on-the-fly. There are no ETL jobs,
no pre-aggregated tables, no scheduled cron tasks. When the dashboard loads, it reads
raw sensor readings, computes statistics, detects anomalies, forecasts future temperatures,
evaluates alert conditions, and renders the UI — all in one request cycle.

**Why this works**: sensor data volumes are moderate (13 sensors × 1 reading every 5–10 seconds ≈
~130,000 readings/day). With proper caching and downsampling, the dashboard responds in
under 2 seconds for any query.

---

## 2. Configuration Layer

**File**: `dashboard/app/config.py` (143 lines)

Every tuneable value in the system lives in this single file. Nothing is hardcoded elsewhere.

### Environment Variables (read at import time)

| Variable | What it controls |
|---|---|
| `AWS_MODE` | When `"true"`, enables Secrets Manager authentication. When `"false"` (default), uses a fixed `demo_client_1` identity — no AWS calls for auth. |
| `DATA_SOURCE` | Which data backend to use: `mysql` (default), `parquet`, or `hybrid` |
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | MySQL Aurora connection parameters |
| `PARQUET_BUCKET` / `PARQUET_PREFIX` | S3 location of daily Parquet files |
| `ALERTS_TABLE` | DynamoDB table name. If empty, auto-generates `TempMonitor-Alerts-local-{client_id}` and creates via moto |
| `NOTE_LAMBDA_ARN` | Lambda function to invoke when officer sends alert note. If empty, just logs locally |

### Temperature Thresholds

These define the "safe operating range" and critical limits:

```
TEMP_CRITICAL_LOW (50°F) ← danger zone
TEMP_LOW (65°F)          ← below normal
                           SAFE RANGE (65–85°F)
TEMP_HIGH (85°F)         ← above normal
TEMP_CRITICAL_HIGH (95°F)← danger zone
```

- Readings between `TEMP_LOW` and `TEMP_HIGH` are "in range" (compliant)
- Readings between `TEMP_HIGH` and `TEMP_CRITICAL_HIGH` trigger `SUSTAINED_HIGH` alert (HIGH severity)
- Readings above `TEMP_CRITICAL_HIGH` trigger `EXTREME_TEMPERATURE` alert (CRITICAL severity)
- Same logic on the cold side

### Cache TTLs

Every cached value has a configurable TTL in seconds:

| What | TTL | Why this value |
|---|---|---|
| Sensor states | 15s | Balance freshness vs DB load; states change slowly |
| Readings | 60s | Once fetched for a time range, data doesn't change |
| Live alerts | 10s | Alerts need fast refresh for officer responsiveness |
| Compliance | 60s | Daily aggregate, doesn't change rapidly |
| Locations | 120s | Facility list rarely changes |
| Tag-to-zone map | 300s | Legacy mapping, essentially static |

### Theme

All UI colours are defined in `COLORS` dict. The theme is a light professional palette
with teal primary (`#0d9488`), orange accent (`#f97316`), and standard semantic colours
(success green, warning amber, danger red). Severity labels use officer-friendly language:
"Urgent" instead of "CRITICAL", "Important" instead of "HIGH".

---

## 3. Data Layer

### 3.1 DataProvider Protocol

**File**: `dashboard/app/data/provider.py` (38 lines)

This file defines the **interface contract** that every data source must satisfy:

```python
class DataProvider(Protocol):
    def get_all_sensor_states(self) -> list[dict]: ...
    def get_readings(self, device_id, since_iso, until_iso) -> list[dict]: ...
    def get_forecast(self, device_id, horizon) -> dict | None: ...
    def get_forecast_series(self, device_id, horizon, steps) -> list[dict]: ...
    def get_compliance_history(self, days) -> list[dict]: ...
    def get_all_devices(self) -> list[str]: ...
    def get_locations(self) -> list[str]: ...
    def get_sensors_for_location(self, location) -> list[str]: ...
    def get_zones(self) -> list[str]: ...
    def get_live_alerts(self) -> list[dict]: ...
    def get_alert_history(self, device_id, days) -> list[dict]: ...
    def dismiss_alert(self, device_id, alert_type) -> None: ...
    def send_alert_note(self, device_id, alert_type, context) -> bool: ...
```

The factory function `get_provider(client_id)` returns a cached `HybridProvider` instance.
During testing, the `SimulatorProvider` or `MockProvider` replaces it via the `_providers` dict.

### 3.2 MySQL Reader

**File**: `dashboard/app/data/mysql_reader.py` (228 lines)

**Connection management**: Uses thread-local storage (`threading.local()`) so each thread
gets its own MySQL connection. Connections are recycled after `MYSQL_MAX_CONN_AGE` seconds (50s)
to prevent stale connections. Every query has automatic retry — if the first attempt fails
(broken pipe, timeout), the connection is closed, a fresh one is created, and the query retries.

**Key queries**:

| Function | What it does | SQL strategy |
|---|---|---|
| `fetch_latest_per_sensor` | Latest reading per MAC | Self-join on `MAX(date_added)` grouped by MAC |
| `fetch_batch_history` | Last 1h of readings for multiple MACs | `IN` clause with MAC list |
| `fetch_readings_range` | Historical readings for one sensor | `BETWEEN` on `date_added`, capped by `MYSQL_QUERY_LIMIT` |
| `fetch_compliance_batch` | Daily compliance for a date range | `GROUP BY DATE(date_added)` with `SUM(CASE WHEN BETWEEN)` |
| `fetch_distinct_locations` | Unique facility names | `DISTINCT name` filtered by `client_id` |
| `fetch_sensors_by_location` | MACs at a specific facility | `WHERE name=%s` with optional `client_id` filter |

All queries filter by `client_id` via `_client_clause()`. The DB column is `customer_key`
but application code uses `client_id` exclusively — the mapping happens once in
`_client_clause()`. For isolated-DB clients (own database), no filter is added.

### 2.5 Client Registry (`client_registry.py`)

The registry loads `clients.yaml` at startup and provides per-client configuration:

| Function | What it does |
|---|---|
| `load_registry(path)` | Parse YAML, resolve `${ENV_VAR}` placeholders, build `ClientConfig` objects |
| `get_client_config(client_id)` | Return config for a client, or fall back to env-var defaults |
| `list_clients()` | Return all registered clients |

Each `ClientConfig` dataclass contains: `client_id`, `name`, `isolation` mode,
DB credentials, Parquet settings, and alerts table name. The `needs_client_filter`
property returns `True` for shared-DB clients (SQL filter needed) and `False` for
isolated-DB clients (no filter, direct connection).

The registry supports two isolation modes:
- **`shared`**: Multiple clients on one database. Queries add `AND customer_key=%s`.
- **`isolated`**: Client has its own database. No filter needed — just connect to the right DB.

`mysql_reader._new_conn_for_client()` uses the registry to create per-client connections
with the correct host, user, password, and database. Connections are pooled per-client
in thread-local storage.

### 3.3 Parquet Reader

**File**: `dashboard/app/data/parquet_reader.py` (111 lines)

S3 daily Parquet files: `s3://{bucket}/{prefix}{YYYY-MM-DD}.parquet`

Each file contains all sensor readings for one UTC day. The reader:
1. Builds a list of dates from `start` to `end`
2. For each date, checks in-memory cache (keyed by `{bucket}/{prefix}{date}`)
3. If not cached or expired (`PARQUET_CACHE_TTL`), downloads from S3
4. Filters by `device_id` and `date_added` range
5. Returns `[{timestamp, temperature}]`

### 3.4 Hybrid Provider

**File**: `dashboard/app/data/hybrid_provider.py` (277 lines)

The orchestrator that ties everything together. Each method follows this pattern:
1. Check cache → return if fresh
2. Route to data source (Parquet first if `hybrid`, then MySQL fallback)
3. Apply analytics (sensor states, forecasts, compliance)
4. Cache the result
5. Return

**Sensor state building** (`get_all_sensor_states`):
1. Fetch latest reading per sensor from MySQL
2. Fetch 1-hour history for all sensors (batch query)
3. For each sensor: call `analytics.build_sensor_state()` which computes rolling stats,
   rate of change, anomaly detection, signal label, battery percentage, and status
4. Cache for 15s

**Readings** (`get_readings`):
1. Try Parquet (if enabled) → fall back to MySQL
2. For MySQL: convert `body_temperature` + `date_added` to `{timestamp, temperature}` dicts
3. Cache for 60s keyed by `(device_id, since, until)`

**Forecast** (`get_forecast`, `get_forecast_series`):
1. Get last 30 minutes of readings for the sensor
2. Run `analytics.forecast_params()` → linear regression
3. Generate forecast series (30 steps × 1 minute each)

---

## 4. Analytics Engine

**File**: `dashboard/app/data/analytics.py` (175 lines)

All functions are **pure** — they take data in, return results out. No database calls, no
side effects, no state. This makes them trivially testable and cacheable.

### Signal Label
Converts raw RSSI (dBm) to human-readable labels:
- `≥ -50`: Strong
- `≥ -65`: Good
- `≥ -80`: Weak
- `< -80`: No Signal

### Rolling Statistics
Given a list of temperature floats, computes mean, standard deviation, min, and max.
Used for the 1-hour rolling window displayed in KPIs.

### Rate of Change
Compares current temperature to the reading from 10 minutes ago.
Used for trend arrows (↑ Rising / → Steady / ↓ Falling) and `RAPID_CHANGE` alerts.

### Anomaly Detection
Two-layer detection:
1. **Hard thresholds**: if temperature exceeds `TEMP_CRITICAL_HIGH` or drops below `TEMP_CRITICAL_LOW`, it's always an anomaly
2. **Z-score**: if the temperature is more than 2.5 standard deviations from the 1-hour mean, it's a statistical anomaly

Both checks return `(is_anomaly: bool, reason: str)`.

### Sensor Status
Based on how long since the sensor's last reading:
- `< 2 min`: online
- `2–5 min`: degraded
- `> 5 min`: offline

### Forecasting
Linear regression on the last N readings:
1. `forecast_params()`: fits a line `y = level + trend × x` to recent temperatures
2. `forecast_point()`: projects the line forward by `steps` and adds a 95% confidence interval
3. `forecast_series()`: generates a time series of predictions + CI bounds

The forecast is intentionally simple (linear) because sensor temperature trends
tend to be monotonic over short periods. The CI widens with the square root of steps,
reflecting increasing uncertainty.

### Build Sensor State
The master function that assembles a complete sensor state dict from raw data:
1. Parse temperature, handle invalid values
2. Calculate age → determine status
3. Extract 1-hour history → rolling stats
4. Compute rate of change
5. Run anomaly detection
6. Parse RSSI → signal label
7. Parse battery → percentage
8. Attach location from `name` column or legacy tag mapping
9. Return a flat dict with 20+ fields

---

## 5. Alert Management

**File**: `dashboard/app/data/alert_manager.py` (250 lines)

### Lifecycle

```
Condition triggers → ACTIVE
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
         [auto-clear]  [Remove]  [Note]
              │        │        │
              ▼        ▼        ▼
          RESOLVED  DISMISSED  Lambda X → DISMISSED
              │        │        │
              └────────┴────────┘
                       │
                  Alert History
                  (DynamoDB, 90-day TTL)
```

### Evaluation

Every 15 seconds, `evaluate()` runs through all sensor states and checks 6 conditions:

```python
ALERT_CONDITIONS = [
    ("EXTREME_TEMPERATURE",     "CRITICAL", temp > critical_high),
    ("EXTREME_TEMPERATURE_LOW", "CRITICAL", temp < critical_low),
    ("SUSTAINED_HIGH",          "HIGH",     critical_high >= temp > temp_high),
    ("LOW_TEMPERATURE",         "MEDIUM",   critical_low <= temp < temp_low),
    ("SENSOR_OFFLINE",          "HIGH",     status == "offline"),
    ("RAPID_CHANGE",            "MEDIUM",   |rate_of_change| > 4.0),
]
```

For each (sensor, condition) pair:
- **If triggered and no existing alert**: create new alert in memory + DynamoDB
- **If triggered but in cooldown**: skip (prevents alert spam after dismiss)
- **If NOT triggered but alert exists**: auto-resolve (move to RESOLVED state)

### Deduplication

Each alert has a primary key: `ALERT#{device_id}#{alert_type}`. Only one alert per
(device, type) can exist at a time. This prevents duplicate alerts for the same condition.

### Cooldown

When an officer dismisses an alert, a cooldown timestamp is recorded.
For `ALERT_COOLDOWN_SEC` (300s = 5 min), the same alert type on the same sensor
won't re-trigger, giving time for corrective action.

### DynamoDB Schema

```
PK: ALERT#{device_id}#{alert_type}     (partition key)
SK: {ISO timestamp}                     (sort key)
GSI: ClientActiveAlerts
  - client_id (partition)
  - state_triggered (sort, e.g. "ACTIVE#2026-03-12T...")
TTL: 90 days from creation
```

### Local Mode

When `AWS_MODE=false`, the system uses `moto` (AWS mock library) to create an in-process
DynamoDB. The exact same code runs — no conditional branches. This means local testing
exercises the full DynamoDB lifecycle including GSI queries.

### Officer Actions

**Note** (Critical/High only): sends the full alert context (device ID, type, sensor state,
timestamp) to a Lambda function (`NOTE_LAMBDA_ARN`), then auto-dismisses the alert.
On the UI, a green checkmark appears briefly.

**Remove**: dismisses the alert from the live screen, starts cooldown. The alert is
preserved in DynamoDB with state `DISMISSED`.

---

## 6. Authentication & Multi-Tenancy

**File**: `dashboard/app/auth.py` (134 lines)

### Token Flow

1. Admin creates a secret in Secrets Manager: `TempMonitor/{deployment_id}/{client_id}`
   containing `{access_token, client_id, client_name}`
2. Admin shares the URL `/connect/{access_token}` with the facility officer
3. Officer visits the URL → token is resolved → signed cookie is set
4. Subsequent requests use the cookie (30-day expiry)
5. Cookie contains `token_hint` (first 8 chars of token) for revocation detection

### Cookie Security

- **HMAC-SHA256 signed**: `base64(payload).hex_signature`
- **HttpOnly**: not accessible to JavaScript
- **Expiry check**: embedded `exp` field verified server-side
- **Revocation**: if the token in Secrets Manager is rotated, the `token_hint` won't match

### Middleware

**File**: `dashboard/app/routes.py` (105 lines)

`@server.before_request` runs before every Flask request:
1. In local mode (`AWS_MODE=false`): sets `g.client_id = "demo_client_1"`, returns
2. Checks for skip paths (`/connect/`, `/assets/`, etc.)
3. Reads cookie → verifies signature → checks expiry → validates token hint
4. Sets `g.client_id` and `g.client_name` for the request

---

## 7. Dashboard UI

**File**: `dashboard/app/pages/monitor.py` (1,098 lines)

### Layout Structure

The `layout()` function returns the page skeleton:
- **Stores**: 7 `dcc.Store` components hold all state (no global variables)
- **Banner**: facility name, sensor count, alert count, average temp
- **Filter bar**: location dropdown, sensor dropdown, date picker, reset button
- **Status bar**: sensor count + filter buttons (All / Critical / Warning / Normal)
- **Alert cards**: current alerts for selected sensor with Note/Remove actions
- **Sensor grid**: scrollable grid of sensor tiles, sorted critical-first
- **KPIs**: 8-card row showing High/Low/Avg/Trend/Forecast/In Range/Battery/Signal
- **Range bar**: LIVE / 1h / 6h / 12h / 24h time buttons
- **Chart**: unified Plotly chart with actual line, forecast, safe zone, alert markers
- **Compliance**: gauge + stats + 7-day trend line chart
- **Alert table**: DataTable with sortable columns and severity highlighting

### Clientside Callbacks (Zero Server Round-Trip)

Six JavaScript callbacks handle instant interactions:
- Status filter button click → updates `status-filter` store
- Range button click → updates `range-mode` store, clears date picker
- Date picker change → sets `range-mode` to "custom", stores date range
- Reset button → clears all filters, returns to LIVE
- MAC filter change → updates `mon-selected` store
- Sensor card click → updates `mon-selected` store

These run entirely in the browser — no network request.

### Compliance Calculation

The `render_compliance` callback carefully separates online and offline sensors:
1. Filter by facility if location filter active
2. Separate `online` and `offline` lists
3. Calculate In Range, Too Hot, Too Cold from **online sensors only**
4. Calculate compliance percentage from online count
5. Count offline separately
6. Display gauge + stats + 7-day trend

---

## 8. Callback Architecture

### Two Data Paths

**Slow path** (`state_pump`, every 15s):
- Fetches ALL sensor states (latest reading per sensor + analytics)
- Fetches ALL live alerts
- Fetches 7-day compliance history
- Auto-selects first visible sensor if none selected

**Fast path** (`readings_pump`, on user action):
- Fetches readings for ONE sensor in the selected time range
- Fetches forecast series (if LIVE mode and online)
- Fetches alert history for the sensor
- Generates forecast alerts

**Optimisation**: when `readings_pump` is triggered by the 15s tick (not by user action)
AND the mode is NOT "live", it returns `no_update` — skipping unnecessary historical data
re-fetches.

### Store-Based Architecture

All data lives in `dcc.Store` components (client-side JSON):
- `store-states`: list of all sensor state dicts
- `store-alerts`: list of live alert dicts
- `store-compliance`: list of daily compliance dicts
- `store-readings`: readings + forecast + alert history for one sensor
- `mon-selected`: currently selected sensor MAC
- `range-mode`: "live", "1", "6", "12", "24", or "custom"
- `store-date-range`: `{start, end}` for custom date range
- `status-filter`: "all", "red", "yellow", or "green"

Display callbacks read from stores and render HTML — they never call the database.

---

## 9. Chart System

**File**: `dashboard/app/pages/charts.py` (348 lines)

### Unified Chart

`unified_chart()` builds a single Plotly figure:

1. **Safe zone**: semi-transparent rectangle between `TEMP_LOW` and `TEMP_HIGH`
2. **Actual line**: solid teal line for readings (dotted gray for offline)
3. **Forecast** (LIVE mode only):
   - CI band: upper/lower confidence bounds, filled region
   - Glow effect: thick semi-transparent lines behind the forecast line
   - Core line: dotted orange line
4. **Threshold annotations**: "Too Hot" and "Too Cold" horizontal lines
5. **High/Low markers**: dashed lines at the actual max and min temperatures
6. **Alert markers**: scatter plot of diamonds at alert timestamps, colour-coded by severity
7. **"Now" marker**: vertical dashed line at the boundary between actual and forecast

### Downsampling

For large datasets (> 2000 points), a min-max-mean bucket algorithm preserves visual fidelity
while reducing point count by ~3x. Each bucket keeps the minimum, maximum, and middle point,
maintaining chart shape while reducing render time.

### Compliance Charts

- **Gauge**: semi-circular indicator with green/red zones split at `COMPLIANCE_TARGET`
- **Trend**: spline line chart with per-day colour (green if ≥ target, red if < 50%, amber otherwise),
  text labels, fill-to-zero, and a dotted target line

---

## 10. Simulator

**File**: `sensor_simulator.py` (488 lines)

A completely standalone, single-file simulator that replaces the `HybridProvider` at runtime.

### How it works

1. Defines 10 live sensors with different temperature profiles (stable, drift_up, hot, cold, rapid, edge)
2. Defines 3 offline sensors matching real MAC addresses from production
3. Seeds 10 days of history at variable resolution (5-min for old data, 10s for last 2 hours)
4. Starts a background thread that generates new readings every 5 seconds
5. Injects the `SimulatorProvider` into `app.data.provider._providers`
6. Starts the Dash server via `werkzeug.serving.run_simple(threaded=True)`

### Temperature Profiles

| Profile | Behaviour | Expected alerts |
|---|---|---|
| `stable` | base ± 0.4°F random | None |
| `drift_up` | 72→78°F over 10 days | Late `SUSTAINED_HIGH` |
| `drift_down` | 74→69°F over 10 days | Late `LOW_TEMPERATURE` |
| `hot` | 88 ± 1.2°F + sine wave | Always `SUSTAINED_HIGH`, sometimes `EXTREME_TEMPERATURE` |
| `cold` | 62°F with dips | Always `LOW_TEMPERATURE` |
| `rapid` | ±8°F spikes every 30 min | `RAPID_CHANGE` |
| `edge` | 82 ± 4°F sine wave | Intermittent `SUSTAINED_HIGH` |

### Alert Evaluation

The simulator has its own alert evaluation that mirrors production logic but stays
self-contained. It tracks active alerts, resolved alerts, dismissed alerts, and cooldowns
— all in-memory. Auto-resolution happens when the triggering condition clears.

---

## 11. Testing Strategy

### Unit Tests (158 tests, ~1,234 lines)

Every module has dedicated tests:

| Test file | What it tests | Key scenarios |
|---|---|---|
| `test_analytics.py` | Signal labels, rolling stats, anomaly, forecast | Boundary values, empty inputs, z-score |
| `test_alert_manager.py` | Alert lifecycle | Create, resolve, dismiss, cooldown, note |
| `test_auth.py` | Cookie HMAC, token resolution | Tampering, expiry, revocation, Unicode |
| `test_config.py` | Config integrity | Required colour keys, threshold ordering |
| `test_monitor.py` | All dashboard callbacks | Banner, grid, KPIs, chart, compliance, filters |
| `test_provider.py` | Protocol + factory | Caching, multi-client isolation |
| `test_routes.py` | Flask middleware | Auth bypass, redirect, healthz |
| `test_lambda_handler.py` | Lambda entry point | Skipped if `serverless_wsgi` not installed |

### MockProvider

A deterministic provider with 3 sensors (1 healthy, 1 hot with alert, 1 offline)
and 2 locations. Used by all monitor tests via `conftest.py` autouse fixture.

### Running Tests

```bash
cd dashboard
python -m pytest tests/ -v        # all tests
python -m ruff check app/ tests/  # lint
```
