# TempMonitor — Complete Backend Architecture & Feature Documentation

## 1. Multi-Tenancy Model

```
Customer (Server)                   ← Physical server (e.g., server1, server2)
 └── Processing Unit (Singleton)    ← One deployment per server
      └── Client A                  ← customer_key in DB = client_id in code
      │    ├── Facility / Dorm 1    ← "name" column in dg_gateway_data
      │    │    ├── Sensor MAC-1
      │    │    └── Sensor MAC-2
      │    └── Facility / Dorm 2
      │         └── Sensor MAC-3
      └── Client B
           └── Facility / Dorm 3
                └── Sensor MAC-4
```

**Key mapping:**
- `customer_key` (DB column) = `client_id` (code) — isolates all data per client
- `name` (DB column) = Location / Facility label — groups sensors within a client
- `mac` (DB column) = Unique sensor identifier
- `mac_type = 'Temp-Sensor'` — all queries filter on this

**Singleton processing:** One `HybridProvider` instance is cached per `client_id`. All clients on the same server share the same Lambda/container process but get fully isolated data paths.

---

## 2. Data Source Table — `dg_gateway_data`

| Column | Type | Purpose |
|--------|------|---------|
| `mac` | VARCHAR | Sensor MAC address (unique per physical device) |
| `mac_type` | VARCHAR | Device type filter — we only use `'Temp-Sensor'` |
| `body_temperature` | FLOAT | Temperature reading in °F |
| `rssi` | INT | Received signal strength (dBm) |
| `power` | VARCHAR | Battery level / power indicator |
| `date_added` | DATETIME | Timestamp of reading (UTC) |
| `tags_id` | INT | Legacy location tag (joins to `dg_tags` → `dg_locations`) |
| `gateway_mac` | VARCHAR | Receiving gateway MAC |
| `customer_key` | VARCHAR | **Tenant key** — maps to `client_id` |
| `name` | VARCHAR | **Location/Facility name** — groups sensors geographically |

---

## 3. Request Lifecycle — End to End

### 3.1 Authentication Flow

```
Officer clicks access URL
     │
     ▼
GET /connect/<token>              ← routes.py:connect()
     │
     ├─► resolve_token(token)     ← auth.py: looks up Secrets Manager cache
     │   TempMonitor/{deploy_id}/{client_id} → {access_token, client_id, client_name}
     │
     ├─► create_cookie()          ← HMAC-SHA256 signed, base64-encoded payload
     │   payload = {cid, cn, token_hint (first 8 chars), exp (30 days)}
     │
     └─► Set HttpOnly cookie → redirect to /
```

**Every subsequent request:**
```
Browser sends cookie → auth_middleware() (routes.py)
     │
     ├─ Non-AWS mode: g.client_id = "demo_client_1" (bypasses auth)
     │
     └─ AWS mode:
         ├─► verify_cookie() → check HMAC signature + expiry
         ├─► validate_token_hint() → compare token[:8] with current secret
         └─► Set g.client_id, g.client_name → available to all callbacks
```

**Token management:** `scripts/manage_client.py` provides CLI for add/list/remove/rotate operations via Secrets Manager.

### 3.2 Provider Factory

```
get_provider(client_id)           ← provider.py
     │
     ├─ if client_id in _providers cache → return cached instance
     └─ else → HybridProvider(client_id)
              └─ cache it in _providers[client_id]
```

One `HybridProvider` per `client_id`, cached for the process lifetime. Contains its own:
- Alert manager (DynamoDB-backed)
- Sensor state cache (20s TTL)
- Readings cache (60s TTL)
- Location cache (120s TTL for location list, 300s for tag map)

### 3.3 Data Pump Pattern

The dashboard uses a **single callback** (`data_pump`) that fires every 10 seconds (configurable via `REFRESH_MONITOR_MS`). It fetches ALL data in one round-trip and stores it in client-side `dcc.Store` components. All display callbacks are pure renderers — zero server calls.

