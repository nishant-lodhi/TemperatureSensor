# Deployment Guide

## Prerequisites

- Python 3.10+
- AWS SAM CLI and AWS CLI v2
- MySQL Aurora cluster (or compatible) with `dg_gateway_data` table
- (Optional) S3 bucket with daily Parquet sensor files
- DynamoDB is auto-created by SAM (or simulated via `moto` locally)

## Environment Variables

### Required

| Variable | Default | Description |
|---|---|---|
| `MYSQL_HOST` | — | Aurora cluster read endpoint |
| `MYSQL_USER` | — | Database user |
| `MYSQL_PASSWORD` | — | Database password |

### Optional

| Variable | Default | Description |
|---|---|---|
| `AWS_MODE` | `false` | `true` for Lambda, `false` for local dev |
| `DATA_SOURCE` | `mysql` | `mysql`, `parquet`, or `hybrid` |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DATABASE` | `Demo_aurora` | Database name |
| `PARQUET_BUCKET` | — | S3 bucket for Parquet files (required when DATA_SOURCE includes parquet) |
| `PARQUET_PREFIX` | `sensor-data/` | S3 key prefix for daily Parquet files |
| `ALERTS_TABLE` | auto-generated | DynamoDB table name (SAM creates this) |
| `NOTE_LAMBDA_ARN` | — | Lambda ARN for officer note dispatch |
| `COOKIE_SECRET` | auto-generated | HMAC key for session cookies (set in prod) |
| `AWS_REGION` | `us-east-1` | AWS region for DynamoDB and other services |
| `CLIENT_ID` | `default` | Tenant identifier for multi-tenant deployments |

## Local Development

### Step 1: Install dependencies

```bash
git clone <repo> && cd TemperatureSensor
pip install -r dashboard/requirements.txt -r requirements-dev.txt
```

### Step 2: Configure environment

```bash
export MYSQL_HOST=your-aurora-host.cluster-ro.rds.amazonaws.com
export MYSQL_USER=your_user
export MYSQL_PASSWORD='your_password'
export MYSQL_DATABASE=your_db
export DATA_SOURCE=mysql
```

### Step 3: Run the dashboard

```bash
# Production-like local server (gunicorn, multi-threaded)
make run                  # http://localhost:8051

# Or Flask debug server (auto-reload on code changes)
make run-debug            # http://localhost:8051
```

`make run` launches gunicorn with 1 worker and 4 threads, matching production
behavior. This eliminates the callback serialization bottleneck seen with
Flask's single-threaded dev server and provides sub-second UI response times.

### Step 4: Run tests and linting

```bash
make test                 # 139 unit tests
make lint                 # ruff check (expects 0 errors)
```

### Local DynamoDB simulation

Local mode automatically uses `moto` to simulate DynamoDB in-process.
No AWS credentials or DynamoDB tables needed. Alert creation, resolution,
dismissal, cooldowns, note dispatch, and history queries all work identically
to production. The `moto` mock is created once at startup and shared for the
lifetime of the process.

### Data source switching

Change `DATA_SOURCE` to control where readings come from:

```bash
export DATA_SOURCE=mysql      # Only MySQL (default, simplest)
export DATA_SOURCE=parquet    # Only S3 Parquet (fastest for large datasets)
export DATA_SOURCE=hybrid     # Parquet first → MySQL fallback
```

In `hybrid` mode:
- Historical ranges first attempt Parquet, falling back to MySQL if no Parquet data exists
- Live/recent readings prefer MySQL for freshness
- Both paths produce the same data shape — the dashboard is agnostic to the source

## AWS Deployment

### 1. Generate a deployment ID (once per server)

```bash
python3 -c "import uuid; print(uuid.uuid4().hex[:10])"
# Example: a1b2c3d4e5
```

This ID uniquely identifies each deployment server. All AWS resources include it in their names.

### 2. Configure `infra/samconfig.toml`

Uncomment and fill the section for your target server. Example for `prod-a`:

```toml
[prod-a.deploy.parameters]
stack_name = "TempMonitor-saas-prod-a"
resolve_s3 = true
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
region = "us-west-2"
parameter_overrides = """
  Environment=prod
  DeploymentId=a1b2c3d4e5
  DataSource=hybrid
  MysqlHost=prod-aurora.rds.amazonaws.com
  MysqlPort=3306
  MysqlUser=reader
  MysqlDatabase=sensor_data
  ParquetBucket=my-sensor-bucket
  ParquetPrefix=parquet/temp-sensor/
"""
```

Each environment section maps to a `--config-env` value used in deploy commands.

### 3. Deploy

```bash
# Build + deploy
sam build --template-file infra/template.yaml
sam deploy --config-env prod-a --config-file infra/samconfig.toml \
  --parameter-overrides "MysqlPassword=$MYSQL_PASSWORD"
