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
10. [Timezone Handling](#10-timezone-handling)
11. [Simulator](#11-simulator)
12. [Testing Strategy](#12-testing-strategy)

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
    def get_db_time(self) -> datetime | None: ...
```

The factory function `get_provider(client_id)` returns a cached `HybridProvider` instance.
During testing, the `SimulatorProvider` or `MockProvider` replaces it via the `_providers` dict.

### 3.2 MySQL Reader

**File**: `dashboard/app/data/mysql_reader.py` (311 lines)

**Connection management**: Uses thread-local storage (`threading.local()`) so each thread
gets its own MySQL connection. Connections are recycled after `MYSQL_MAX_CONN_AGE` seconds (50s)
to prevent stale connections. Every query has automatic retry — if the first attempt fails
(broken pipe, timeout), the connection is closed, a fresh one is created, and the query retries.

**Timezone detection**: The module maintains a cached timezone offset (`_tz_offset`) that
represents the difference between the DB server's `NOW()` (UTC) and the `date_added` column's
timezone (typically US/Eastern). This is detected automatically by `_detect_tz_offset()` and
cached for 1 hour. `fetch_db_now()` applies this offset so all time anchoring aligns with
`date_added` values. See [Section 10: Timezone Handling](#10-timezone-handling) for full details.

**Key queries**:

| Function | What it does | SQL strategy |
|---|---|---|
| `fetch_latest_per_sensor` | Latest reading per MAC | Self-join on `MAX(date_added)` grouped by MAC |
| `fetch_batch_history` | Last 1h of readings for multiple MACs | `IN` clause with MAC list |
| `fetch_readings_range` | Historical readings for one sensor | `BETWEEN` on `date_added`, capped by `MYSQL_QUERY_LIMIT` |
| `fetch_compliance_batch` | Daily compliance for a date range | `GROUP BY DATE(date_added)` with `SUM(CASE WHEN BETWEEN)` |
| `fetch_distinct_locations` | Unique facility names | `DISTINCT name` filtered by `client_id` |
| `fetch_sensors_by_location` | MACs at a specific facility | `WHERE name=%s` with optional `client_id` filter |
| `fetch_db_now` | Current time aligned with `date_added` timezone | `SELECT NOW()` minus detected timezone offset |

All queries filter by `client_id` via `_client_clause()`. The DB column is `customer_key`
but application code uses `client_id` exclusively — the mapping happens once in
`_client_clause()`. For isolated-DB clients (own database), no filter is added.

### 3.3 Client Registry (`client_registry.py`)

**File**: `dashboard/app/data/client_registry.py` (199 lines)

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

### 3.4 Parquet Reader

**File**: `dashboard/app/data/parquet_reader.py` (111 lines)

S3 daily Parquet files: `s3://{bucket}/{prefix}{YYYY-MM-DD}.parquet`

Each file contains all sensor readings for one UTC day. The reader:
1. Builds a list of dates from `start` to `end`
2. For each date, checks in-memory cache (keyed by `{bucket}/{prefix}{date}`)
3. If not cached or expired (`PARQUET_CACHE_TTL`), downloads from S3
4. Filters by `device_id` and `date_added` range
5. Returns `[{timestamp, temperature}]` with timestamps formatted without "Z" suffix (DB local time)

### 3.5 Hybrid Provider

**File**: `dashboard/app/data/hybrid_provider.py` (315 lines)

The orchestrator that ties everything together. Each method follows this pattern:
1. Check cache → return if fresh
2. Route to data source (Parquet first if `hybrid`, then MySQL fallback)
3. Apply analytics (sensor states, forecasts, compliance)
4. Cache the result
5. Return

**DB time anchoring** (`_db_now()`): every time-sensitive operation uses `mysql_reader.fetch_db_now()`
as its reference point, not `datetime.now()` or `datetime.utcnow()`. This ensures all
calculations (sensor age, query ranges, compliance boundaries, forecast timestamps)
are in the same timezone as the `date_added` column.

**Sensor state building** (`get_all_sensor_states`):
1. Fetch latest reading per sensor from MySQL
2. Fetch 1-hour history for all sensors (batch query)
3. For each sensor: call `analytics.build_sensor_state()` with `now=db_now` which computes
   rolling stats, rate of change, anomaly detection, signal label, battery percentage, and status
4. Cache for 15s

**Readings** (`get_readings`):
1. Try Parquet (if enabled) → fall back to MySQL
2. For MySQL: convert `body_temperature` + `date_added` to `{timestamp, temperature}` dicts
3. Timestamps formatted as `%Y-%m-%dT%H:%M:%S` (no "Z" — already in DB local time)
4. Default `until` parameter is `_db_now()` if not specified
5. Cache for 60s keyed by `(device_id, since, until)`

**Forecast** (`get_forecast`, `get_forecast_series`):
1. Get last 30 minutes of readings for the sensor
2. Run `analytics.forecast_params()` → linear regression
3. Generate forecast series (30 steps × 1 minute each) using `_db_now()` as reference time
4. Forecast timestamps formatted without "Z" suffix

**Compliance history** (`get_compliance_history`):
1. Fetch daily compliance data from MySQL for the specified date range
2. **Deduplicate**: if the same date appears multiple times, keep only the first entry
3. **Fill missing dates**: iterate day-by-day from `start` to `db_now`, inserting `{"date": "...", "compliance_pct": 0.0}` for any day with no data
4. Cache for 60s

**Alert evaluation** (`get_live_alerts`):
1. Fetch current sensor states
2. Call `self._alerts.evaluate(states, now_dt=self._db_now())` — passing DB local time
   so alert timestamps match the data timezone, not server UTC

---

## 4. Analytics Engine

**File**: `dashboard/app/data/analytics.py` (180 lines)

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
Based on how long since the sensor's last reading. The age calculation uses **naive datetime
comparison** — both `now` and `last_seen` have their `tzinfo` stripped before subtraction.
This is critical because `now` comes from `fetch_db_now()` (UTC minus offset = local naive)
and `last_seen` is already naive (from `date_added`):

```python
ls = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
n = now.replace(tzinfo=None) if now.tzinfo else now
age_sec = (n - ls).total_seconds()
```

Thresholds:
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

Forecast timestamps are formatted as `%Y-%m-%dT%H:%M:00` (no "Z" suffix), using
the reference time from `_db_now()`.

### Build Sensor State
The master function that assembles a complete sensor state dict from raw data:
1. Parse temperature, handle invalid values
2. Calculate age using timezone-aligned naive datetimes → determine status
3. Extract 1-hour history → rolling stats
4. Compute rate of change
5. Run anomaly detection
6. Parse RSSI → signal label
7. Parse battery → percentage
8. Attach location from `name` column or legacy tag mapping
9. Format `last_seen` as `%Y-%m-%dT%H:%M:%S` (no "Z")
10. Return a flat dict with 20+ fields

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

Every 15 seconds, `evaluate(sensor_states, now_dt)` runs through all sensor states and checks 6 conditions.
The `now_dt` parameter receives the DB-local time from `hybrid_provider._db_now()` so that
all alert timestamps (`triggered_at`, `resolved_at`) are in the same timezone as the sensor data.

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

### Timestamp Consistency

All alert timestamps use the same timezone as sensor data:
- `triggered_at`: from `now_dt` parameter (DB local time)
- `resolved_at`: `datetime.now().isoformat()` (naive local, matching DB timezone)
- `dismissed_at`: same as `resolved_at`

This ensures alert timestamps displayed on the chart align with reading timestamps.

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

**File**: `dashboard/app/routes.py` (109 lines)

`@server.before_request` runs before every Flask request:
1. In local mode (`AWS_MODE=false`): sets `g.client_id = "demo_client_1"`, returns
2. Checks for skip paths (`/connect/`, `/assets/`, `/healthz`, etc.)
3. Reads cookie → verifies signature → checks expiry → validates token hint
4. Sets `g.client_id` and `g.client_name` for the request

---

## 7. Dashboard UI

**File**: `dashboard/app/pages/monitor.py` (1,105 lines)

### Layout Structure

The `layout()` function returns the page skeleton. It initialises `today` using
`prov.get_db_time().date()` (falling back to UTC) so the date range picker's default
aligns with the DB's current date:

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

### Navbar Clock

**File**: `dashboard/app/main.py` (121 lines)

The clock callback (`update_clock`) runs every second and displays the current time in
the navbar. On the first tick, it auto-detects the timezone offset:

1. Calls `prov.get_db_time()` to get DB-local current time
2. Computes `_clock_offset = db_now - datetime.now(timezone.utc).replace(tzinfo=None)`
3. On every subsequent tick: `display = utc_now + _clock_offset`
4. Shows label "Local" if offset was detected, "UTC" if not

This means the navbar always shows the facility's local time (e.g., US/Eastern) without
requiring any explicit timezone configuration.

### Clientside Callbacks (Zero Server Round-Trip)

Six JavaScript callbacks handle instant interactions:
- Status filter button click → updates `status-filter` store
- Range button click → updates `range-mode` store, clears date picker
- Date picker change → sets `range-mode` to "custom", stores date range
- Reset button → clears all filters, returns to LIVE
- MAC filter change → updates `mon-selected` store
- Sensor card click → updates `mon-selected` store

These run entirely in the browser — no network request.

### KPIs

The `render_kpis` callback displays 8 information cards for the selected sensor:

| Card | Source | Display |
|---|---|---|
| High | 1h rolling max | Temperature in °F |
| Low | 1h rolling min | Temperature in °F |
| Avg | 1h rolling mean | Temperature in °F |
| Trend | Rate of change | Rising ↑ / Steady → / Falling ↓ |
| Forecast (or "Last" for offline) | Linear regression point estimate | Temperature in °F |
| In Range | Last N readings compliance % | Percentage |
| Battery | `power` column | Percentage (always shown, even when offline) |
| Signal | RSSI → label | Strong/Good/Weak/No Signal |

An anomaly alert box appears when `anomaly=True` with the anomaly reason.

### Compliance Calculation

The `render_compliance` callback uses **total sensors** as the denominator, not just online ones:

1. Filter by facility if location filter active
2. Separate `online` and `offline` lists
3. Count In Range, Too Hot, Too Cold from online sensors
4. `pct = in_range / total * 100` — offline sensors reduce the compliance score
5. Count offline sensors separately
6. Display gauge + stats + 7-day trend (with missing dates filled to 0%)

**Example**: 3 sensors total, 1 in-range, 2 offline → compliance = 33.3% (not 100%).

### Time-Formatting Helper

`_fmt_time(iso)` converts ISO strings to display format:
1. Strips "Z" suffix if present (all timestamps are already in DB local time)
2. Parses with `datetime.fromisoformat()`
3. Formats as `"Mar 13, 14:30"` for display
4. Returns empty string on any parsing error

---

## 8. Callback Architecture

### Two Data Paths

**Slow path** (`state_pump`, every 15s):
- Fetches ALL sensor states (latest reading per sensor + analytics)
- Fetches ALL live alerts (passes `now_dt=db_now` for timestamp alignment)
- Fetches 7-day compliance history (with filled dates)
- Auto-selects first visible sensor if none selected

**Fast path** (`readings_pump`, on user action):
- Fetches readings for ONE sensor in the selected time range
- Fetches forecast series (if LIVE mode and online)
- Fetches alert history for the sensor
- Generates forecast alerts

**Optimisation**: when `readings_pump` is triggered by the 15s tick (not by user action)
AND the mode is NOT "live", it returns `no_update` — skipping unnecessary historical data
re-fetches.

### Time Anchoring in `_fetch_readings`

The `_fetch_readings` function uses `prov.get_db_time()` as the sole time anchor:

| Mode | `since` | `until` | `x_until` (chart right edge) |
|---|---|---|---|
| LIVE (online) | db_now − 2h | db_now | db_now + 1h (forecast window) |
| LIVE (offline) | last_seen − 2h | last_seen | last_seen |
| 1h / 6h / 12h / 24h | db_now − Nh | db_now | db_now |
| Custom date range | start 00:00:00 | end 23:59:59 | end 23:59:59 |

For LIVE mode, the `x_until = db_now + 1h` creates a 1-hour window ahead of "now":
30 minutes for the forecast line + 30 minutes of buffer. This prevents blank space on the
chart after the forecast ends.

### Store-Based Architecture

All data lives in `dcc.Store` components (client-side JSON):
- `store-states`: list of all sensor state dicts
- `store-alerts`: list of live alert dicts
- `store-compliance`: list of daily compliance dicts
- `store-readings`: readings + forecast + alert history for one sensor, plus `since` and `until` for chart ranging
- `mon-selected`: currently selected sensor MAC
- `range-mode`: "live", "1", "6", "12", "24", or "custom"
- `store-date-range`: `{start, end}` for custom date range
- `status-filter`: "all", "red", "yellow", or "green"

Display callbacks read from stores and render HTML — they never call the database.

---

## 9. Chart System

**File**: `dashboard/app/pages/charts.py` (364 lines)

### Unified Chart

`unified_chart()` builds a single Plotly figure with explicit X-axis control:

1. **Safe zone**: semi-transparent rectangle between `TEMP_LOW` and `TEMP_HIGH`, spanning the full
   `x_since` → `x_until` range (not just the data extent)
2. **Actual line**: solid teal line for readings (dotted gray for offline)
3. **Forecast** (LIVE mode only):
   - CI band: upper/lower confidence bounds, filled region
   - Glow effect: thick semi-transparent lines behind the forecast line
   - Core line: dotted orange line
4. **Threshold annotations**: "Too Hot" and "Too Cold" horizontal lines
5. **High/Low markers**: dashed lines at the actual max and min temperatures
6. **Alert markers**: scatter plot of diamonds at alert timestamps, colour-coded by severity
7. **"Now" marker**: vertical dashed line at the boundary between actual and forecast

### X-Axis Range Locking

The chart always locks its X-axis to the requested time window, regardless of data availability:

```python
if x_since and x_until:
    xaxis["range"] = [x_since, x_until]
```

**Why**: without this, Plotly auto-fits the axis to the data extent. If a user selects "6h"
but only has 30 minutes of data, the chart would zoom to 30 minutes — making the time
buttons appear broken. Locking the axis shows the full 6-hour window with the 30 minutes of
data positioned correctly.

### Empty Data Handling

When the readings list is empty but `x_since`/`x_until` are provided, the chart still renders:
- Safe zone band fills the full range
- Threshold lines are drawn
- A centred annotation reads "No readings in this range"
- The graph structure (axes, grid) remains visible

This replaces the old behavior of returning a blank "Select a sensor" placeholder when no
data existed for a date range.

### Downsampling

For large datasets (> 2000 points), a min-max-mean bucket algorithm preserves visual fidelity
while reducing point count by ~3x. Each bucket keeps the minimum, maximum, and middle point,
maintaining chart shape while reducing render time.

### Compliance Charts

- **Gauge**: semi-circular indicator with green/red zones split at `COMPLIANCE_TARGET`
- **Trend**: spline line chart with per-day colour (green if ≥ target, red if < 50%, amber otherwise),
  text labels, fill-to-zero, and a dotted target line

---

## 10. Timezone Handling

The most subtle aspect of the system. Sensors in a Florida facility report data
with `date_added` timestamps in US/Eastern, but the MySQL server's `NOW()` returns UTC.

### The Problem

If the code naively compares `NOW()` (UTC 18:30) with `MAX(date_added)` (Eastern 14:30),
it calculates an age of 4 hours — marking the sensor as offline even though it reported
5 seconds ago.

### The Solution

**`mysql_reader._detect_tz_offset()`**:
1. Runs `SELECT NOW() AS server_now`
2. Runs `SELECT MAX(date_added) ... WHERE mac_type='Temp-Sensor'`
3. Computes `offset_hours = round((server_now - latest).total_seconds() / 3600)`
4. Returns `timedelta(hours=offset_hours)`
5. Caches the offset for 1 hour

**`mysql_reader.fetch_db_now()`**:
1. Runs `SELECT NOW() AS server_now`
2. Returns `server_now - _detect_tz_offset()` → result is in `date_added`'s timezone

### Where It's Used

| Location | How it uses `fetch_db_now()` |
|---|---|
| `hybrid_provider.get_all_sensor_states()` | Passes `now=db_now` to `build_sensor_state()` for accurate age calculation |
| `hybrid_provider.get_readings()` | Default `until` parameter for time queries |
| `hybrid_provider.get_compliance_history()` | End date for day-filling loop |
| `hybrid_provider.get_live_alerts()` | `now_dt` parameter to `alert_manager.evaluate()` |
| `hybrid_provider.get_forecast_series()` | Reference time for forecast timestamps |
| `monitor.py._fetch_readings()` | Anchor for time window calculations (since/until) |
| `monitor.py.layout()` | Initializes date picker's "today" |
| `main.py.update_clock()` | Computes clock offset for navbar display |

### Multi-Client Timezone

Each client can be on a different DB server in a different timezone. The offset detection
runs per `client_id` (via the connection pool), so clients on a US/Eastern server see
Eastern time while clients on a US/Central server see Central time, with no configuration needed.

### Why Not UTC Everywhere?

The `date_added` column is populated by the sensor gateway application (outside our control)
and uses the server's local timezone. Converting everything to UTC would require either:
- Modifying the gateway (not possible)
- Storing a per-client timezone string and doing explicit conversions

Auto-detection avoids both: it works with any timezone and adapts automatically.

---

## 11. Simulator

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

## 12. Testing Strategy

### Unit Tests (161 tests, ~1,280 lines)

Every module has dedicated tests:

| Test file | What it tests | Key scenarios |
|---|---|---|
| `test_analytics.py` | Signal labels, rolling stats, anomaly, forecast | Boundary values, empty inputs, z-score |
| `test_alert_manager.py` | Alert lifecycle | Create, resolve, dismiss, cooldown, note |
| `test_auth.py` | Cookie HMAC, token resolution | Tampering, expiry, revocation, Unicode |
| `test_config.py` | Config integrity | Required colour keys, threshold ordering |
| `test_monitor.py` | All dashboard callbacks | Banner, grid, KPIs, chart, compliance, filters, empty chart |
| `test_provider.py` | Protocol + factory | Caching, multi-client isolation |
| `test_routes.py` | Flask middleware | Auth bypass, redirect, healthz |
| `test_lambda_handler.py` | Lambda entry point | Skipped if `serverless_wsgi` not installed |

### MockProvider

A deterministic provider with 3 sensors (1 healthy, 1 hot with alert, 1 offline)
and 2 locations. Used by all monitor tests via `conftest.py` autouse fixture.

### Production Readiness Validated

A deep-dive integration test (run against a live DB, then removed) validated 169 assertions
across 16 categories:
- Sensor states (online/offline/degraded, battery, signal, anomaly)
- Timezone auto-detection (`_detect_tz_offset`, `fetch_db_now`)
- Time range buttons (live, 1h, 6h, 12h, 24h) and custom date ranges
- Offline sensor handling (anchoring to `last_seen`, no forecast)
- Filters (location, MAC, status, reset)
- Compliance calculations (total-based %, 7-day trend with filled dates)
- Forecast generation and alerts
- Alert lifecycle (creation, resolution, dismissal, history, cooldown)
- KPIs (all values, edge cases)
- Chart rendering (axis ranges, empty data annotation, downsampling)
- UI callbacks (banner, status bar, grid, chart, compliance, range bar, alert table)
- Authentication (cookie creation, verification, expiry, token hints)
- Timestamp formatting (`_fmt_time` edge cases, no "Z" suffix)
- Provider caching and DB connection health

### Running Tests

```bash
cd dashboard
python -m pytest tests/ -v        # 161 unit tests
python -m ruff check app/ tests/  # lint (0 errors)
```