```
dcc.Interval (10s tick)
     │
     ▼
data_pump callback                ← monitor.py:data_pump()
     │
     ├─► prov.get_all_sensor_states()     → store-states
     ├─► prov.get_live_alerts()           → store-alerts
     ├─► prov.get_compliance_history(7)   → store-compliance
     └─► _fetch_readings(selected_sensor) → store-readings
              ├─► prov.get_readings()
              ├─► prov.get_forecast_series()
              └─► prov.get_alert_history()
```

**Display callbacks** (pure render, read from stores only):
```
store-states  ──► render_banner()   → Banner: online/total, alerts, avg temp, low battery
store-states  ──► render_grid()     → Sensor tile grid (sorted: critical first)
store-alerts  ──► render_alerts()   → Alert cards with Note/Remove actions
store-readings ─► render_kpis()     → KPI row: high, low, avg, trend, forecast, compliance
store-readings ─► render_chart()    → Unified plotly chart
store-states  ──► render_compliance() → Gauge + 7-day trend
store-readings ─► render_alert_table() → Historical alert table
```

---

## 4. Feature Deep Dive

### 4.1 Sensor State Computation

**File:** `hybrid_provider.py:get_all_sensor_states()` → `analytics.py:build_sensor_state()`

**Lifecycle:**
1. `fetch_latest_per_sensor(customer_key)` — Gets the most recent row per MAC from `dg_gateway_data` (self-join on MAX date_added, grouped by mac)
2. `fetch_batch_history(mac_list, since_1h, customer_key)` — Gets all readings for these MACs from the past 1 hour (batch query)
3. For each sensor, `build_sensor_state()` computes:

| Field | Computation |
|-------|-------------|
| `temperature` | `float(row["body_temperature"])` |
| `status` | `compute_sensor_status(age_sec)`: online (<120s), degraded (120-300s), offline (>300s) |
| `rolling_avg_1h` | `np.mean()` of all readings in last 1 hour |
| `actual_high_1h` | `np.max()` of 1-hour window |
| `actual_low_1h` | `np.min()` of 1-hour window |
| `rate_of_change` | Temperature delta over last 10 minutes: `temp_now - temp_10min_ago` |
| `anomaly` | Z-score > 2.5 OR exceeds critical thresholds (95°F high, 50°F low) |
| `anomaly_reason` | Human-readable explanation |
| `signal_label` | From RSSI: Strong (≥-50), Good (≥-65), Weak (≥-80), No Signal (<-80) |
| `battery_pct` | Parsed from `power` column, clamped 0-100 |
| `location` | `row["name"]` or legacy `loc_info["zone_label"]` from `dg_tags` join |
| `zone_id`, `facility_id` | From `dg_tags` → `dg_locations` legacy mapping |
| `client_id` | Passed through for multi-tenancy |

**Caching:** Results cached for 20 seconds (avoids DB hits on every data pump cycle).

### 4.2 Readings Fetch (Hybrid Approach)

**File:** `hybrid_provider.py:get_readings()` → `parquet_reader.py` / `mysql_reader.py`

**Data source selection** (controlled by `DATA_SOURCE` env var):

```
DATA_SOURCE = "mysql"    → MySQL only
DATA_SOURCE = "parquet"  → Parquet only
DATA_SOURCE = "hybrid"   → Parquet first, MySQL fallback
```

**Lifecycle:**
```
get_readings(device_id, since_iso, until_iso)
     │
     ├─► Check readings cache (key: "device_id|since|until", TTL: 60s)
     │
     ├─► If parquet mode:
     │    └─ parquet_reader.readings_for_device(bucket, prefix, mac, since, until)
     │         ├─ read_range() → reads daily Parquet files from S3
     │         │   s3://{bucket}/{prefix}{YYYY-MM-DD}.parquet
     │         ├─ Each file cached in-memory for 120 seconds
     │         └─ Filter: mac == device_id AND date_added >= since
     │
     ├─► If no parquet results AND mysql mode:
     │    └─ mysql_reader.fetch_readings_range(device_id, start, end, limit=3000)
     │       OR fetch_readings(device_id, since) for open-ended queries
     │
     └─► Return [{timestamp: ISO, temperature: float}, ...]
```

