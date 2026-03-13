# TempMonitor — Correctional Facility Temperature Sensor Platform

Serverless single-page dashboard for monitoring temperature sensors in correctional facilities.
Hybrid data architecture (MySQL Aurora / S3 Parquet), DynamoDB-backed alert management,
multi-tenant client isolation with location-based filtering, and officer-friendly UI
designed for real-time operational awareness.

## Architecture

```
┌──────────────┐     ┌────────────────────────────────┐     ┌──────────────┐
│  S3 Parquet  │────▶│                                │◀───▶│  DynamoDB    │
│  (10-min     │     │     Dashboard (Dash + Flask)   │     │  (Alerts)    │
│   interval)  │     │                                │     └──────────────┘
└──────────────┘     │  ┌──────────┐  ┌────────────┐  │
                     │  │ Hybrid   │  │ Analytics  │  │     ┌──────────────┐
┌──────────────┐     │  │ Provider │  │  Engine    │  │────▶│  Lambda X    │
│  MySQL       │────▶│  └──────────┘  └────────────┘  │     │  (Notes)     │
│  Aurora RDS  │     │                                │     └──────────────┘
│(dg_gateway_  │     │  ┌──────────┐  ┌────────────┐  │
│  data table) │     │  │  Alert   │  │  Charts    │  │
└──────────────┘     │  │ Manager  │  │  (Plotly)  │  │
                     │  └──────────┘  └────────────┘  │
                     └────────────────────────────────┘
                                │
                     ┌──────────┴──────────┐
                     │   API Gateway / ALB  │
                     └─────────────────────┘
```

### Data Flow — Hybrid Provider

| Flag (`DATA_SOURCE`) | Live readings | Historical (custom range) | Notes |
|---|---|---|---|
| `mysql` | MySQL only | MySQL only | Default; simplest setup |
| `parquet` | Parquet only | Parquet only | Fastest for large datasets |
| `hybrid` | Parquet → MySQL fallback | Parquet for past days, MySQL for today | Best of both worlds |

The `HybridProvider` manages the routing transparently. Readings are cached for 60s
keyed by `(device_id, range)`. Sensor states are cached for 15s. All cache TTLs are
centralised in `config.py`.

### Database Table — `dg_gateway_data`

| Column | Purpose |
|---|---|
| `mac` | Sensor MAC address (device identifier) |
| `mac_type` | Device type — filtered to `Temp-Sensor` |
| `customer_key` | Client/tenant identifier (**DB column** — app code uses `client_id` everywhere) |
| `name` | Facility / location name (used for location filter) |
| `body_temperature` | Temperature reading (°F) |
| `rssi` | Signal strength (dBm) |
| `power` | Battery level |
| `tags_id` | Tag identifier (links to legacy `dg_tags` table) |
| `date_added` | Timestamp of the reading |

The DB column `customer_key` is mapped to `client_id` once in `mysql_reader._client_clause()`.
All application code uses `client_id` consistently. For shared-DB clients the SQL filter
`AND customer_key=%s` is added; for isolated-DB clients (own database) no filter is needed.

### Single-Page UI Layout

```
┌──────────────────────────────────────────────────────────────┐
│ ◉ TEMPMONITOR                        Mar 12, 2026  ● LIVE   │
├──────────────────────────────────────────────────────────────┤
│ [All Facilities]  10/13 Sensors  6 Alerts  77.5°F Avg        │
├──────────────────────────────────────────────────────────────┤
│ FACILITY ▼  │ SENSOR ▼  │ 📅 Date Range │ ↺ Reset           │
├──────────────────────────────────────────────────────────────┤
│ ☉ 13 Sensors  [All 13] [Critical 6] [Warning 0] [Normal 7]  │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ...             │
│ │ 95.8°F │ │ 95.2°F │ │ 89.2°F │ │ 73.0°F │                 │
│ │ F.Mstr │ │ F.Mstr │ │ B.Nrth │ │ F.Mstr │                 │
│ └────────┘ └────────┘ └────────┘ └────────┘                  │
├──────────────────────────────────────────────────────────────┤
│ ⚠ 2 Alerts for SIM0A0000007                                  │
│  [Important] Temperature 93.2°F — above normal                │
│  [📋 Note] [✕ Remove]                                        │
├──────────────────────────────────────────────────────────────┤
│ ● ONLINE  SIM0A0000007 • 02-Block North  93.2°F              │
│ [HIGH] [LOW] [AVG] [TREND] [FORECAST] [IN RANGE] [BAT] [SIG]│
├──────────────────────────────────────────────────────────────┤
│ [LIVE] [1h] [6h] [12h] [24h]                                 │
├──────────────────────────────────────────────────────────────┤
│ ━━━━━━━ Unified Chart (Actual + Forecast + Alert Markers) ━━ │
│  Safe zone shading (65–85°F) | Too Hot / Too Cold thresholds  │
│  Forecast dotted line with glow + CI band                     │
│  Alert ◆ diamonds color-coded by severity                     │
├──────────────────────────────────────────────────────────────┤
│ [Compliance Gauge 70%]       │  [7-Day Compliance Trend]      │
│ Total 13 | In Range 7        │  Line chart with target 95%    │
│ Issue 3 | Hot 2 | Cold 1     │                                │
│ Offline 3                    │                                │
├──────────────────────────────────────────────────────────────┤
│ Alert History Table                                           │
│  Priority | Type | What | When | Status                       │
└──────────────────────────────────────────────────────────────┘
```

