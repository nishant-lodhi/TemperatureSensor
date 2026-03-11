# TempMonitor — Correctional Facility Temperature Sensor Platform

Serverless single-page dashboard for monitoring temperature sensors in correctional facilities.
Hybrid data architecture (MySQL Aurora / S3 Parquet), DynamoDB-backed alert management,
multi-tenant client isolation, and officer-friendly UI designed for real-time operational awareness.

## Architecture

```
┌──────────────┐     ┌────────────────────────────┐     ┌──────────────┐
│  S3 Parquet  │────▶│                            │◀───▶│  DynamoDB    │
│  (10-min     │     │     Dashboard (Dash)       │     │  (Alerts)    │
│   interval)  │     │                            │     └──────────────┘
└──────────────┘     │  ┌────────┐  ┌──────────┐  │
                     │  │ Hybrid │  │ Analytics│  │     ┌──────────────┐
┌──────────────┐     │  │Provider│  │  Engine  │  │────▶│  Lambda X    │
│  MySQL       │────▶│  └────────┘  └──────────┘  │     │  (Notes)     │
│  Aurora RDS  │     │                            │     └──────────────┘
│(dg_gateway_  │     │  ┌────────┐  ┌──────────┐  │
│  data table) │     │  │ Alert  │  │  Charts  │  │
└──────────────┘     │  │Manager │  │ (Plotly) │  │
                     │  └────────┘  └──────────┘  │
                     └────────────────────────────┘
                                │
                     ┌──────────┴──────────┐
                     │   API Gateway / ALB  │
                     └─────────────────────┘
```

### Data flow — Hybrid Provider

| Flag (`DATA_SOURCE`) | Live readings | Historical (6h–120d) | Notes |
|---|---|---|---|
| `mysql` | MySQL only | MySQL only | Default; simplest setup |
| `parquet` | Parquet only | Parquet only | Fastest for large datasets |
| `hybrid` | Parquet → MySQL fallback | Parquet for past days, MySQL for today | Best of both worlds |

The `HybridProvider` manages the routing transparently. Readings are cached for 60 seconds
keyed by `(device_id, range)`. Sensor states are cached for 20 seconds.

### Single-Page UI Layout

```
┌──────────────────────────────────────────────────────────┐
│ ⬢ TEMPMONITOR                    Mar 11, 2026  ● LIVE   │
├──────────────────────────────────────────────────────────┤
│ [ACTION REQUIRED]     0/3 Sensors  5 Alerts  72.4°F Avg │
├──────────────────────────────────────────────────────────┤
│ ⚠ 2 Alerts for 00301A80                                 │
│  [Important] Sensor 00301A80 not responding              │
│  [📋 Note] [✕ Remove]                                   │
├──────────────────────────────────────────────────────────┤
│ ☉ 3 Sensors          [Show All toggle]                  │
│ ┌────────┐ ┌────────┐ ┌────────┐                       │
│ │ 95.8°F*│ │ 95.2°F*│ │ 69.8°F*│                       │
│ └────────┘ └────────┘ └────────┘                        │
├──────────────────────────────────────────────────────────┤
│ ● OFFLINE  C30000301A80  69.8°F                         │
│ [HIGH] [LOW] [AVG] [TREND] [FORECAST] [IN RANGE]       │
│ [BATTERY] [SIGNAL]                                      │
├──────────────────────────────────────────────────────────┤
│ [LIVE] [6h] [12h] [24h] [48h] [7d] [14d] [30d] [60d]  │
│ [90d] [120d]                                            │
├──────────────────────────────────────────────────────────┤
│ ━━━━━━━━ Unified Chart ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  Actual line + Forecast + Alert ◆ markers (clickable)    │
│  Safe zone (65–85°F) + Too Hot / Too Cold thresholds     │
│  High/Low annotations (staggered, non-overlapping)       │
│  Downsampled to ~2000 pts for 60–120 day ranges          │
├──────────────────────────────────────────────────────────┤
│ [Compliance Gauge 33.3%]  │  [7-Day Compliance Trend]   │
│  3 Total, 1 In Range, 2 Out, 2 Hot, 0 Cold             │
├──────────────────────────────────────────────────────────┤
│ Alert History Table                                      │
│  Priority | Type | What | When | Status                  │
│  Important  SENSOR_OFFLINE  Sensor not responding  Active│
└──────────────────────────────────────────────────────────┘
```

Key UI behaviors:
- **LIVE mode** (default): auto-refreshes every 10s, shows last 2h + 30-min forecast, green button
- **History mode** (6h–120d): fetches once on click, caches in browser store, no auto-refresh for readings
- **Offline sensors**: chart shows dotted line up to last reading, "Last Reading" marker, no forecast
- **Alert markers**: severity-colored diamonds on the chart at the alert timestamp/temperature
- **Note click flow**: officer clicks Note → green checkmark → alert auto-dismissed from live → preserved in DynamoDB history
- **Compliance**: always shows for ALL sensors (including offline); labeled "Last Known Compliance" when all offline
- **Toggle**: switch between "All Sensors" and "Critical Only" filtering