**MySQL queries used:**
- `fetch_readings(mac, since)` — Open-ended: all readings since a cutoff, ordered ASC
- `fetch_readings_range(mac, start, end, limit=3000)` — Bounded range with cap to prevent huge responses
- `fetch_max_date(mac)` — Finds the most recent timestamp for a device (used by forecast)

### 4.3 Anomaly Detection

**File:** `analytics.py:is_anomaly()`

**Two-layer detection:**
1. **Threshold-based** (hard limits):
   - `temp > 95.0°F` → Critical high anomaly
   - `temp < 50.0°F` → Critical low anomaly
2. **Statistical (Z-score)**:
   - If `std > 0`: compute `z = |temp - avg| / std`
   - If `z > 2.5` → Statistical anomaly
   - Uses the 1-hour rolling window statistics

**Output:** `(is_anomaly: bool, reason: str | None)`

### 4.4 Temperature Forecasting

**File:** `analytics.py:forecast_params()`, `forecast_point()`, `forecast_series()`

**Model:** Simple linear extrapolation with confidence intervals.

**Lifecycle:**
```
get_forecast(device_id, horizon)
     │
     ├─► fetch_max_date(device_id) → most recent timestamp
     ├─► get_readings(device_id, max_date - 30min) → recent readings
     ├─► forecast_params(readings)
     │    ├─ Requires ≥ 5 readings
     │    ├─ level = last temperature value
     │    ├─ trend = slope from np.polyfit(x, y, degree=1)
     │    └─ residual_std = np.std(y, ddof=1)
     │
     └─► forecast_point(params, horizon)
          ├─ steps = 30 (for "30min") or 120 (for "2h")
          ├─ predicted = level + trend × steps
          ├─ CI = ±1.96 × std × √steps × 0.1
          └─ Returns: {predicted_temp, ci_lower, ci_upper, steps, model_params}
```

**Series forecast** (for chart): Generates step-by-step predictions for 1..N minutes into the future, each with its own confidence interval.

**When shown:** Only in "LIVE" mode when the sensor is online.

### 4.5 Alert Management

**File:** `alert_manager.py` (AlertManager class)

**Storage:** DynamoDB table with PK/SK composite key + GSI on `client_id + state_triggered`.

**Alert conditions** (evaluated every data pump cycle):

| Alert Type | Severity | Trigger Condition |
|------------|----------|-------------------|
| `EXTREME_TEMPERATURE` | CRITICAL | `temp > 95.0°F` (critical_high) |
| `EXTREME_TEMPERATURE_LOW` | CRITICAL | `temp < 50.0°F` (critical_low) |
| `SUSTAINED_HIGH` | HIGH | `95.0 ≥ temp > 85.0` |
| `LOW_TEMPERATURE` | MEDIUM | `50.0 ≤ temp < 65.0` |
| `SENSOR_OFFLINE` | HIGH | `status == "offline"` |
| `RAPID_CHANGE` | MEDIUM | `|rate_of_change| > 4.0°F in 10 min` |

**State machine:**
```
              trigger condition met
                     │
                     ▼
    ┌─────────── ACTIVE ───────────┐
    │                              │
    │ condition resolves      officer action
    │                              │
    ▼                              ▼
 RESOLVED                     DISMISSED
 (auto)                       (manual)
                               │
                               └─► Cooldown (300s) — same alert won't re-fire
```

**Lifecycle:**
1. `evaluate(sensor_states)` — Called every data pump cycle
   - For each sensor × each condition: check if triggered
   - If triggered AND not in memory AND not in cooldown → `_create_alert()` → DynamoDB put_item
   - If NOT triggered AND was ACTIVE → `_resolve_alert()` → DynamoDB update_item
2. On cold start: `_load_active()` → Query GSI `ClientActiveAlerts` → hydrate `_memory` dict