### Filter System

**Location/Facility Filter** (dropdown + search):
- Populated from the `name` column in `dg_gateway_data` for the current `client_id`
- Selecting a location narrows the sensor grid, MAC dropdown, and banner stats
- Searchable — type to find a location quickly

**Sensor/MAC Filter** (dropdown + search):
- Cascading: options update based on selected location
- If no location selected, all sensors appear
- Selecting a sensor directly highlights it and loads its data

**Date Range Picker**:
- Calendar-based start/end date selection (max 120 days back)
- Selecting dates replaces the quick-button range mode with "custom"

**Status Filter** (color-coded buttons):
- **All** — show every sensor
- **Critical** (red dot) — only sensors with alerts or out-of-range temps
- **Warning** (yellow dot) — anomaly, low battery, or degraded
- **Normal** (green dot) — healthy sensors only

**Reset Button**: clears all filters (location, MAC, date range) and returns to LIVE mode.

### Time Range Modes

| Button | Behavior |
|---|---|
| **LIVE** (green pulse) | Auto-refreshes every 15s, shows last 2h + 30-min forecast |
| **1h / 6h / 12h / 24h** | Single fetch, cached, no auto-refresh for readings |
| **Date Range Picker** | Custom start/end dates (up to 120 days back), single fetch |

### Callback Architecture — Split Data Pump

```
  15s Interval ─── state_pump ──▶ Store: states
                                  Store: alerts
                                  Store: compliance
                                       │
  Sensor Click ─┐                      │
  Range Click ──┤── readings_pump ──▶ Store: readings (+ forecast + alert history)
  Date Range ───┘                      │
                        ┌──────────────┼────────────────────┐
                        ▼              ▼                    ▼
                  render_banner   render_chart    render_compliance
                  render_grid    render_kpis     render_alert_table
                  render_alerts  render_range_bar
```

**Performance strategy**:
- `state_pump` runs on every tick (15s) — fetches sensor states, alerts, and compliance
- `readings_pump` runs on user interaction (sensor select, range change) — fetches readings for ONE sensor
- `readings_pump` skips fetches when triggered by tick in non-LIVE mode (`no_update` shortcut)
- Clientside callbacks handle filter/range/select interactions (zero server round-trip)
- Display callbacks are pure renderers from `dcc.Store` objects (no DB calls)

### Module Structure