```

The password is passed at deploy time (not stored in `samconfig.toml`) for security.

### 4. Add clients (multi-tenancy)

Each client gets a unique access token stored in AWS Secrets Manager:

```bash
# Creates secret: TempMonitor/{deployment_id}/{client_id}
# Returns access URL: https://{api-gw}/connect/{token}
aws secretsmanager create-secret \
  --name "TempMonitor/a1b2c3d4e5/client_a" \
  --secret-string '{"client_id":"client_a","name":"Facility A","token":"<generated-uuid>"}'
```

Officers visit the `/connect/{token}` URL once. The app validates the token against
Secrets Manager, sets a signed HttpOnly cookie (30-day expiry), and all subsequent
requests use the cookie for authentication. No passwords to remember.

### 5. Health check

```bash
curl https://{api-gw-url}/healthz
# Returns: {"status":"healthy","timestamp":"2026-03-11T10:30:00Z"}
```

## CI/CD Setup (GitHub Actions)

### Workflow files

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | PR checks: lint + test + SAM validate |
| `.github/workflows/cd.yml` | Continuous deploy: dev → staging → prod |

### Pipeline flow

```
PR created ──▶ ci.yml ──▶ lint + test + SAM validate ──▶ merge
                                                            │
Push to develop ──▶ cd.yml ──▶ deploy to DEV (auto)        │
Push to main ─────▶ cd.yml ──▶ deploy to STAGING (auto)    │
Git tag v* ───────▶ cd.yml ──▶ deploy to PROD (approval-gated per server)
Manual dispatch ──▶ cd.yml ──▶ deploy to any server
```

### Required GitHub secrets (per environment)

| Secret | Description |
|---|---|
| `DEPLOYMENT_ID` | 10-char unique per server |
| `AWS_DEPLOY_ROLE_ARN` | IAM role with OIDC trust for GitHub |
| `MYSQL_PASSWORD` | Database password (injected at deploy time) |

### Required GitHub variables (optional)

| Variable | Description |
|---|---|
| `AWS_REGION` | Override default `us-west-2` |

### GitHub Environments

Create one environment per deployment target:
- `dev` — auto-deploy, no approval
- `staging` — auto-deploy, no approval
- `prod-a`, `prod-b`, `prod-c` — required reviewers configured

### OIDC Configuration (one-time)

```bash
# Create OIDC provider in AWS
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com

# Create deploy role with trust policy for your repo
# See: https://docs.github.com/en/actions/security-for-github-actions/
#      security-hardening-your-deployments/
#      configuring-openid-connect-in-amazon-web-services
```

The deploy role needs permissions for: CloudFormation, Lambda, API Gateway,
DynamoDB, S3 (for SAM artifacts), IAM (role creation), and CloudWatch.

## AWS Resources Created

| Resource | Name Pattern | Purpose |
|---|---|---|
| Lambda | `TempMonitor-Dashboard-{id}-{env}` | Dash app (512MB, 30s timeout) |
| HTTP API | auto-generated | API Gateway v2 |
| DynamoDB | `TempMonitor-Alerts-{id}` | Alert persistence (PAY_PER_REQUEST) |
| CloudWatch Alarm | `TempMonitor-Dashboard-Errors-{id}-{env}` | Error alerting |

DynamoDB table has:
- Partition key: `PK` (e.g., `ALERT#device_id#alert_type`)
- Sort key: `SK` (e.g., `CLIENT#client_id`)
- GSI `ClientActiveAlerts`: for querying all alerts by `client_id`
- TTL on `expires_at` (90 days)

## Rollback

Re-run the CD workflow for a previous Git tag:

```bash
# Or manually
git checkout v1.0.0
sam deploy --config-env prod-a --config-file infra/samconfig.toml \
  --parameter-overrides "MysqlPassword=$MYSQL_PASSWORD"
```

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| Dashboard slow (3-5s clicks) | Single-threaded Flask server | Use `make run` (gunicorn) instead of `make run-debug` |
| Blank chart on 60-120 day range | Too many data points | Downsampling is automatic (2000 pts); check MySQL query limits |
| Alerts not showing for auto-selected sensor | `mon-selected` store not populated | Fixed in data pump — auto-selects first sensor on load |
| Compliance shows 0% | All sensors offline | Expected — shows "Last Known Compliance" label |
| `moto` errors on startup | Wrong moto version | Ensure `moto>=5.0` in requirements |
| MySQL connection timeouts | Aurora idle connection pruning | Auto-retry with fresh connection is built in |
| Parquet not found (hybrid mode) | S3 bucket/prefix misconfigured | Falls back to MySQL automatically; check `PARQUET_BUCKET` and `PARQUET_PREFIX` |