**Officer actions:**
- **"Remove" (Dismiss):** `dismiss(device_id, alert_type)` → Sets state=DISMISSED in DynamoDB, starts cooldown timer, moves to resolved history
- **"Note" (Create Note):** `send_note_and_dismiss(device_id, alert_type, context)` → Invokes `NOTE_LAMBDA_ARN` asynchronously with full context (sensor state, timestamps, etc.), then auto-dismisses

**DynamoDB schema:**
```
PK:               ALERT#{device_id}#{alert_type}
SK:               ISO timestamp (triggered_at)
GSI (ClientActiveAlerts):
  client_id:      Partition key
  state_triggered: Sort key (e.g., "ACTIVE#2026-03-11T...")
TTL:              90 days
```

**Local development:** Uses `moto` (AWS mock library) to create an in-process DynamoDB table — same code path, zero AWS dependency.

### 4.6 Compliance Tracking

**File:** `hybrid_provider.py:get_compliance_history()` → `mysql_reader.py:fetch_compliance_batch()`

**What it measures:** Percentage of temperature readings within the safe range (65-85°F) per day.

**Lifecycle:**
```
get_compliance_history(days=7)
     │
     ├─► If parquet: parquet_reader.compliance_for_range()
     │    └─ Groups by day, counts total vs. compliant readings
     │
     └─► If mysql: fetch_compliance_batch(start, end, temp_low, temp_high, customer_key)
          └─ SQL: GROUP BY DATE(date_added), COUNT(*) as total,
                  SUM(CASE WHEN body_temperature BETWEEN 65 AND 85 THEN 1 ELSE 0 END) as compliant
```

**Dashboard display:**
- **Gauge:** Current compliance percentage (all active sensors, real-time)
- **7-day trend line:** Daily compliance percentages, spline chart, target line at 95%
- **Stats row:** Total sensors, in-range count, out-of-range, too hot, too cold

### 4.7 Location & MAC Filtering

**File:** `mysql_reader.py:fetch_distinct_locations()`, `fetch_sensors_by_location()`

**Lifecycle:**
```
Dashboard loads → load_locations callback (every 10s tick)
     │
     ├─► prov.get_locations() → fetch_distinct_locations(customer_key)
     │   SQL: SELECT DISTINCT name FROM dg_gateway_data
     │        WHERE mac_type='Temp-Sensor' AND name IS NOT NULL
     │        AND customer_key = %s ORDER BY name
     │   Cache: 120s TTL
     │
     └─► Populates "Facility / Location" dropdown options
```

**Cascading MAC filter:**
```
User selects location in dropdown
     │
     ▼
update_mac_options callback
     │
     ├─► Filters store-states by location match
     └─► Populates "Sensor / MAC" dropdown with filtered MACs only
```

**Reset:** Clears both dropdowns, date picker, and returns to "LIVE" mode.

### 4.8 Time Range Selection

**Quick buttons:** LIVE, 1h, 6h, 12h, 24h

**Date range picker:** Custom start/end up to 4 months (120 days) back.

**Interaction model:**
- Clicking a quick button → clears date picker, sets `range-mode` to button value
- Selecting dates in picker → sets `range-mode` to "custom", stores `{start, end}`
- Clicking "Reset" → clears everything, returns to LIVE

**How range affects data fetch:**
```
range_mode = "live"   → readings from (now - 2h) to now + forecast
range_mode = "1"      → readings from (now - 1h) to now, no forecast
range_mode = "6"      → readings from (now - 6h) to now, no forecast
range_mode = "custom" → readings from start_date to end_date+23:59, no forecast
```

Forecast is **only shown in LIVE mode** for online sensors.

---

## 5. Chart Rendering

**File:** `charts.py`

### 5.1 Unified Chart

**Layers (bottom to top):**
1. **Safe zone** — Shaded area between TEMP_LOW (65°F) and TEMP_HIGH (85°F)
2. **Actual readings** — Solid line (or dotted if offline)
3. **Forecast** — Dotted line + confidence interval band (LIVE mode only)
4. **Threshold lines** — "Too Hot" (85°F) and "Too Cold" (65°F) horizontal dashes
5. **High/Low reference** — Actual max/min from data, staggered annotations
6. **Alert markers** — Severity-colored diamonds at alert timestamps
7. **Marker line** — "Now" (live) or "Last Reading" (offline) vertical dash