```
TemperatureSensor/
├── README.md                     This file
├── DEPLOY.md                     Full deployment guide
├── info.md                       Deep-dive technical documentation
├── clients.yaml                  Client registry (single source of truth)
├── requirements-dev.txt          Dev dependencies (pytest, ruff)
├── sensor_simulator.py    (488)  Standalone simulator (10 live + 3 offline sensors)
├── scripts/
│   ├── manage_client.py   (213)  Client CRUD via Secrets Manager (add/list/remove/rotate)
│   ├── onboard_client.sh  (158)  Automated onboarding (Secrets + DynamoDB + registry)
│   └── setup_server.sh    (155)  Automated server deployment (SAM build + deploy)
├── infra/
│   └── template.yaml      (200)  SAM CloudFormation template
└── dashboard/
    ├── lambda_handler.py    (9)  AWS Lambda entry point (serverless-wsgi)
    ├── pyproject.toml             Ruff + pytest config
    ├── requirements.txt           Runtime dependencies
    ├── app/
    │   ├── config.py       (143) Centralised config: env vars, thresholds, cache TTLs,
    │   │                         theme colours, chart defaults, SVG icons
    │   ├── auth.py         (134) Cookie signing, Secrets Manager token resolution
    │   ├── routes.py       (109) Flask middleware, /connect, /disconnect, /healthz
    │   ├── main.py         (106) Dash app creation, navbar, clock callback
    │   ├── assets/
    │   │   └── style.css   (321) Light theme: cards, filters, animations, calendar
    │   ├── data/
    │   │   ├── provider.py  (38) DataProvider protocol + factory (per-client cache)
    │   │   ├── client_registry.py (160) Client config loader (clients.yaml + env fallback)
    │   │   ├── mysql_reader.py (255) Per-client connection pool + all SQL queries
    │   │   ├── parquet_reader.py (111) S3 daily Parquet with in-memory cache
    │   │   ├── analytics.py (175) Stats, anomaly detection, forecasting (stateless)
    │   │   ├── alert_manager.py (250) DynamoDB lifecycle (moto locally)
    │   │   └── hybrid_provider.py (282) Orchestrator: routing + caching + analytics
    │   └── pages/
    │       ├── charts.py   (348) unified_chart(), compliance_gauge(), compliance_trend()
    │       └── monitor.py (1098) Single-page: layout, filters, callbacks, all UI
    └── tests/
        ├── conftest.py      (44) Flask context + MockProvider fixture
        ├── mock_provider.py (111) Deterministic 3-sensor + 2-location mock
        └── unit/
            ├── test_alert_manager.py (132) Alert lifecycle, cooldown, note/dismiss
            ├── test_analytics.py     (148) Signal, rolling, anomaly, forecast
            ├── test_auth.py          (249) Cookie HMAC, tokens, expiry, hints
            ├── test_config.py         (35) Theme + threshold validation
            ├── test_lambda_handler.py (49) Lambda handler (skip if no serverless_wsgi)
            ├── test_monitor.py       (325) All callbacks, filters, compliance, alerts
            ├── test_provider.py       (75) Protocol + factory + mock
            └── test_routes.py         (66) Flask routes + middleware
```

Total: **~3,200 lines of application code**, **~1,234 lines of test code**, **161 unit tests**.

### Alert System

| State | Trigger | DynamoDB | Live UI |
|---|---|---|---|
| **ACTIVE** | Condition fires (temp > threshold, offline, etc.) | `put_item` | Alert card with severity badge |
| **RESOLVED** | Condition clears automatically | `update_item` → RESOLVED | Disappears from live |
| **DISMISSED** | Officer clicks "Remove" | `update_item` → DISMISSED | Disappears + 5-min cooldown |
| **NOTE + DISMISS** | Officer clicks "Note" | Sends context to Lambda X → auto-dismiss | Green checkmark → disappears |

Alert conditions evaluated every 15 seconds:

| Alert Type | Severity | Condition |
|---|---|---|
| `EXTREME_TEMPERATURE` | CRITICAL | Temp > 95°F |
| `EXTREME_TEMPERATURE_LOW` | CRITICAL | Temp < 50°F |
| `SUSTAINED_HIGH` | HIGH | 85°F < Temp ≤ 95°F |
| `LOW_TEMPERATURE` | MEDIUM | 50°F ≤ Temp < 65°F |
| `SENSOR_OFFLINE` | HIGH | Sensor not responding > 5 min |
| `RAPID_CHANGE` | MEDIUM | Rate of change > 4.0°F / 10 min |

Officer interaction is minimal — only **CRITICAL** and **HIGH** alerts show action buttons.
All other alerts auto-resolve when the condition clears. History persists in DynamoDB with 90-day TTL.

### Analytics Engine (On-the-Fly)

All analytics computed in real-time from raw readings — no pre-aggregation:
- **Rolling statistics**: 1-hour high, low, average, standard deviation
- **Rate of change**: temperature delta per 10-minute window
- **Anomaly detection**: Z-score (> 2.5σ) + hard threshold checks
- **Sensor status**: online / degraded (> 2 min silent) / offline (> 5 min silent)
- **Forecasting**: linear regression on recent readings → point forecast + confidence interval series
- **Compliance**: percentage of readings within safe range (65–85°F), excludes offline sensors