### Module Structure

```
TemperatureSensor/
├── README.md                     This file
├── DEPLOY.md                     Full deployment guide
├── Makefile                      run, run-debug, test, lint
├── requirements-dev.txt          Dev dependencies (pytest, ruff, moto)
├── infra/
│   ├── template.yaml             SAM template (Lambda, API GW, DynamoDB)
│   └── samconfig.toml            Per-environment deploy config
├── .github/workflows/
│   ├── ci.yml                    PR checks: lint + test + SAM validate
│   └── cd.yml                    Continuous deploy: dev/staging/prod
└── dashboard/
    ├── lambda_handler.py         AWS Lambda entry point (serverless-wsgi)
    ├── pyproject.toml            Ruff + pytest config
    ├── requirements.txt          Runtime dependencies
    ├── app/
    │   ├── config.py        (90) Theme, thresholds, env vars, SVG icons
    │   ├── auth.py         (134) Cookie signing, Secrets Manager tokens
    │   ├── routes.py       (104) Flask middleware, /connect, /healthz
    │   ├── main.py          (64) Dash app creation, navbar, clock
    │   ├── data/
    │   │   ├── provider.py  (36) DataProvider protocol + factory
    │   │   ├── mysql_reader.py (174) Thread-local pool + SQL queries
    │   │   ├── parquet_reader.py (110) S3 daily Parquet with cache
    │   │   ├── analytics.py (174) Stats, anomaly detection, forecasting
    │   │   ├── alert_manager.py (250) DynamoDB lifecycle (moto locally)
    │   │   └── hybrid_provider.py (230) Orchestrator: data + analytics
    │   └── pages/
    │       ├── charts.py   (284) unified_chart(), compliance figures
    │       └── monitor.py  (573) Single-page: data pump + all UI
    └── tests/
        ├── conftest.py      (44) Flask context + MockProvider fixture
        ├── mock_provider.py (98) Deterministic 3-sensor test data
        └── unit/
            ├── test_alert_manager.py (131) Alert lifecycle + note/dismiss
            ├── test_analytics.py     (148) Stats, anomaly, forecast
            ├── test_auth.py          (249) Cookie, tokens, hints
            ├── test_config.py         (35) Theme + threshold validation
            ├── test_lambda_handler.py (49) Lambda handler basics
            ├── test_monitor.py       (256) All UI callbacks (12 classes)
            ├── test_provider.py       (74) Protocol + factory + mock
            └── test_routes.py         (71) Flask routes + middleware
```

Total: **2,223 lines of application code**, **1,155 lines of test code**, **139 unit tests**.

### Alert System

| State | Trigger | DynamoDB | Live UI |
|---|---|---|---|
| **ACTIVE** | Condition fires (temp > threshold, offline, etc.) | `put_item` | Shows alert card with severity badge |
| **RESOLVED** | Condition clears automatically | `update_item` → RESOLVED | Disappears from live |
| **DISMISSED** | Officer clicks "Remove" | `update_item` → DISMISSED | Disappears + 5-min cooldown |
| **NOTE + DISMISS** | Officer clicks "Note" | Sends context to Lambda X → auto-dismiss | Green checkmark → disappears |

Alert conditions evaluated every 10 seconds:

| Alert Type | Severity | Condition |
|---|---|---|
| `EXTREME_TEMPERATURE` | CRITICAL | Temp > 95°F |
| `EXTREME_TEMPERATURE_LOW` | CRITICAL | Temp < 50°F |
| `SUSTAINED_HIGH` | HIGH | 85°F < Temp ≤ 95°F |
| `LOW_TEMPERATURE` | MEDIUM | 50°F ≤ Temp < 65°F |
| `SENSOR_OFFLINE` | HIGH | Sensor not responding |
| `RAPID_CHANGE` | MEDIUM | Rate of change > 4.0°F / 10 min |

Officer interaction is minimal — only **CRITICAL** and **HIGH** alerts show action buttons.
All other alerts self-manage (auto-resolve when condition clears).
Alert history persists in DynamoDB with 90-day TTL.

### Analytics Engine (On-the-Fly)

All analytics computed in real-time, no pre-aggregation:
- **Rolling statistics**: 1-hour high, low, average
- **Rate of change**: temperature delta per 10-minute window
- **Anomaly detection**: Z-score (> 2.5σ) + hard threshold checks
- **Sensor status**: online / degraded (> 2 min silent) / offline (> 5 min silent)
- **Forecasting**: linear regression on recent readings → point forecast + confidence interval series
- **Compliance**: percentage of readings within safe range (65–85°F)