**Downsampling:** For datasets >2000 points, applies min-max-mean bucketing that preserves peaks and valleys.

### 5.2 Compliance Charts
- **Gauge:** go.Indicator with target threshold at 95%
- **Trend:** 7-day spline line with colored markers (green if ≥ target, orange if below)

---

## 6. Dashboard UI Layout

```
┌─────────────────────────────────────────────────┐
│  ⬡ TEMPMONITOR              Mar 11, 2026  ●LIVE │  ← Sticky navbar + live clock
├─────────────────────────────────────────────────┤
│  NEEDS ATTENTION   5/13 Sensors  2 Alerts  74°F │  ← Status banner
├─────────────────────────────────────────────────┤
│  [Location ▼]  [Sensor/MAC ▼]  [Date Range ▼]  │  ← Filter bar
│  [↺ Reset]                                      │
├─────────────────────────────────────────────────┤
│  ⚠ 2 Alerts for SIM0A006                       │  ← Sensor-specific alerts
│  [Urgent] Temp 91.2°F — exceeds safe limit      │    with Note / Remove buttons
│  [📋 Note] [✕ Remove]                          │
├─────────────────────────────────────────────────┤
│  ☉ 13 Sensors  [Show All toggle]                │  ← Sensor grid
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐           │    Sorted: critical first
│  │SIM001│ │SIM006│ │SIM007│ │SIM008│ ...        │    Color-coded borders
│  │73.0°F│ │89.0°F│ │90.5°F│ │61.0°F│           │    Click to select
│  │Fac.M │ │Blk.N │ │Blk.N │ │Blk.S │           │    Location label on each tile
│  └──────┘ └──────┘ └──────┘ └──────┘           │
├─────────────────────────────────────────────────┤
│  ● ONLINE  SIM0A0000006 • 02-Block North 89.0°F│  ← KPI header + 8 metrics
│  High  Low  Average  Trend  Forecast  InRange   │
│  91.2  87.3  89.4    ↑Rise  92.1°F    78.5%    │
│  Battery  Signal                                │
│  45%      Good                                  │
├─────────────────────────────────────────────────┤
│  [LIVE] [1h] [6h] [12h] [24h]                  │  ← Range buttons
├─────────────────────────────────────────────────┤
│  ╭──────────── Unified Chart ──────────────╮    │  ← Temperature chart
│  │  Safe zone (65-85°F shaded)             │    │    + forecast line
│  │  ── Actual readings                     │    │    + alert markers
│  │  ·· Forecast (LIVE only)                │    │    + threshold lines
│  │  ◆ Alert markers                        │    │
│  ╰─────────────────────────────────────────╯    │
├─────────────────────────────────────────────────┤
│  ┌─ Live Compliance ─┐  ┌──── 7-Day Trend ────┐│  ← Compliance section
│  │    [Gauge 88.5%]  │  │  ── Trend line ──    ││
│  │  Total InRange Out│  │  ·· Target 95%       ││
│  └───────────────────┘  └──────────────────────┘│
├─────────────────────────────────────────────────┤
│  Alert History (DataTable, sortable, paginated) │  ← Alert history table
│  Priority | Type | What | When | Status         │
└─────────────────────────────────────────────────┘
```

---

## 7. Module Inventory

### Backend Data Layer

| Module | LOC | Responsibility | Caching |
|--------|-----|----------------|---------|
| `provider.py` | 38 | DataProvider protocol + factory | Per-client_id instance cache |
| `hybrid_provider.py` | 262 | Orchestrator: routes to MySQL/Parquet, runs analytics, delegates alerts | States: 20s, Readings: 60s, Locations: 120s, Tags: 300s |
| `mysql_reader.py` | 223 | Thread-local pymysql pool, all SQL queries for dg_gateway_data | Connection reuse: 50s max age, auto-retry on broken pipe |
| `parquet_reader.py` | 110 | S3 daily Parquet files, pandas-based | Per-file: 120s in-memory cache |
| `analytics.py` | 175 | Stateless math: rolling stats, anomaly, forecast | None (pure functions) |
| `alert_manager.py` | 250 | DynamoDB alert lifecycle, evaluate/dismiss/note | In-memory `_memory` dict + DynamoDB persistence |