### Multi-Tenancy & Client Registry

- **Single registry** (`clients.yaml`) defines all client configuration per server
- Each client entry specifies: DB credentials, isolation mode, data source, alert table
- **Two isolation modes**:
  - `shared` — clients share a DB; queries filter by `client_id` (→ `customer_key` column)
  - `isolated` — client has a dedicated DB; no filter needed, connects directly
- Per-client MySQL connection pool (thread-local, keyed by `client_id`)
- Access tokens stored in AWS Secrets Manager: `TempMonitor/{deployment_id}/{client_id}`
- Officers visit `/connect/{token}` → signed HttpOnly cookie → 30-day session
- Alerts isolated by `client_id` in DynamoDB GSI (`ClientActiveAlerts`)

Server-to-client mapping:
```
server1 → clients A, B     (shared DB)
server2 → client C          (isolated DB)
server3 → clients A, D, E  (mixed)
serverX → dev/staging       (default, no filter)
```

### Client Onboarding

Automated via `scripts/onboard_client.sh`:

```bash
./scripts/onboard_client.sh \
  --client-id 14 \
  --client-name "County Jail West" \
  --deployment-id abc1234567 \
  --db-host cluster.rds.amazonaws.com \
  --db-user app_user \
  --db-password-env CLIENT_14_DB_PASSWORD \
  --db-database county_west
```

This creates: Secrets Manager entry + DynamoDB alerts table + `clients.yaml` entry.
One command, ~3 minutes. See [DEPLOY.md](DEPLOY.md) for details.

### Server Setup

Automated via `scripts/setup_server.sh`:

```bash
./scripts/setup_server.sh \
  --env prod \
  --deployment-id abc1234567 \
  --db-host cluster.rds.amazonaws.com \
  --db-user app_user \
  --db-database county_db
```

This builds and deploys the full SAM stack (Lambda + API Gateway + DynamoDB + IAM).

### Compliance Section

- **Live Compliance Gauge**: percentage of ONLINE sensors within safe range (65–85°F)
- **Stats**: Total, In Range, Issue, Too Hot, Too Cold, Offline (offline sensors excluded from temperature stats)
- **7-Day Compliance Trend**: daily compliance percentage over the past 7 days with target line (95%)
- **Filter-aware**: compliance updates when a facility filter is applied, showing scope label

### Unified Chart

One chart handles all modes — no separate live/offline/history charts:

| Feature | LIVE mode | Quick Range (1h–24h) | Custom Date Range | Offline |
|---|---|---|---|---|
| Actual line | Solid, teal | Solid, teal | Solid, teal | Dotted, gray |
| Forecast | 30-min, dotted orange with glow | Hidden | Hidden | Hidden |
| Safe zone (65–85°F) | Shaded | Shaded | Shaded | Shaded |
| Threshold lines | Too Hot / Too Cold | Too Hot / Too Cold | Too Hot / Too Cold | Too Hot / Too Cold |
| Alert diamonds | Severity-colored | Severity-colored | Severity-colored | Severity-colored |
| Downsampling | No (< 2000 pts) | No | Min-max-mean (> 2000 pts) | No |

## Quick Start (Local)

```bash
# 1. Set environment
export MYSQL_HOST=your-aurora-host
export MYSQL_USER=your_user
export MYSQL_PASSWORD='your_password'
export MYSQL_DATABASE=your_db
export DATA_SOURCE=mysql           # or parquet, hybrid

# 2. Install
pip install -r dashboard/requirements.txt -r requirements-dev.txt

# 3. Run with gunicorn (threaded — faster than Flask dev server)
cd dashboard && gunicorn app.main:server -b 0.0.0.0:8051 --threads 4

# 4. Or run standalone simulator (no DB needed)
python sensor_simulator.py         # http://localhost:8051

# 5. Test + lint
cd dashboard && python -m pytest tests/ -v    # 158 unit tests
cd dashboard && python -m ruff check app/ tests/
```

Local mode uses `moto` to simulate DynamoDB in-process — same alert lifecycle
as production with zero AWS dependency.

## Simulator (Testing)

The standalone simulator generates 10 live + 3 offline sensors with 10 days of history:
```bash
python sensor_simulator.py --port 8051 --interval 5
```

