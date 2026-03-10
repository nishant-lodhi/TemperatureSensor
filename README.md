# TempMonitor — Environmental Sensor Analytics Platform

Real-time temperature monitoring, anomaly detection, forecasting, and
compliance reporting for correctional facilities.

**Multi-tenant** — one AWS deployment serves multiple clients (facilities),
each seeing only their own sensor data via a unique access URL.

**Serverless** — runs entirely on AWS Lambda, DynamoDB, Kinesis, and API Gateway.
Deploys identically to standard AWS and GovCloud with zero code changes.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Architecture — Full Data Flow](#architecture--full-data-flow)
3. [Resource Inventory](#resource-inventory)
4. [DynamoDB Schema](#dynamodb-schema)
5. [Backend Modules](#backend-modules)
6. [Dashboard (Frontend)](#dashboard-frontend)
7. [Project Structure](#project-structure)
8. [Quick Start — Run Locally](#quick-start--run-locally)
9. [Running Tests](#running-tests)
10. [Multi-Tenant Model](#multi-tenant-model)
11. [Authentication Flow](#authentication-flow)
12. [Client Management](#client-management)
13. [Deploy to AWS](#deploy-to-aws)
14. [CI/CD with GitHub Actions](#cicd-with-github-actions)
15. [Configuration Reference](#configuration-reference)
16. [AWS Cost Estimation](#aws-cost-estimation)
17. [Useful Commands](#useful-commands)

---

## How It Works

```
                                    DATA INGESTION
                                    ══════════════

  [Prod] Physical IoT Sensors ─── MQTT ──▸ IoT Core ──▸ IoT Adapter Lambda ──▸ Kinesis Stream
                                                          (decode BLE hex)         │
                           OR                                                      │
                                                                                   │
  [Dev]  EventBridge (every 1 min) ──────▸ Synthetic Generator Lambda ────────▸ Kinesis Stream
                                           (20 fake sensors)                       │
                                                                                   │
                                    PROCESSING                                     │
                                    ══════════                                     │
                                                                                   ▼
                                                                          ┌────────────────┐
                                          ┌───────────────────────────────│ Batch Processor │
                                          │                               │ Lambda          │
                                          │                               │ (500 records    │
                                          │                               │  per 30s)       │
                                          │                               └────────────────┘
                                          │
                                ┌─────────┼──────────┬───────────┐
                                ▼         ▼          ▼           ▼
                           DynamoDB    DynamoDB     S3        SNS Topics
                           (STATE)     (READING)  (archive)  (alerts)

  EventBridge (scheduled) ──▸ Scheduled Processor Lambda
                                │
                                ├── every 15 min → analytics (rolling metrics, anomaly detection)
                                ├── every 1 hour → forecast (30-min and 2-hr predictions)
                                └── daily 6 AM   → compliance report

                                    DASHBOARD
                                    ═════════

  Officer Browser ──▸ API Gateway HTTPS ──▸ Dashboard Lambda (Dash/Flask)
                                                   │
                                             Secrets Manager (token → client_id)
                                                   │
                                             DynamoDB (client-scoped reads via GSI)
```

**Key design**: Kinesis is the universal entry point. Both real and synthetic data
use identical record formats. The entire downstream pipeline is source-agnostic.

---

## Architecture — Full Data Flow

Step-by-step, showing every AWS resource touched at each stage.

```
STEP  WHAT HAPPENS                                          AWS RESOURCE
────  ──────────────────────────────────────────────────    ─────────────────────────
 1a   [Prod] BLE sensors publish via gateway MQTT            AWS IoT Core
      TempMonitorIoTRule fires → IoT Adapter Lambda          Lambda (iot-adapter)
      Decode rawData hex → temperature °F                    ↓
      Write decoded records to ───────────────────────▸      Kinesis Data Stream

 1b   [Dev] EventBridge triggers every 1 minute ─────▸       Lambda (synthetic-gen)
      Generate 20 realistic fake readings ───────────▸       Kinesis Data Stream

 1c   [Generic IoT] AllDataRule routes MQTT ─────────▸       Kinesis (direct)
      CriticalTempRule fires on >95°F / <50°F ──────▸        Lambda (critical-alert)
      └── validate → put_alert → send_alert ─────────▸       Alerts DynamoDB + SNS

 2    Kinesis triggers Batch Processor (batch ≤500, 30s window)
      │
      ├── Base64 decode → JSON parse
      ├── Normalize fields (normalizer.py)
      ├── Validate (temperature range, timestamp, device_id)
      ├── Lookup device in PlatformConfig table ──────▸      PlatformConfig DynamoDB
      │   (auto-provision if FEATURE_AUTO_PROVISION=true)
      ├── Update sensor state ────────────────────────▸      SensorData DynamoDB
      │   pk=device_id, sk="STATE"
      │   Fields: last_temp, last_seen, status, signal_dbm,
      │           signal_label, battery_pct, client_id, zone_id
      ├── Store 1-minute aggregate ───────────────────▸      SensorData DynamoDB
      │   pk=device_id, sk="R#2026-03-10T12:05:00Z"
      │   Fields: temperature (avg), temp_min, temp_max,
      │           reading_count, signal_dbm_avg, battery_pct_avg
      │   TTL: auto-expires after configured retention
      ├── Evaluate alerts:
      │   - evaluate_critical() → extreme temp per event
      │   - evaluate_thresholds() → sustained high, rapid change
      │   - aggregate_zone_alerts() → zone-level rollups
      │   If alert fires ─────────────────────────────▸      Alerts DynamoDB + SNS
      └── Archive raw batch (if enabled) ─────────────▸      S3 Data Lake

 3    EventBridge triggers Scheduled Processor:
      │
      ├── Every 15 min (mode=analytics):
      │   Read STATE records → get last 2h readings
      │   compute_all_metrics() → rolling_avg_10m/1h, rolling_std_1h,
      │                           rate_of_change_10m, actual_high_1h, actual_low_1h
      │   detect_anomaly() → z-score ≥ 3.0 or moving-avg deviation ≥ 4°F
      │   Update STATE ──────────────────────────────▸       SensorData DynamoDB
      │   Evaluate analytics alerts (offline, anomaly, forecast breach)
      │
      ├── Every 1 hr (mode=forecast):
      │   Read last 4h readings (need ≥10 points)
      │   Holt's linear method → predict 30min and 2hr ahead
      │   Store forecast ────────────────────────────▸       SensorData DynamoDB
      │   pk=device_id, sk="F#30min" / "F#2hr"
      │   Fields: predicted_temp, ci_lower, ci_upper, steps
      │
      └── Daily 6 AM (mode=compliance):
          compute_compliance() per zone → in-range %, breaches
          generate_daily_report() ───────────────────▸       S3 Data Lake (reports/)

 4    Officer opens browser → API Gateway HTTPS → Dashboard Lambda
      │
      ├── First visit: /connect/{token}
      │   resolve_token() ───────────────────────────▸       Secrets Manager
      │   (secret: TempMonitor/{deployment_id}/{client_id})
      │   Set signed HttpOnly cookie (tm_session, 30 days)
      │   Redirect to /
      │
      ├── Every request: before_request middleware
      │   verify_cookie() → HMAC-SHA256 check
      │   validate_token_hint() → check if token revoked ▸  Secrets Manager (5-min cache)
      │   Set flask.g.client_id for request scope
      │
      ├── Live Monitor tab (refreshes every 10s):
      │   get_all_sensor_states() ───────────────────▸       SensorData DynamoDB (client-index GSI)
      │   get_all_alerts() ──────────────────────────▸       Alerts DynamoDB (client-index GSI)
      │   Banner: ALL CLEAR / NEEDS ATTENTION / ACTION REQUIRED
      │   Grid: sensor tiles (temp, battery icon, WiFi icon)
      │   Detail: selected sensor chart + metrics
      │
      └── History & Reports tab:
          get_readings(device_id, since) ────────────▸       SensorData DynamoDB
          get_forecast_series(device_id, horizon) ───▸       SensorData DynamoDB
          get_compliance_history(days) ──────────────▸       S3 Data Lake (reports/)
          Chart: actual + forecast + safe zone + anomaly markers
          Compliance: gauge, 7-day trend, breach stats
          Alerts: DataTable of recent alerts for selected sensor

 5    CloudWatch monitors Dashboard Lambda
      DashboardErrorAlarm fires if ≥5 errors in 5 minutes
```

### Resource Connection Matrix

Every arrow in the system. Read as: **Source** writes/calls **Target**.

```
                         Platform    Sensor     Alerts    Data Lake   Critical   Standard   Secrets
                         Config DB   Data DB    DB        S3 Bucket   SNS Topic  SNS Topic  Manager
                         ─────────   ─────────  ────────  ──────────  ─────────  ─────────  ───────
BatchProcessor Lambda      CRUD        CRUD      CRUD      Write       Publish    Publish     —
CriticalAlert  Lambda       —           —        CRUD       —          Publish    Publish     —
Scheduled      Lambda      CRUD        CRUD      CRUD      Write       Publish    Publish     —
Dashboard      Lambda      Read        Read      Read      Read         —          —         Read
IoT Adapter    Lambda       —           —         —         —           —          —          —
Synthetic Gen  Lambda       —           —         —         —           —          —          —
```

IoT Adapter and Synthetic Generator write to **Kinesis** only (not directly to DynamoDB).

---

## Resource Inventory

The SAM template (`infra/template.yaml`) creates up to **22 AWS resources** in
a single CloudFormation stack. Resources marked **(conditional)** are only created
when their condition is met.

| # | Resource | AWS Type | Condition | Naming Pattern |
|---|----------|----------|-----------|----------------|
| 1 | SharedDependenciesLayer | Lambda Layer | always | `temp-sensor-shared-deps-{ID}-{ENV}` |
| 2 | SensorDataStream | Kinesis Stream | always | `temp-sensor-sensor-stream-{ID}-{ENV}` |
| 3 | BatchProcessorFunction | Lambda | always | `temp-sensor-batch-processor-{ID}-{ENV}` |
| 4 | CriticalAlertFunction | Lambda | always | `temp-sensor-critical-alert-{ID}-{ENV}` |
| 5 | ScheduledProcessorFunction | Lambda | always | `temp-sensor-scheduled-processor-{ID}-{ENV}` |
| 6 | SyntheticGeneratorFunction | Lambda | SyntheticMode=true | `temp-sensor-synthetic-gen-{ID}-{ENV}` |
| 7 | IoTAdapterFunction | Lambda | EnableIoTRule=true | `temp-sensor-iot-adapter-{ID}-{ENV}` |
| 8 | TempMonitorIoTRule | IoT TopicRule | EnableIoTRule=true | — |
| 9 | IoTAdapterInvokePermission | Lambda Permission | EnableIoTRule=true | — |
| 10 | CriticalTempRule | IoT TopicRule | EnableIoTRule!=true | — |
| 11 | AllDataRule | IoT TopicRule | EnableIoTRule!=true | — |
| 12 | IoTKinesisRole | IAM Role | EnableIoTRule!=true | — |
| 13 | IoTInvokeCriticalAlertPermission | Lambda Permission | EnableIoTRule!=true | — |
| 14 | PlatformConfigTable | DynamoDB | always | `temp-sensor-platform-config-{ID}-{ENV}` |
| 15 | SensorDataTable | DynamoDB | always | `temp-sensor-sensor-data-{ID}-{ENV}` |
| 16 | AlertsTable | DynamoDB | always | `temp-sensor-alerts-{ID}-{ENV}` |
| 17 | DataLakeBucket | S3 | always | `temp-sensor-data-lake-{ID}-{ENV}` |
| 18 | CriticalAlertTopic | SNS | always | `temp-sensor-critical-alerts-{ID}-{ENV}` |
| 19 | StandardAlertTopic | SNS | always | `temp-sensor-standard-alerts-{ID}-{ENV}` |
| 20 | DashboardApi | HTTP API (v2) | always | — |
| 21 | DashboardFunction | Lambda | always | `TempMonitor-Dashboard-{ID}-{ENV}` |
| 22 | DashboardErrorAlarm | CloudWatch Alarm | always | — |
| — | Secrets Manager | managed by scripts | always | `TempMonitor/{ID}/{client_id}` |

`{ID}` = DeploymentId (10-char), `{ENV}` = Environment (dev/staging/prod).

---

## DynamoDB Schema

All three tables use single-table design with `pk` (partition key) + `sk` (sort key).

### SensorDataTable

| Record Type | pk | sk | Key Fields | TTL |
|------------|----|----|------------|-----|
| **Sensor State** | `{device_id}` | `STATE` | last_temp, last_seen, status, client_id, zone_id, facility_id, signal_dbm, signal_label, battery_pct, rolling_avg_10m, rolling_avg_1h, rolling_std_1h, rate_of_change_10m, actual_high_1h, actual_low_1h, anomaly, anomaly_reason | — |
| **1-min Reading** | `{device_id}` | `R#{ISO timestamp}` | temperature, temp_min, temp_max, reading_count, signal_dbm_avg, battery_pct_avg | Yes |
| **Forecast** | `{device_id}` | `F#{horizon}` | predicted_temp, ci_lower, ci_upper, peak_temp, min_temp, steps, series | — |

**GSI**: `client-index` — pk=`client_id`, sk=`sk`. Used by dashboard to query all sensors/readings for a specific client.

### AlertsTable

| Record Type | pk | sk | Key Fields | TTL |
|------------|----|----|------------|-----|
| **Alert** | `{facility_id}#{zone_id}` | `{triggered_at}#{alert_type}` | severity, device_id, client_id, temperature, message, status, resolved_at | Yes (90 days) |

**GSI**: `client-index` — pk=`client_id`, sk=`sk`. Used by dashboard.

### PlatformConfigTable

| Record Type | pk | sk | Key Fields |
|------------|----|----|------------|
| **Device Metadata** | `DEVICE#{device_id}` | `META` | client_id, facility_id, zone_id |
| **Tenant Config** | `TENANT#{client_id}` | `CONFIG` | thresholds overrides |
| **Tenant Features** | `TENANT#{client_id}` | `FEATURES` | feature flags |

**GSI**: `zone-index` — pk=`zone_id`. Used for zone-level queries.

---

## Backend Modules

### Handlers (Lambda entry points)

| Handler | File | Trigger | What It Does |
|---------|------|---------|--------------|
| **Batch Processor** | `src/handlers/batch_handler.py` | Kinesis (batch ≤500, 30s window) | Decode, validate, normalize, enrich, update STATE, store READING, check alerts, archive to S3 |
| **Critical Alert** | `src/handlers/critical_handler.py` | IoT Rule (temp >95 or <50) | Validate event, create alert, send SNS notification |
| **Scheduled Processor** | `src/handlers/scheduled_handler.py` | EventBridge (15m/1h/daily) | Rolling metrics, anomaly detection, forecasting, compliance reports |
| **IoT Adapter** | `src/handlers/iot_adapter.py` | IoT Rule (BLE MQTT topic) | Decode BLE rawData hex → temperature °F, write to Kinesis |
| **Synthetic Generator** | `src/handlers/synthetic_generator.py` | EventBridge (every 1 min) | Generate realistic fake data for N sensors, write to Kinesis |

### Processing Libraries

| Module | Files | What It Does |
|--------|-------|--------------|
| **Ingestion** | `normalizer.py`, `validator.py` | Normalize raw fields (CSV column mapping, type coercion), validate ranges |
| **Analytics** | `rolling_metrics.py`, `anomaly_detection.py`, `zone_analytics.py` | Rolling avg/std (10m, 1h), rate of change, z-score anomalies, zone summaries |
| **Forecasting** | `forecast_model.py` | Holt's linear method (double exponential smoothing), needs ≥10 readings |
| **Alerts** | `alert_engine.py`, `alert_rules.py`, `notifier.py` | Evaluate thresholds, aggregate zone alerts, deduplicate, send via SNS |
| **Reports** | `compliance.py` | In-range %, breach counts, daily/shift reports |
| **Storage** | `dynamodb_store.py`, `s3_store.py` | DynamoDB CRUD (single-table), S3 archival and report storage |
| **Config** | `settings.py`, `resource_naming.py`, `tenant_config.py` | Environment-based config, resource naming, per-tenant thresholds/features |

### Alert Types

| Alert | Severity | Trigger Condition |
|-------|----------|-------------------|
| EXTREME_TEMPERATURE | CRITICAL | temp > 95°F or < 50°F |
| SUSTAINED_HIGH_TEMPERATURE | HIGH | All readings > 85°F for 10+ minutes |
| RAPID_TEMPERATURE_CHANGE | MEDIUM | \|rate_of_change\| > 4°F/min |
| SENSOR_OFFLINE | CRITICAL/HIGH/MEDIUM | No reading for >60 seconds (severity by gap) |
| ANOMALY_DETECTED | MEDIUM | Z-score ≥ 3.0 or deviation ≥ 4°F from rolling avg |
| FORECAST_BREACH | WARNING | Predicted temp > 85°F |

---

## Dashboard (Frontend)

Built with **Dash by Plotly** + **Flask**, served via Lambda behind API Gateway using `serverless-wsgi`.

### Tab 1: Live Monitor (refreshes every 10s)

| Component | What It Shows |
|-----------|--------------|
| **Status Banner** | ALL CLEAR / NEEDS ATTENTION / ACTION REQUIRED + sensor count, avg temp, alert count, low-battery count |
| **Alert Drawer** | Click alert count to expand — severity-sorted list of all active alerts |
| **Sensor Grid** | Horizontal tiles: temperature, battery icon, WiFi signal icon. Alerts/issues sorted first. Gray = offline. Click to select (orange highlight). |
| **Detail Panel** | Selected sensor: 1h high/low, rate of change, battery %, signal dBm, anomaly info, 2h temperature chart. Offline sensors show last known data with "Last Reading" marker. |

### Tab 2: History & Reports

| Component | What It Shows |
|-----------|--------------|
| **Controls** | Sensor dropdown (preserves selection), time range (6h/12h/24h/48h), forecast horizon (30min/2hr) |
| **KPIs** | Current (or Last for offline), High, Low, Average, Forecast (or Last Reading for offline), In-Range % |
| **Chart** | Actual readings + forecast overlay + CI band + safe zone (65-85°F) + high/low annotations. Offline sensors: x-axis bounded to data range, "Last Reading" marker. |
| **Compliance** | Gauge vs 95% target, breach stats, 7-day spline area trend |
| **Alert History** | DataTable: Priority, What, When (with year), Status. Conditional styling for Urgent/Active. |

### Data Providers

| Provider | When Used | Data Source |
|----------|-----------|-------------|
| `MockProvider` | `AWS_MODE=false` (local dev) | In-memory generated data, 20 sensors per client |
| `AWSProvider` | `AWS_MODE=true` (deployed) | DynamoDB queries via client-index GSI, S3 for compliance reports |

---

## Project Structure

```
temp_sensors/
├── .github/
│   ├── actions/deploy-sam/action.yml    # Reusable SAM deploy action
│   └── workflows/
│       ├── ci.yml                        # Lint + test on push/PR to main/develop
│       └── cd.yml                        # Deploy to prod on v* tag or manual
│
├── src/                                  # BACKEND (Lambda handlers + libraries)
│   ├── handlers/
│   │   ├── batch_handler.py              # Kinesis → process → DynamoDB/S3/SNS
│   │   ├── critical_handler.py           # IoT critical temp → alert
│   │   ├── scheduled_handler.py          # Analytics, forecast, compliance
│   │   ├── iot_adapter.py                # BLE rawData hex → Kinesis (prod)
│   │   └── synthetic_generator.py        # Fake sensor data → Kinesis (dev)
│   ├── analytics/                        # Rolling metrics, anomaly detection, zone analytics
│   ├── alerts/                           # Alert engine, rules, SNS notifier
│   ├── forecasting/                      # Holt's linear forecast model
│   ├── ingestion/                        # Normalizer + validator
│   ├── reports/                          # Compliance reporting
│   ├── storage/                          # DynamoDB + S3 abstraction
│   ├── config/                           # Settings, naming, tenant config
│   └── requirements.txt                  # boto3, numpy
│
├── dashboard/                            # FRONTEND (independent package)
│   ├── app/
│   │   ├── main.py                       # Dash app + Flask auth middleware
│   │   ├── auth.py                       # Secrets Manager token + signed cookies
│   │   ├── config.py                     # Theme, colors, thresholds, chart config
│   │   ├── pages/
│   │   │   ├── monitor.py                # Tab 1 — Live Monitor
│   │   │   └── history.py                # Tab 2 — History & Reports
│   │   └── data/
│   │       ├── provider.py               # DataProvider interface + factory
│   │       ├── mock_provider.py           # Local demo data (no AWS needed)
│   │       └── aws_provider.py            # Live DynamoDB/S3 queries
│   ├── lambda_handler.py                 # Lambda entry: serverless_wsgi adapter
│   ├── tests/unit/                       # 8 test modules, 156 tests
│   ├── requirements.txt                  # dash, plotly, boto3, serverless-wsgi
│   └── pyproject.toml                    # Ruff + pytest config
│
├── infra/                                # INFRASTRUCTURE AS CODE
│   ├── template.yaml                     # Unified SAM template (all environments)
│   └── samconfig.toml                    # Per-server deploy parameters
│
├── scripts/
│   ├── manage_client.py                  # CLI: add/list/remove/rotate clients
│   └── import_csv_sensor.py              # One-time CSV → DynamoDB import
│
├── tests/                                # BACKEND TESTS
│   ├── unit/                             # 22 test modules, 343 tests
│   ├── integration/                      # End-to-end pipeline test
│   └── events/                           # Sample Lambda event payloads
│
├── simulation/                           # Local mock data generator + pipeline runner
├── data/                                 # Sample CSV sensor data files
│
├── Makefile                              # Single entry: install, test, lint, build, deploy
├── DEPLOY.md                             # Step-by-step deployment guide
├── requirements-dev.txt                  # Dev/test deps: pytest, ruff, moto
└── .gitignore
```

---

## Quick Start — Run Locally

Run the dashboard with mock data. No AWS account needed.

### Step 1: Install Dependencies

```bash
cd temp_sensors

# (Recommended) Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all dependencies
make install install-dev
```

Or manually:

```bash
pip install -r src/requirements.txt -r dashboard/requirements.txt -r requirements-dev.txt
```

### Step 2: Start the Dashboard

```bash
make run
```

You should see:

```
Dash is running on http://0.0.0.0:8050/
```

### Step 3: Open Your Browser

Go to **http://localhost:8050**

You'll see:
- **Live Monitor** tab — 20 mock sensors with temperature, battery, WiFi signal
- Click any sensor tile to see its detail panel with a 2-hour chart
- Click the alert count in the banner to see facility-wide alerts
- **History & Reports** tab — per-sensor historical data, forecast, compliance

### Step 4: Stop

Press `Ctrl+C` in the terminal.

---

## Running Tests

```bash
make test                # All tests (backend + dashboard)
make test-backend        # Backend only (~343 tests)
make test-dashboard      # Dashboard only (~156 tests)
make lint                # Dashboard linter (ruff)
```

Expected results:

```
tests/ ─────────────── 343 passed
dashboard/tests/ ───── 156 passed, 1 skipped
```

The 1 skipped test requires `serverless_wsgi` (deployment-only dependency).

---

## Multi-Tenant Model

Each **server** (dev, staging, prod-A, govcloud-prod) is one SAM stack.
Multiple **clients** share the same stack with complete data isolation.

```
Server: prod-a (DeploymentId = a3f7b2c1d4)
├── Client: alpha_facility  →  /connect/a7f3b2c1-d4e5-...
├── Client: beta_facility   →  /connect/x9d2e4f5-a7b8-...
└── Client: gamma_facility  →  /connect/m1n2o3p4-q5r6-...
```

**How isolation works:**
- Every DynamoDB record has a `client_id` field
- Dashboard queries use a Global Secondary Index (GSI) on `client_id`
- Each client's access token maps to their `client_id` in Secrets Manager
- Officers see only their facility's sensors, alerts, and reports

---

## Authentication Flow

```
Admin creates client ─▸ Secrets Manager stores token + client_id
                              │
Admin shares URL ─────▸ https://{api-gw}/connect/{token}
                              │
Officer visits URL ───▸ Dashboard resolves token → sets signed cookie → redirect to /
                              │
Officer bookmarks / ──▸ Cookie verified (HMAC-SHA256) → client_id set → scoped queries
                              │
Cookie lasts 30 days. No login form, no password.
Token rotation: admin runs `rotate` → new URL → old cookie expires in ~5 min.
Token revocation: admin runs `remove` → officers see "session expired" page.
```

---

## Client Management

```bash
# Add a new client (returns access URL to share with officers)
python scripts/manage_client.py add \
  --deployment-id YOUR_DEPLOYMENT_ID \
  --client-id acme \
  --client-name "Acme Correctional Facility" \
  --region us-west-2

# List all clients on a server
python scripts/manage_client.py list --deployment-id YOUR_DEPLOYMENT_ID --region us-west-2

# Rotate token (old URL stops working within 5 minutes)
python scripts/manage_client.py rotate --deployment-id YOUR_DEPLOYMENT_ID --client-id acme --region us-west-2

# Remove a client (access revoked immediately)
python scripts/manage_client.py remove --deployment-id YOUR_DEPLOYMENT_ID --client-id acme --region us-west-2
```

### Makefile Shortcuts

```bash
make add-client    DEPLOYMENT_ID=244d4b8211 CLIENT_ID=acme CLIENT_NAME="Acme Facility"
make list-clients  DEPLOYMENT_ID=244d4b8211
make rotate-token  DEPLOYMENT_ID=244d4b8211 CLIENT_ID=acme
make remove-client DEPLOYMENT_ID=244d4b8211 CLIENT_ID=acme
```

---

## Deploy to AWS

For complete step-by-step instructions, see **[DEPLOY.md](DEPLOY.md)**.

### Quick Summary

```bash
# 1. Generate a unique 10-char deployment ID (once per server)
python3 -c "import uuid; print(uuid.uuid4().hex[:10])"

# 2. Build
sam build --template infra/template.yaml --use-container

# 3. Deploy to dev
sam deploy \
  --config-env dev \
  --config-file infra/samconfig.toml \
  --no-confirm-changeset

# 4. Add a client
python scripts/manage_client.py add \
  --deployment-id YOUR_ID \
  --client-id acme \
  --client-name "Acme Facility" \
  --region us-west-2

# 5. Share the access URL with officers
```

### Two Parameters Control Everything

| Parameter | Dev (standard AWS) | Prod (GovCloud) |
|---|---|---|
| `SyntheticMode` | `true` (fake data) | `false` (real sensors) |
| `EnableIoTRule` | `false` | `true` (BLE adapter) |

Same template, same code, different config.

---

## CI/CD with GitHub Actions

```
feature/* ──PR──▸ develop ──PR──▸ main ──tag v1.0.0──▸ production
                     │              │                      │
               auto-deploy     auto-deploy          approve per-server
                 to DEV        to STAGING         prod-a ✅ prod-b ✅ prod-c ❌
```

| Workflow | File | Trigger | What It Does |
|----------|------|---------|--------------|
| **CI** | `ci.yml` | Push/PR to `main`/`develop` | Lint + test + validate SAM. Auto-deploy to dev (develop push) or staging (main push). |
| **CD** | `cd.yml` | Git tag `v*` or manual dispatch | Test → deploy to each prod server (each gated by reviewer approval). |

See [DEPLOY.md — CI/CD section](DEPLOY.md#14-cicd-with-github-actions) for complete setup (OIDC, environments, branch protection).

---

## Configuration Reference

### Deploy-Time Parameters (SAM template)

| Parameter | Type | Default | Constraint | Description |
|-----------|------|---------|------------|-------------|
| `Environment` | String | `dev` | dev/staging/prod | Environment name |
| `DeploymentId` | String | — | `[a-z0-9]{10}` exactly | Unique server identifier |
| `ProjectPrefix` | String | `temp-sensor` | — | Resource naming prefix |
| `SyntheticMode` | String | `true` | true/false | Create synthetic data generator |
| `EnableIoTRule` | String | `false` | true/false | Create IoT Rule + BLE adapter |
| `IoTTopicPattern` | String | `sensors/temp` | — | MQTT topic for real sensors |
| `SyntheticSensorCount` | Number | `20` | — | Number of fake sensors |
| `KinesisShardCount` | Number | `1` | — | Kinesis stream shards |
| `CookieSecret` | String | auto-generated | NoEcho | HMAC key for dashboard cookies |

### Temperature Thresholds

| Threshold | Value | Triggers |
|-----------|-------|----------|
| Normal range | 65 – 85°F | In-range for compliance |
| Critical low | < 50°F | EXTREME_TEMPERATURE alert (CRITICAL) |
| Critical high | > 95°F | EXTREME_TEMPERATURE alert (CRITICAL) |
| Compliance target | 95% | Minimum acceptable in-range percentage |

### Feature Flags (per-tenant via PlatformConfig DynamoDB)

| Flag | Default | Effect |
|------|---------|--------|
| `alerts_enabled` | true | Enable/disable alert generation |
| `alert_extreme_temp` | true | Extreme temperature alerts |
| `alert_sustained_high` | true | Sustained high alerts |
| `alert_rapid_change` | true | Rapid change alerts |
| `forecasting_enabled` | true | Temperature forecasting |
| `compliance_enabled` | true | Daily compliance reports |
| `archival_enabled` | true | S3 batch archival |
| `notifications_enabled` | true | SNS notifications |
| `auto_provision` | true | Auto-create device on first reading |

---

## AWS Cost Estimation

All pricing: **us-east-1**, March 2026. GovCloud is ~10-20% higher.

### Monthly Cost by Scale

#### Small Pilot — 10 sensors, 5 users, 1 client

| Resource | Monthly Cost |
|----------|-------------|
| Kinesis (1 shard) | **$11.00** |
| Lambda (all) | **$0.00** (free tier) |
| DynamoDB (all tables) | **$0.68** |
| S3 + API Gateway + SNS | **$0.00** (free tier) |
| Secrets Manager (1 secret) | **$0.40** |
| CloudWatch | **$0.10** |
| **TOTAL** | **~$12/month** |

#### Single Facility — 50 sensors, 20 users, 3 clients

| Resource | Monthly Cost |
|----------|-------------|
| Kinesis (1 shard) | **$11.00** |
| Lambda (all) | **$0.00** (free tier) |
| DynamoDB | **$3.38** |
| S3 + API Gateway + SNS | **$0.01** |
| Secrets Manager (3 secrets) | **$1.20** |
| CloudWatch | **$1.60** |
| **TOTAL** | **~$17/month** |

#### Multi-Facility — 500 sensors, 100 users, 10 clients

| Resource | Monthly Cost |
|----------|-------------|
| Kinesis (2 shards) | **$22.00** |
| Lambda (all) | **$0.50** |
| DynamoDB | **$33.75** |
| API Gateway | **$2.00** |
| Secrets Manager (10 secrets) | **$4.00** |
| CloudWatch | **$5.10** |
| IoT Core (if real sensors) | **$22.00** |
| **TOTAL** | **~$89/month** |

### Cost Optimization

| Tip | Savings |
|-----|---------|
| DynamoDB TTL (already configured) | 30-50% on DynamoDB — old readings auto-expire |
| S3 Lifecycle (90d → Glacier) | 60-70% on S3 long-term storage |
| CloudWatch log retention (30/90 days) | 50% on log costs |
| Lambda memory tuning | 10-30% on Lambda |

### Free Tier (first 12 months)

| Service | Free Allowance |
|---------|---------------|
| Lambda | 1M requests + 400K GB-s/mo |
| DynamoDB | 25 WRU + 25 RRU |
| API Gateway | 1M requests/mo |
| SNS | 1M publishes/mo |
| CloudWatch | 10 alarms + 5 GB logs |
| IoT Core | 500K messages/mo |

After free tier expires, the pilot (~10 sensors) costs **~$12/month**.
The largest component is always **Kinesis** ($11/shard/month).

---

## Useful Commands

```bash
# ── Local Development ─────────────────────────────────────────
make install install-dev               # Install all dependencies
make run                               # Start dashboard (mock data, port 8050)
make test                              # All tests (backend + dashboard)
make test-backend                      # Backend tests only
make test-dashboard                    # Dashboard tests only
make lint                              # Lint dashboard (ruff)

# ── Build & Deploy ────────────────────────────────────────────
make validate                          # Validate SAM template
make build                             # Build SAM application
make deploy-dev                        # Deploy to dev (synthetic data)
make deploy-staging                    # Deploy to staging
make deploy-prod-a                     # Deploy to prod-a
make deploy-govcloud-prod              # Deploy to GovCloud prod

# ── Synthetic Mode Toggle (no redeploy) ──────────────────────
make synth-on  STACK=TempMonitor-dev   # Enable fake data
make synth-off STACK=TempMonitor-dev   # Disable fake data

# ── Client Management ────────────────────────────────────────
make add-client    DEPLOYMENT_ID=xxx CLIENT_ID=yyy CLIENT_NAME="Zzz"
make list-clients  DEPLOYMENT_ID=xxx
make rotate-token  DEPLOYMENT_ID=xxx CLIENT_ID=yyy
make remove-client DEPLOYMENT_ID=xxx CLIENT_ID=yyy

# ── Monitoring ────────────────────────────────────────────────
aws logs tail /aws/lambda/TempMonitor-Dashboard-ID-env --follow
aws logs tail /aws/lambda/temp-sensor-batch-processor-ID-env --follow

# ── Teardown ──────────────────────────────────────────────────
aws cloudformation delete-stack --stack-name TempMonitor-dev
make clean                             # Remove local build artifacts
```

---

## Further Reading

- **[DEPLOY.md](DEPLOY.md)** — Complete step-by-step deployment guide (prerequisites, AWS setup, SAM deploy, verification, GovCloud, CI/CD, CSV import, troubleshooting)