### Authentication & Routing

| Module | LOC | Responsibility |
|--------|-----|----------------|
| `auth.py` | 134 | Secrets Manager token resolution, HMAC cookie sign/verify |
| `routes.py` | 104 | Flask before_request auth middleware, /connect, /disconnect, /healthz |
| `config.py` | 90 | All env vars, theme colors, thresholds, SVG icons |

### Dashboard UI

| Module | LOC | Responsibility |
|--------|-----|----------------|
| `main.py` | 64 | Dash app creation, navbar, live clock callback |
| `monitor.py` | 719 | Single-page layout, data pump, all display callbacks, filter callbacks |
| `charts.py` | 284 | Plotly figure builders: unified_chart, compliance_gauge, compliance_trend |
| `style.css` | ~100 | Dark theme CSS for dropdowns and date picker |

### Infrastructure & Scripts

| File | LOC | Purpose |
|------|-----|---------|
| `template.yaml` | 196 | SAM: DynamoDB table, API Gateway, Lambda, CloudWatch alarm |
| `samconfig.toml` | ~150 | Deploy configs per environment (dev, staging, prod-a/b/c, govcloud) |
| `ci.yml` | ~80 | GitHub Actions: lint, test, SAM validate, auto-deploy dev/staging |
| `cd.yml` | ~120 | GitHub Actions: tag-based prod deploy with approval gates |
| `action.yml` | ~140 | Composite action: OIDC auth, SAM build/deploy, health checks |
| `manage_client.py` | 213 | CLI for Secrets Manager client CRUD operations |
| `sensor_simulator.py` | 379 | Standalone in-memory simulator (no DB, implements DataProvider) |

---

## 8. Connection & Query Patterns

### MySQL Connection Pool (`mysql_reader.py`)

```
Thread-local storage (_tls)
     │
     ├─ _tls.c → pymysql connection
     └─ _tls.ts → creation timestamp
```

- Connections reused for up to 50 seconds, then recycled
- Every `query()` call: try once → if connection error → close + reconnect + retry
- `DictCursor` — all results returned as `list[dict]`
- `autocommit=True` — read-only workload, no transaction management

### Multi-Tenant SQL Filtering

Every SQL query uses `_ck_clause(customer_key)`:
```python
def _ck_clause(customer_key):
    if customer_key and customer_key != "default":
        return " AND customer_key=%s", (customer_key,)
    return "", ()
```

This appends `AND customer_key = %s` to WHERE clauses when a client_id is present, ensuring complete data isolation between tenants.

---

## 9. Deployment Architecture

### Serverless (AWS Lambda)

```
                  ┌─────────────┐
                  │  API Gateway │  (HttpApi, $default stage)
                  │  (HTTPS)     │
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │   Lambda     │  512MB, 30s timeout
                  │  Dashboard   │  handler: lambda_handler.handler
                  │              │  serverless-wsgi wraps Flask/Dash
                  └──────┬──────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐  ┌───────────┐  ┌──────────┐
    │  Aurora   │  │ DynamoDB  │  │    S3    │
    │  MySQL    │  │ (Alerts)  │  │(Parquet) │
    │  (RDS)    │  │           │  │          │
    └──────────┘  └───────────┘  └──────────┘
```

### CI/CD Pipeline

```
PR/push → ci.yml
  ├─ ruff lint
  ├─ pytest (py3.10 + py3.12)
  ├─ SAM validate
  ├─ Auto-deploy: develop → dev, main → staging

Tag v* → cd.yml
  ├─ Pre-deploy tests
  ├─ Deploy: prod-a, prod-b, prod-c (sequential, approval-gated)
  └─ Deploy: govcloud-prod (separate approval)
```