Sensor profiles cover all scenarios: stable, drift_up, drift_down, hot, cold, rapid, edge, offline.
No DB dependency — all data is in-memory. Does not modify any production code.

## Deployment

See [DEPLOY.md](DEPLOY.md) for the full deployment guide.

## Key Configuration

| Variable | Default | Description |
|---|---|---|
| `CLIENT_ID` | `default` | Client identifier for local mode (maps to `customer_key` in DB) |
| `CLIENT_NAME` | `Local Facility` | Display name for local mode |
| `CLIENTS_YAML` | (auto-detect) | Path to `clients.yaml` client registry |
| `DATA_SOURCE` | `mysql` | Data routing: `mysql`, `parquet`, or `hybrid` |
| `MYSQL_HOST` | `localhost` | MySQL Aurora host |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DATABASE` | `Demo_aurora` | Database name |
| `PARQUET_BUCKET` | (empty) | S3 bucket for Parquet files |
| `PARQUET_PREFIX` | `sensor-data/` | S3 key prefix for daily Parquets |
| `ALERTS_TABLE` | (empty) | DynamoDB table name (auto-created locally with moto) |
| `NOTE_LAMBDA_ARN` | (empty) | Lambda ARN for alert note forwarding |
| `AWS_MODE` | `false` | Enable Secrets Manager auth (true in production) |
| `AWS_REGION` | `us-east-1` | AWS region for all services |
| `TEMP_HIGH` | `85.0` | Upper normal threshold (°F) |
| `TEMP_LOW` | `65.0` | Lower normal threshold (°F) |
| `TEMP_CRITICAL_HIGH` | `95.0` | Critical upper limit (°F) |
| `TEMP_CRITICAL_LOW` | `50.0` | Critical lower limit (°F) |
| `COMPLIANCE_TARGET` | `95.0` | Target compliance percentage |
| `REFRESH_MONITOR_MS` | `15000` | State pump refresh interval (ms) |
| `ALERT_COOLDOWN_SEC` | `300` | Seconds before a dismissed alert can re-trigger |
| `ALERT_OFFLINE_THRESHOLD_SEC` | `300` | Seconds of silence before "offline" |
| `ALERT_DEGRADED_THRESHOLD_SEC` | `120` | Seconds of silence before "degraded" |
| `MAX_HISTORY_DAYS` | `120` | Maximum days for date range picker |
| `ALERT_TTL_DAYS` | `90` | DynamoDB item TTL for alert records |

### Cache TTLs (in `config.py`)

| Cache | TTL (seconds) | What it caches |
|---|---|---|
| `CACHE_TTL_STATES` | 15 | All sensor states (per-client) |
| `CACHE_TTL_READINGS` | 60 | Readings for a single sensor + time range |
| `CACHE_TTL_ALERTS` | 10 | Live alerts (fast refresh) |
| `CACHE_TTL_COMPLIANCE` | 60 | 7-day compliance history |
| `CACHE_TTL_LOCATIONS` | 120 | Distinct facility/location list |
| `CACHE_TTL_TAG_LOCATIONS` | 300 | Tag-to-zone mapping (legacy) |

## AWS Resource Costs (Estimated)

| Resource | Type | Monthly Cost |
|---|---|---|
| Lambda (dashboard) | 256 MB, ~5,000 req/day | ~$2–5 |
| API Gateway | REST, ~5,000 req/day | ~$3–5 |
| DynamoDB (alerts) | On-demand, ~1 KB/item, 90-day TTL | ~$1–3 |
| MySQL Aurora | Existing (shared with other services) | — |
| S3 (Parquet) | ~100 MB/month | < $1 |
| Secrets Manager | ~5 secrets | ~$2 |
| **Total (per server)** | | **~$10–15/month** |

## Dependencies

**Runtime** (`dashboard/requirements.txt`):
```
dash>=2.14, dash-bootstrap-components>=1.5, plotly>=5.18
pandas>=2.0, numpy>=1.24,<2.1
pymysql>=1.1, cryptography>=41.0, pyarrow>=15.0
boto3>=1.28, serverless-wsgi>=0.2, gunicorn>=21.2, moto>=5.0
```

**Development** (`requirements-dev.txt`):
```
pytest>=7.4, ruff>=0.1, moto>=5.0
```