### Data Pump Pattern

All data fetching happens in a single `data_pump` callback. Display callbacks read from `dcc.Store` objects (pure render, zero DB calls):

```
  10s Interval ─┐
  Range Click ──┤──▶ data_pump ──▶ Store: states
  Sensor Click ─┘                  Store: alerts
                                   Store: compliance
                                   Store: readings (+ forecast + alert history)
                                        │
                         ┌───────────────┼────────────────┐
                         ▼               ▼                ▼
                   render_banner   render_chart    render_compliance
                   render_grid    render_kpis     render_alert_table
                   render_alerts  render_range_bar
```

This eliminates serial callback latency — every display callback executes instantly from cached stores.

### Multi-Tenancy

- Each server runs one Lambda (or Gunicorn process) serving multiple clients
- Client isolation via `client_id` set in auth middleware (row-level, shared schema)
- Access tokens stored in AWS Secrets Manager: `TempMonitor/{deployment_id}/{client_id}`
- Officers visit `/connect/{token}` → signed HttpOnly cookie → 30-day session
- Alerts isolated by `client_id` in DynamoDB GSI (`ClientActiveAlerts`)

Server-to-client mapping example:
```
server1 → clients A, B
server2 → client A
server3 → clients A, B, C
serverX → dev/staging (shared)
```

Processing is singleton per server; data and details are segregated per client.

### Unified Chart

One chart handles all modes — no separate live/offline/history charts:

| Feature | LIVE mode | History mode (6h–120d) | Offline |
|---|---|---|---|
| Actual line | Solid, orange | Solid, orange | Dotted, gray |
| Forecast | 30-min ahead, CI band | Hidden | Hidden |
| Safe zone (65–85°F) | Shown | Shown | Shown |
| Threshold lines | Too Hot / Too Cold | Too Hot / Too Cold | Too Hot / Too Cold |
| High/Low markers | Right side, staggered | Right side, staggered | Right side, staggered |
| "Now" / "Last Reading" | "Now" dashed line | None | "Last Reading" dashed line |
| Alert diamonds | Severity-colored | Severity-colored | Severity-colored |
| Downsampling | No (< 2000 pts) | Min-max-mean (> 2000 pts) | No |

Annotations use `annotation_position` to prevent overlapping. Long ranges (60–120 days)
connect sparse data with lines — no blank gaps.

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

# 3. Run (gunicorn with 4 threads — faster than Flask dev server)
make run                           # http://localhost:8051

# 4. Or run with Flask dev server (for debugging)
make run-debug                     # http://localhost:8051

# 5. Test + lint
make test                          # 139 unit tests
make lint                          # ruff check (0 errors)
```

Local mode uses `moto` to simulate DynamoDB in-process — same alert lifecycle
as production with zero AWS dependency. No DynamoDB credentials needed locally.

## Deployment

See [DEPLOY.md](DEPLOY.md) for the full deployment guide covering:
- Environment variable reference
- Local development setup
- AWS deployment with SAM
- Client management (add/remove)
- CI/CD setup with GitHub Actions and OIDC
- AWS resources created
- Rollback procedures

```bash
# Deploy to dev (auto on push to develop)
sam deploy --config-env dev --config-file infra/samconfig.toml

# Deploy to production (via Git tag + GitHub approval)
git tag v1.0.0 && git push --tags
```

## CI/CD

| Trigger | Action | Approval |
|---|---|---|
| PR to `main` or `develop` | Lint + test + SAM validate | None (auto) |
| Push to `develop` | Auto-deploy to DEV | None |
| Push to `main` | Auto-deploy to STAGING | None |
| Git tag `v*` | Deploy to all prod servers | Required per server |
| Manual dispatch | Deploy to any single server | Optional |

Rollback: re-run the CD workflow for a previous tag, or `git checkout v1.0.0 && make deploy-prod-a`.

## Key Configuration

| Variable | Default | Description |
|---|---|---|
| `TEMP_HIGH` | 85.0°F | Upper normal threshold |
| `TEMP_LOW` | 65.0°F | Lower normal threshold |
| `TEMP_CRITICAL_HIGH` | 95.0°F | Critical upper limit |
| `TEMP_CRITICAL_LOW` | 50.0°F | Critical lower limit |
| `COMPLIANCE_TARGET` | 95.0% | Target compliance percentage |
| `REFRESH_MONITOR_MS` | 10,000 | Data pump refresh interval |
| `ALERT_COOLDOWN_SEC` | 300 | Seconds before a dismissed alert can re-trigger |
| `ALERT_OFFLINE_THRESHOLD_SEC` | 300 | Seconds of silence before "offline" |
| `ALERT_DEGRADED_THRESHOLD_SEC` | 120 | Seconds of silence before "degraded" |

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
pytest, ruff
```