### Local Development

```bash
# Production code
make run     # gunicorn -w 1 --threads 4 -b 0.0.0.0:8051

# Testing with simulator (no DB needed)
python sensor_simulator.py --port 8060
```

---

## 10. Offline Sensor Handling

When a sensor stops sending data:

1. **Detection:** `compute_sensor_status(age_sec)` checks time since last reading
   - 0-120s → `online`
   - 120-300s → `degraded` (yellow indicator)
   - >300s → `offline` (grey indicator)

2. **Alert:** `SENSOR_OFFLINE` alert fires automatically (severity: HIGH)

3. **Dashboard behavior:**
   - Tile shows grey border with `*` suffix on temperature
   - Chart uses dotted line for last known readings
   - "Last Reading" marker line instead of "Now"
   - Forecast is disabled
   - KPI shows "Last Reading" instead of "Forecast"
   - Reading window anchored to `last_seen` timestamp (not current time)

4. **Recovery:** When sensor comes back online:
   - Status transitions back to `online`
   - `SENSOR_OFFLINE` alert auto-resolves
   - Chart switches to solid line + forecast resumes
   - All metrics recalculate from fresh data

---

## 11. Environment Variables Reference

| Variable | Default | Used By |
|----------|---------|---------|
| `AWS_MODE` | `false` | Auth (cookie vs demo), alert table creation |
| `DATA_SOURCE` | `mysql` | HybridProvider: mysql / parquet / hybrid |
| `MYSQL_HOST` | `localhost` | mysql_reader.py |
| `MYSQL_PORT` | `3306` | mysql_reader.py |
| `MYSQL_USER` | `root` | mysql_reader.py |
| `MYSQL_PASSWORD` | `""` | mysql_reader.py |
| `MYSQL_DATABASE` | `Demo_aurora` | mysql_reader.py |
| `PARQUET_BUCKET` | `""` | parquet_reader.py |
| `PARQUET_PREFIX` | `sensor-data/` | parquet_reader.py |
| `ALERTS_TABLE` | `""` | alert_manager.py (auto-generates local name if empty) |
| `NOTE_LAMBDA_ARN` | `""` | alert_manager.py (logs locally if empty) |
| `DEPLOYMENT_ID` | `0000000000` | auth.py (Secrets Manager path) |
| `COOKIE_SECRET` | `local-dev-secret-key` | auth.py (HMAC signing) |
| `ENVIRONMENT` | `dev` | config.py, SAM template |

---

## 12. Test Coverage

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_analytics.py` | 18 | signal_label, compute_rolling, rate_of_change, is_anomaly, sensor_status, build_sensor_state, forecast_params, forecast_point |
| `test_alert_manager.py` | 14 | evaluate (all 6 conditions), dismiss, send_note, get_history, cooldown |
| `test_auth.py` | 24 | Cookie sign/verify, create/verify roundtrip, expiry, token map, resolve_token, validate_hint |
| `test_monitor.py` | 38 | Banner, grid, KPIs, chart, alerts, compliance, alert table, range bar, toggle, location filter, date range, provider locations |
| `test_provider.py` | 8 | Protocol methods, factory, MockProvider basics |
| `test_config.py` | 5 | Colors, thresholds, card style, SVG icons |
| `test_routes.py` | 7 | Auth middleware, disconnect, healthz, layout, clock |
| `test_lambda_handler.py` | 4 | Lambda handler import, basic request |
| **Total** | **~118** | |

---

## 13. File Statistics

| Category | Files | Total LOC |
|----------|-------|-----------|
| Backend data layer | 6 | ~1,058 |
| Auth & routing | 3 | ~328 |
| Dashboard UI | 3 | ~1,067 |
| CSS assets | 1 | ~100 |
| Infrastructure | 5 | ~590 |
| Scripts | 1 | 213 |
| Tests | 10 | ~1,155 |
| Simulator | 1 | 379 |
| **Total** | **30** | **~4,890** |
