# TempMonitor — Complete Deployment Guide

Step-by-step guide to deploy TempMonitor from scratch on AWS.
Written for beginners — every command is copy-pasteable, every output is shown.

Works identically on **standard AWS** and **GovCloud** — same template,
same commands, different config.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and Install](#2-clone-and-install)
3. [Run Locally (Verify Before AWS)](#3-run-locally)
4. [Run Tests](#4-run-tests)
5. [AWS Account Setup](#5-aws-account-setup)
6. [Generate a Deployment ID](#6-generate-a-deployment-id)
7. [Configure samconfig.toml](#7-configure-samconfigtoml)
8. [Build the Application](#8-build-the-application)
9. [Deploy to AWS](#9-deploy-to-aws)
10. [Verify the Deployment](#10-verify-the-deployment)
11. [Add Your First Client](#11-add-your-first-client)
12. [Test the Dashboard](#12-test-the-dashboard)
13. [Verify Data Pipeline](#13-verify-data-pipeline)
14. [CI/CD with GitHub Actions](#14-cicd-with-github-actions)
15. [GovCloud Deployment](#15-govcloud-deployment)
16. [Synthetic Mode](#16-synthetic-mode)
17. [Connecting Real Sensors](#17-connecting-real-sensors)
18. [Import Historical CSV Data](#18-import-historical-csv-data)
19. [Subsequent Deployments](#19-subsequent-deployments)
20. [Multi-Server Setup](#20-multi-server-setup)
21. [Client Management](#21-client-management)
22. [Monitoring and Logs](#22-monitoring-and-logs)
23. [Troubleshooting](#23-troubleshooting)
24. [Teardown](#24-teardown)
25. [Quick Reference](#25-quick-reference)

---

## 1. Prerequisites

Install these tools on your computer before starting.

| Tool | Minimum Version | Install |
|------|----------------|---------|
| **Python** | 3.10+ | https://python.org/downloads |
| **pip** | 21+ | Comes with Python |
| **AWS CLI** | v2 | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html |
| **AWS SAM CLI** | 1.90+ | `pip install aws-sam-cli` |
| **Docker** | 20+ | https://docs.docker.com/get-docker/ (needed for `sam build --use-container`) |
| **Git** | any | `sudo apt install git` (Linux) or https://git-scm.com |

### Verify All Tools

Run each command and confirm the version:

```bash
python3 --version        # Must show 3.10 or higher
pip --version            # Must show 21 or higher
aws --version            # Must show aws-cli/2.x.x
sam --version            # Must show SAM CLI, version 1.x.x
docker --version         # Must show Docker version 20.x or higher
git --version            # Any version
```

If any command says "not found", install that tool first.

---

## 2. Clone and Install

```bash
# Clone the repository
git clone <your-repo-url>
cd temp_sensors

# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate    # Linux/Mac
# .venv\Scripts\activate     # Windows

# Install all dependencies (production + development)
make install install-dev
```

**If `make` is not available**, run manually:

```bash
pip install -r src/requirements.txt
pip install -r dashboard/requirements.txt
pip install -r requirements-dev.txt
```

### Verify Installation

```bash
python3 -c "import dash; print('Dash', dash.__version__)"
python3 -c "import boto3; print('Boto3', boto3.__version__)"
python3 -c "import numpy; print('NumPy', numpy.__version__)"
```

All three should print version numbers without errors.

---

## 3. Run Locally

Before deploying to AWS, verify everything works locally with mock data.

```bash
make run
```

**Expected output:**

```
Dash is running on http://0.0.0.0:8050/
```

Open **http://localhost:8050** in your browser. You should see:

- **Live Monitor** tab — 20 sensor tiles with temperatures, battery icons, WiFi icons
- Click any sensor tile — detail panel appears with a chart
- Click the alert count in the banner — alert drawer expands
- **History & Reports** tab — dropdown to select sensor, time range, forecast

Press `Ctrl+C` to stop.

---

## 4. Run Tests

```bash
make test
```

**Expected output (last lines):**

```
tests/ ─────────────── 343 passed
dashboard/tests/ ───── 156 passed, 1 skipped
```

If any tests fail, fix them before deploying. Common issue: missing dependency.
Try `make install install-dev` again.

---

## 5. AWS Account Setup

### Step 1: Create an IAM User for Deployment

1. Log in to **AWS Console** → search **IAM** → click **Users** → **Create user**
2. User name: `tempmonitor-deployer`
3. Click **Next**
4. Select **Attach policies directly**
5. Search and check each of these policies:
   - `AdministratorAccess` (simplest option for getting started)
6. Click **Next** → **Create user**

> For tighter security, instead of AdministratorAccess use these individual policies:
> `AWSCloudFormationFullAccess`, `AWSLambda_FullAccess`, `AmazonDynamoDBFullAccess`,
> `AmazonS3FullAccess`, `AmazonAPIGatewayAdministrator`, `IAMFullAccess`,
> `AmazonKinesisFullAccess`, `AmazonSNSFullAccess`, `AWSIoTFullAccess`,
> `SecretsManagerReadWrite`, `CloudWatchFullAccess`

### Step 2: Create Access Keys

1. Click on the user you just created → **Security credentials** tab
2. Scroll to **Access keys** → **Create access key**
3. Select **Command Line Interface (CLI)** → check the confirmation → **Next** → **Create**
4. **Copy both values** (Access Key ID + Secret Access Key) — you won't see them again

### Step 3: Configure AWS CLI

```bash
# If you want to use a named profile (recommended for multiple AWS accounts):
aws configure --profile tempmonitor
```

Enter these when prompted:

```
AWS Access Key ID:     AKIA...       (paste your access key)
AWS Secret Access Key: wJal...       (paste your secret key)
Default region name:   us-west-2     (or your preferred region)
Default output format: json
```

### Step 4: Verify AWS Access

```bash
aws sts get-caller-identity --profile tempmonitor
```

**Expected output:**

```json
{
    "UserId": "AIDAXXXXXXXXXXXXXXXXX",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/tempmonitor-deployer"
}
```

If you see an error, double-check your access key and secret key.

> **Important**: If you use `--profile tempmonitor`, you must add it to every
> AWS CLI and SAM command below. Alternatively, set an environment variable:
> `export AWS_PROFILE=tempmonitor`

---

## 6. Generate a Deployment ID

Every server (dev, staging, prod) gets a unique 10-character alphanumeric ID.
This ID is embedded in all resource names to prevent conflicts.

```bash
python3 -c "import uuid; print(uuid.uuid4().hex[:10])"
```

**Example output:** `a3f7b2c1d4`

**Rules:**
- Exactly 10 characters
- Only lowercase letters and digits (`[a-z0-9]{10}`)
- NO dashes, NO uppercase, NO special characters
- Generate ONCE per server, then reuse forever

**Save this ID.** Write it down. You'll need it for every deploy command.

---

## 7. Configure samconfig.toml

Open `infra/samconfig.toml` and update the dev section with your deployment ID and region:

```toml
[dev.deploy.parameters]
stack_name = "TempMonitor-dev"
resolve_s3 = true
capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"
parameter_overrides = "Environment=dev DeploymentId=YOUR_ID_HERE ProjectPrefix=temp-sensor SyntheticMode=true EnableIoTRule=false"
confirm_changeset = false
region = "us-west-2"
```

Replace `YOUR_ID_HERE` with the deployment ID from step 6.

**The `region` must match what you configured in `aws configure`.**

---

## 8. Build the Application

```bash
sam build --template infra/template.yaml --use-container
```

**What this does:**
- Reads `infra/template.yaml` to find all Lambda functions
- Installs their Python dependencies (from `requirements.txt`)
- Packages everything into `.aws-sam/build/`

**Expected output (last lines):**

```
Build Succeeded

Built Artifacts  : .aws-sam/build
Built Template   : .aws-sam/build/template.yaml
```

**If the build fails:**

```bash
# Clear cache and retry
rm -rf .aws-sam/
sam build --template infra/template.yaml --use-container
```

> `--use-container` runs the build inside a Docker container matching the Lambda
> runtime (Python 3.11). This avoids issues when your local Python version differs.
> If you don't have Docker, try without `--use-container` — it works if your local
> Python is 3.11.

---

## 9. Deploy to AWS

### Option A: Using samconfig.toml (Recommended)

If you configured `infra/samconfig.toml` in step 7:

```bash
sam deploy --config-env dev --config-file infra/samconfig.toml --no-confirm-changeset
```

### Option B: Using Makefile

```bash
make deploy-dev
```

### Option C: Full Manual Command

If samconfig doesn't work or you prefer explicit control:

```bash
sam deploy \
  --stack-name TempMonitor-dev \
  --region us-west-2 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --resolve-s3 \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    "Environment=dev \
     DeploymentId=YOUR_ID_HERE \
     ProjectPrefix=temp-sensor \
     SyntheticMode=true \
     EnableIoTRule=false \
     SyntheticSensorCount=20"
```

> **If using a named AWS profile**, add `--profile tempmonitor` to the command.

### What Happens During Deploy

SAM creates a CloudFormation stack. You'll see resources being created:

```
CloudFormation events from stack operations (refresh every 5.0 seconds)
------------------------------------------------------------------
ResourceStatus         ResourceType              LogicalResourceId
------------------------------------------------------------------
CREATE_IN_PROGRESS     AWS::DynamoDB::Table      SensorDataTable
CREATE_IN_PROGRESS     AWS::Kinesis::Stream      SensorDataStream
CREATE_COMPLETE        AWS::DynamoDB::Table      SensorDataTable
CREATE_COMPLETE        AWS::Lambda::Function     BatchProcessorFunction
...
CREATE_COMPLETE        AWS::CloudFormation::Stack TempMonitor-dev
------------------------------------------------------------------
```

**Total time:** 3-8 minutes for first deploy, 1-3 minutes for updates.

### Common Deploy Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Parameter DeploymentId failed to satisfy constraint` | ID is not exactly 10 lowercase alphanumeric chars | Generate a new ID: `python3 -c "import uuid; print(uuid.uuid4().hex[:10])"` |
| `ROLLBACK_COMPLETE` state | First deploy failed midway | Delete the stack first: `aws cloudformation delete-stack --stack-name TempMonitor-dev` then wait and retry |
| `Unable to locate credentials` | AWS CLI not configured | Run `aws configure` or set `AWS_PROFILE` |
| `S3 bucket does not exist` | Missing artifact bucket | Use `--resolve-s3` flag (SAM creates one automatically) |
| `InsufficientCapabilities` | IAM permissions needed | Use `--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM` |

---

## 10. Verify the Deployment

After deploy succeeds, verify all resources were created correctly.

### Step 1: Check Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name TempMonitor-dev \
  --region us-west-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

**Expected output:**

```
---------------------------------------------------------------------------
|                            DescribeStacks                               |
+----------------------------+--------------------------------------------+
|         OutputKey          |               OutputValue                  |
+----------------------------+--------------------------------------------+
| DashboardUrl               | https://xxxxx.execute-api.us-west-2...    |
| SensorDataTableName        | temp-sensor-sensor-data-YOUR_ID-dev       |
| AlertsTableName            | temp-sensor-alerts-YOUR_ID-dev            |
| BatchProcessorArn          | arn:aws:lambda:...                        |
| ScheduledProcessorArn      | arn:aws:lambda:...                        |
| SensorDataStreamName       | temp-sensor-sensor-stream-YOUR_ID-dev     |
| DataLakeBucketName         | temp-sensor-data-lake-YOUR_ID-dev         |
+----------------------------+--------------------------------------------+
```

**Save the `DashboardUrl`** — this is your dashboard's HTTPS URL.

### Step 2: Verify Synthetic Data Generator Is Running

If `SyntheticMode=true`, the generator should start immediately:

```bash
aws logs tail /aws/lambda/temp-sensor-synthetic-gen-YOUR_ID-dev \
  --since 5m --region us-west-2 --format short
```

You should see log lines like:

```
Put 20 records to Kinesis stream temp-sensor-sensor-stream-...
```

If no logs appear, wait 2 minutes (EventBridge triggers every 1 minute).

### Step 3: Verify Batch Processor Is Running

```bash
aws logs tail /aws/lambda/temp-sensor-batch-processor-YOUR_ID-dev \
  --since 5m --region us-west-2 --format short
```

You should see:

```
Processed 20 events: 20 valid, 0 invalid
```

### Step 4: Verify DynamoDB Has Data

```bash
aws dynamodb scan \
  --table-name temp-sensor-sensor-data-YOUR_ID-dev \
  --filter-expression "sk = :s" \
  --expression-attribute-values '{":s":{"S":"STATE"}}' \
  --select COUNT \
  --region us-west-2
```

**Expected:** Count should be 20 (or your `SyntheticSensorCount`).

---

## 11. Add Your First Client

A **client** is a facility that gets its own isolated view of the dashboard.

```bash
python scripts/manage_client.py add \
  --deployment-id YOUR_ID \
  --client-id myfacility \
  --client-name "My Correctional Facility" \
  --region us-west-2
```

> Add `--profile tempmonitor` if using a named AWS profile.

**Expected output:**

```
Client created successfully.
  Client ID:    myfacility
  Access Token: a7f3b2c1-d4e5-f6a7-b8c9-0d1e2f3a4b5c

Dashboard URL: https://xxxxx.execute-api.us-west-2.amazonaws.com/connect/a7f3b2c1-d4e5-...
```

**This is the URL you share with officers.** Anyone with this URL can access
the dashboard for this client.

> **Important**: The `client-id` in the `manage_client.py add` command must match
> the `client_id` that sensors send in their data. For synthetic mode, the
> synthetic generator automatically uses the DeploymentId as the client_id.
> So if your DeploymentId is `244d4b8211`, use that as the client-id:
>
> ```bash
> python scripts/manage_client.py add \
>   --deployment-id 244d4b8211 \
>   --client-id 244d4b8211 \
>   --client-name "Dev Test Facility" \
>   --region us-west-2
> ```

---

## 12. Test the Dashboard

1. Open the access URL from step 11 in your browser
2. You should be redirected to the dashboard at `/`
3. A session cookie is set automatically (valid for 30 days)

**What you should see (SyntheticMode=true):**

- **Live Monitor**: 20 sensor tiles with temperatures around 74-79°F
- Tiles show battery icon and WiFi signal icon
- Click a tile → detail panel with 2-hour chart
- Banner shows sensor count, average temp, alert count
- **History & Reports**: Select a sensor, pick 6h/12h/24h/48h range
- Chart shows actual readings; forecast appears after ~1 hour

**If you see "No data":** wait 2-3 minutes for the synthetic generator to
produce enough data, then refresh. See [Troubleshooting](#23-troubleshooting)
for common issues.

---

## 13. Verify Data Pipeline

After 15-20 minutes, verify the full pipeline is working:

### Analytics (runs every 15 min)

```bash
aws logs tail /aws/lambda/temp-sensor-scheduled-processor-YOUR_ID-dev \
  --since 20m --region us-west-2 --format short | head -20
```

Look for: `Analytics completed for X devices`

### Forecast (runs every 1 hour)

The forecast model needs ≥10 readings per sensor. If you just deployed,
wait 10+ minutes then manually trigger it:

```bash
# Create a payload file
echo '{"mode":"forecast"}' > /tmp/fc_payload.json

# Invoke the scheduled processor
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-dev \
  --payload file:///tmp/fc_payload.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/fc_output.json

cat /tmp/fc_output.json
```

Look for: `Forecast completed for X devices` (X should be > 0).

### Verify on Dashboard

After the forecast runs, refresh the History tab. The forecast line should
appear on the chart (dotted line extending beyond "Now").

---

## 14. CI/CD with GitHub Actions

### 14.1 Overview

```
feature/* ──PR──▸ develop ──PR──▸ main ──tag v1.0.0──▸ production
                     │              │                      │
               auto-deploy     auto-deploy          approve per-server
                 to DEV        to STAGING         prod-a ✅ prod-b ✅ prod-c ❌
```

| Workflow | File | Trigger | Action |
|----------|------|---------|--------|
| **CI** | `ci.yml` | Push/PR to `main`/`develop` | Lint + test + auto-deploy to dev/staging |
| **CD** | `cd.yml` | Tag `v*` or manual dispatch | Test → deploy to prod (per-server approval) |

### 14.2 One-Time Setup: AWS OIDC Provider

GitHub Actions authenticates with AWS via OIDC (no stored access keys).

1. **AWS Console** → **IAM** → **Identity providers** → **Add provider**
   - Provider type: **OpenID Connect**
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Click **Get thumbprint**
   - Audience: `sts.amazonaws.com`
   - Click **Add provider**

2. **IAM** → **Roles** → **Create role**
   - Trusted entity: **Web identity**
   - Identity provider: `token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
   - Attach policies: same list as [step 5](#5-aws-account-setup) above
   - Role name: `TempMonitor-GitHubActions-Deploy`

3. **Edit the role's trust policy** → replace Condition with:

```json
"Condition": {
    "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:YOUR_ORG/temp-sensors:*"
    },
    "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
    }
}
```

4. **Copy the Role ARN**: `arn:aws:iam::123456789012:role/TempMonitor-GitHubActions-Deploy`

### 14.3 One-Time Setup: GitHub Environments

Go to GitHub repo → **Settings** → **Environments** → create each:

| Environment | Required Reviewers | Branch Restriction |
|---|---|---|
| `dev` | None | `develop`, `main` |
| `staging` | Optional (1) | `main` only |
| `prod-a` | 2 reviewers | tags `v*` |
| `prod-b` | 2 reviewers | tags `v*` |
| `prod-c` | 2 reviewers | tags `v*` |
| `govcloud-prod` | 2 reviewers | tags `v*` |

**For each environment, add these secrets:**

| Secret Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | ARN from step 14.2 |
| `DEPLOYMENT_ID` | 10-char ID for this server |

**Add this environment variable (not secret):**

| Variable | Value |
|---|---|
| `AWS_REGION` | `us-west-2` (or `us-gov-west-1` for GovCloud) |

### 14.4 Branch Protection

**Settings** → **Branches** → **Add rule:**

| Branch | Require PR | Required Checks |
|--------|-----------|-----------------|
| `main` | Yes (1 approval) | Backend Tests, Dashboard Tests (3.10), Dashboard Tests (3.12), Validate SAM Template |
| `develop` | Yes (1 approval) | Backend Tests, Dashboard Tests (3.10), Dashboard Tests (3.12) |

### 14.5 Daily Workflow

```bash
# Start feature
git checkout develop && git pull
git checkout -b feature/my-change

# Make changes, test locally
make test

# Push and create PR
git add . && git commit -m "Add feature X"
git push -u origin feature/my-change
gh pr create --base develop --title "Add feature X"
# → CI runs → reviewer approves → merge → auto-deploy to DEV

# Promote to staging
gh pr create --base main --head develop --title "Release: promote to staging"
# → merge → auto-deploy to STAGING

# Release to production
git checkout main && git pull
git tag v1.0.0 && git push origin v1.0.0
# → CD runs → approve prod-a ✅ → approve prod-b ✅ → skip prod-c ❌
```

### 14.6 Rollback

```bash
# Redeploy last good version
git checkout v1.0.0
make deploy-prod-a

# Or via GitHub Actions: Actions → CD → Run workflow → select tag v1.0.0
```

---

## 15. GovCloud Deployment

The same template works in GovCloud. The only differences:

| Aspect | Standard AWS | GovCloud |
|--------|-------------|----------|
| Region | `us-west-2` | `us-gov-west-1` |
| ARN partition | `aws` | `aws-us-gov` (auto via `AWS::Partition`) |
| Architecture | `x86_64` | `x86_64` (same) |

### Step-by-Step

```bash
# 1. Configure AWS CLI for GovCloud
aws configure --profile govcloud
# Region: us-gov-west-1

# 2. Generate deployment ID
python3 -c "import uuid; print(uuid.uuid4().hex[:10])"

# 3. Edit infra/samconfig.toml — uncomment and update govcloud-prod section

# 4. Build
sam build --template infra/template.yaml --use-container

# 5. Deploy
sam deploy \
  --config-env govcloud-prod \
  --config-file infra/samconfig.toml \
  --profile govcloud \
  --no-confirm-changeset

# 6. Get dashboard URL
aws cloudformation describe-stacks \
  --stack-name TempMonitor-govcloud-prod \
  --region us-gov-west-1 \
  --profile govcloud \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' \
  --output text

# 7. Add a client
AWS_PROFILE=govcloud python scripts/manage_client.py add \
  --deployment-id YOUR_GOVCLOUD_ID \
  --client-id facility1 \
  --client-name "Facility One" \
  --region us-gov-west-1
```

---

## 16. Synthetic Mode

### When to Use

| Scenario | SyntheticMode | EnableIoTRule |
|----------|---------------|---------------|
| **Local development** | N/A (uses mock data) | N/A |
| **Dev/testing on AWS** | `true` | `false` |
| **Prod with real sensors** | `false` | `true` |
| **Prod testing before sensors arrive** | `true` (temporary) | `false` |

### How It Works

When `SyntheticMode=true`:
- Lambda `synthetic-gen` is created with EventBridge trigger (every 1 minute)
- Generates readings for 20 sensors (configurable via `SyntheticSensorCount`)
- Sensor IDs are deterministic: MD5(`synth-{DeploymentId}-{index}`) → `C3` + 10 hex chars
- Temperature: base 74°F + diurnal sine + noise; 5% chance of anomaly (40-50°F or 95-110°F)
- Data flows through Kinesis → BatchProcessor → DynamoDB (identical to real sensors)

### Toggle Without Redeploying

```bash
make synth-on  STACK=TempMonitor-dev     # Enable synthetic data
make synth-off STACK=TempMonitor-dev     # Disable synthetic data
```

This updates the CloudFormation parameter — takes 2-3 minutes.

---

## 17. Connecting Real Sensors

### Generic MQTT Sensors (Standard AWS, EnableIoTRule=false)

Sensors publish to `sensors/temp` with this JSON format:

```json
{
  "device_id": "C3D45DC29E62",
  "client_id": "your_client_id",
  "temperature": 72.5,
  "battery_pct": 85,
  "signal_dbm": -48,
  "timestamp": "2026-03-09T14:30:00Z"
}
```

Two IoT Rules are auto-created:
- **AllDataRule**: routes all messages to Kinesis
- **CriticalTempRule**: routes extreme temps (>95°F, <50°F) to CriticalAlert Lambda

### BLE Sensors (GovCloud, EnableIoTRule=true)

When `EnableIoTRule=true`, the IoT Adapter Lambda decodes BLE rawData hex:

```
Physical BLE Sensor → Gateway → MQTT → IoT Core → IoT Adapter Lambda → Kinesis
```

BLE payload format: temperature from bytes 10-11, battery from byte 20.
Configure the MQTT topic in `samconfig.toml`:

```toml
IoTTopicPattern=/gw/+/lpsogateway1
```

### Test with MQTT Client

1. AWS Console → IoT Core → MQTT test client
2. Publish to topic: `sensors/temp`
3. Paste the JSON above → Publish
4. Check dashboard — reading appears within 30 seconds

---

## 18. Import Historical CSV Data

Import sensor data from a CSV file into DynamoDB. The sensors appear as
**offline** on the dashboard with full historical data.

### CSV Format

The CSV must have these columns:
- `mac` — sensor MAC address (e.g., `C30000301A80`)
- `body_temperature` — temperature in °F
- `rssi` — signal strength in dBm
- `power` — power level
- `timestamp` — ISO 8601 timestamp (e.g., `2024-10-05T14:30:00Z`)
- `gateway_mac` — gateway MAC address

### Import Command

```bash
python scripts/import_csv_sensor.py \
  --csv data/temp-sensor-final.csv \
  --table temp-sensor-sensor-data-YOUR_ID-dev \
  --alerts-table temp-sensor-alerts-YOUR_ID-dev \
  --client-id YOUR_CLIENT_ID \
  --region us-west-2 \
  --profile tempmonitor
```

### What It Does

1. Parses the CSV and normalizes timestamps
2. Aggregates readings into 1-minute buckets
3. Writes STATE record (sensor marked as **offline** with `last_seen` = last reading time)
4. Writes READING records (`R#{timestamp}`)
5. Creates alerts for any threshold breaches found in the data

### After Import

- The sensor appears in the Live Monitor grid as an **offline** (gray) tile
- In History tab, selecting the sensor shows its historical data
- The x-axis is bounded to the data range (no empty gap to current date)
- KPIs show "Last" instead of "Current" and "Last Reading" instead of "Forecast"

---

## 19. Subsequent Deployments

After code changes, redeploy with zero downtime:

```bash
# Build
sam build --template infra/template.yaml --use-container

# Deploy (uses saved config)
sam deploy --config-env dev --config-file infra/samconfig.toml --no-confirm-changeset
```

Or with Makefile:

```bash
make deploy-dev
```

CloudFormation updates only the resources that changed. Typical update: 1-3 minutes.

---

## 20. Multi-Server Setup

Deploy separate stacks for different environments or client groups.

```bash
# Generate unique IDs for each server
python3 -c "import uuid; print('prod-a:', uuid.uuid4().hex[:10])"
python3 -c "import uuid; print('prod-b:', uuid.uuid4().hex[:10])"

# Edit infra/samconfig.toml — uncomment and update prod-a, prod-b sections

# Deploy each server
make deploy-prod-a
make deploy-prod-b
```

Each server is completely independent: separate DynamoDB tables, separate Kinesis
streams, separate dashboards, separate client lists.

---

## 21. Client Management

```bash
# List all clients
python scripts/manage_client.py list \
  --deployment-id YOUR_ID --region us-west-2

# Rotate token (old URL stops working within 5 min)
python scripts/manage_client.py rotate \
  --deployment-id YOUR_ID --client-id myfacility --region us-west-2

# Remove client (access revoked immediately)
python scripts/manage_client.py remove \
  --deployment-id YOUR_ID --client-id myfacility --region us-west-2
```

---

## 22. Monitoring and Logs

### CloudWatch Alarm

The stack includes an alarm when the Dashboard Lambda has ≥5 errors in 5 minutes.

### View Logs

Replace `YOUR_ID` and `ENV` with your actual values:

```bash
# Dashboard logs
aws logs tail /aws/lambda/TempMonitor-Dashboard-YOUR_ID-ENV \
  --follow --region us-west-2

# Batch processor logs
aws logs tail /aws/lambda/temp-sensor-batch-processor-YOUR_ID-ENV \
  --follow --region us-west-2

# Scheduled processor logs
aws logs tail /aws/lambda/temp-sensor-scheduled-processor-YOUR_ID-ENV \
  --follow --region us-west-2

# Synthetic generator logs
aws logs tail /aws/lambda/temp-sensor-synthetic-gen-YOUR_ID-ENV \
  --follow --region us-west-2

# IoT adapter logs (only when EnableIoTRule=true)
aws logs tail /aws/lambda/temp-sensor-iot-adapter-YOUR_ID-ENV \
  --follow --region us-west-2
```

### Manually Trigger Scheduled Tasks

Useful for testing or forcing analytics/forecast to run immediately:

```bash
# Trigger analytics
echo '{"mode":"analytics"}' > /tmp/payload.json
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-ENV \
  --payload file:///tmp/payload.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/output.json && cat /tmp/output.json

# Trigger forecast
echo '{"mode":"forecast"}' > /tmp/payload.json
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-ENV \
  --payload file:///tmp/payload.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/output.json && cat /tmp/output.json

# Trigger compliance report
echo '{"mode":"compliance"}' > /tmp/payload.json
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-ENV \
  --payload file:///tmp/payload.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/output.json && cat /tmp/output.json
```

---

## 23. Troubleshooting

### Dashboard loads but shows no data

**Cause 1:** `client_id` mismatch. The synthetic generator uses `DeploymentId` as the
client_id. If you created a client with a different ID, data won't match.

**Fix:** Create a client whose `client-id` matches `DeploymentId`:

```bash
python scripts/manage_client.py add \
  --deployment-id YOUR_ID \
  --client-id YOUR_ID \
  --client-name "Test" \
  --region us-west-2
```

**Cause 2:** Synthetic generator not running. Check logs:

```bash
aws logs tail /aws/lambda/temp-sensor-synthetic-gen-YOUR_ID-dev \
  --since 5m --region us-west-2
```

**Cause 3:** SyntheticMode is false. Verify stack parameters:

```bash
aws cloudformation describe-stacks \
  --stack-name TempMonitor-dev \
  --region us-west-2 \
  --query 'Stacks[0].Parameters'
```

### Forecast not showing on dashboard

**Cause:** The forecast model needs ≥10 readings per sensor. The hourly schedule
may not have run yet, or there wasn't enough data when it ran.

**Fix:** Wait 10+ minutes (for 10 readings at 1/min), then manually invoke:

```bash
echo '{"mode":"forecast"}' > /tmp/fc.json
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-dev \
  --payload file:///tmp/fc.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/fc_out.json && cat /tmp/fc_out.json
```

Check logs for "Forecast completed for X devices" — X should be > 0.

### Signal icons or battery not showing

**Cause:** Analytics hasn't run yet (runs every 15 min). The `signal_label`
field is computed during analytics.

**Fix:** Wait 15 minutes, or manually trigger analytics:

```bash
echo '{"mode":"analytics"}' > /tmp/an.json
aws lambda invoke \
  --function-name temp-sensor-scheduled-processor-YOUR_ID-dev \
  --payload file:///tmp/an.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/an_out.json
```

### SAM build fails

```bash
# Clear cache and retry
rm -rf .aws-sam/
sam build --template infra/template.yaml --use-container

# If Docker issues, try without container (requires Python 3.11 locally)
sam build --template infra/template.yaml
```

### SAM deploy fails with ROLLBACK_COMPLETE

The stack is in a failed state from a previous deploy attempt.

```bash
# Delete the failed stack
aws cloudformation delete-stack --stack-name TempMonitor-dev --region us-west-2

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name TempMonitor-dev --region us-west-2

# Deploy again
sam deploy --config-env dev --config-file infra/samconfig.toml --no-confirm-changeset
```

### "session expired" for all users

**Cause:** Token was rotated or Secrets Manager cache is stale (5-min cache).

**Fix:** Wait 5 minutes. If persistent, check the secret exists:

```bash
aws secretsmanager get-secret-value \
  --secret-id TempMonitor/YOUR_ID/CLIENT_ID \
  --region us-west-2 \
  --query 'SecretString' --output text
```

### Lambda returning 502

Check logs for the specific error:

```bash
aws logs tail /aws/lambda/TempMonitor-Dashboard-YOUR_ID-dev \
  --since 5m --region us-west-2 --format short
```

Common causes: missing environment variable, DynamoDB table not found, Lambda memory.

### AWS CLI says "Unable to locate credentials"

```bash
# Verify credentials
aws sts get-caller-identity --profile tempmonitor

# If using a profile, ensure it's set
export AWS_PROFILE=tempmonitor

# Or add --profile to every command
aws logs tail ... --profile tempmonitor
```

### "InvalidBase64" when invoking Lambda manually

Don't pass JSON directly to `--payload`. Use a file:

```bash
echo '{"mode":"analytics"}' > /tmp/payload.json
aws lambda invoke \
  --function-name FUNCTION_NAME \
  --payload file:///tmp/payload.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/output.json
```

---

## 24. Teardown

### Delete the CloudFormation Stack

```bash
# Empty the S3 bucket first (CloudFormation can't delete non-empty buckets)
aws s3 rm s3://temp-sensor-data-lake-YOUR_ID-dev --recursive --region us-west-2

# Delete the stack
aws cloudformation delete-stack --stack-name TempMonitor-dev --region us-west-2

# Wait for completion
aws cloudformation wait stack-delete-complete --stack-name TempMonitor-dev --region us-west-2
```

### Delete Secrets Manager Secrets

```bash
# List secrets for this deployment
aws secretsmanager list-secrets \
  --filter Key=name,Values=TempMonitor/YOUR_ID \
  --query 'SecretList[].Name' --output text \
  --region us-west-2

# Delete each secret
aws secretsmanager delete-secret \
  --secret-id TempMonitor/YOUR_ID/CLIENT_ID \
  --force-delete-without-recovery \
  --region us-west-2
```

---

## 25. Quick Reference

```bash
# ── Local ─────────────────────────────────────────────────────
make install install-dev                    # Install everything
make run                                    # Dashboard with mock data
make test                                   # All tests
make lint                                   # Lint dashboard

# ── Build ─────────────────────────────────────────────────────
sam build --template infra/template.yaml --use-container

# ── Deploy ────────────────────────────────────────────────────
sam deploy --config-env dev --config-file infra/samconfig.toml --no-confirm-changeset
# Or:
make deploy-dev
make deploy-staging
make deploy-prod-a
make deploy-govcloud-prod

# ── Client Management ────────────────────────────────────────
python scripts/manage_client.py add    --deployment-id ID --client-id CID --client-name "N" --region R
python scripts/manage_client.py list   --deployment-id ID --region R
python scripts/manage_client.py rotate --deployment-id ID --client-id CID --region R
python scripts/manage_client.py remove --deployment-id ID --client-id CID --region R

# ── Verify ────────────────────────────────────────────────────
aws cloudformation describe-stacks --stack-name TempMonitor-dev --query 'Stacks[0].Outputs' --output table --region R
aws logs tail /aws/lambda/temp-sensor-synthetic-gen-ID-ENV --since 5m --region R
aws logs tail /aws/lambda/temp-sensor-batch-processor-ID-ENV --since 5m --region R
aws logs tail /aws/lambda/TempMonitor-Dashboard-ID-ENV --since 5m --region R

# ── Manual Lambda Invoke ─────────────────────────────────────
echo '{"mode":"analytics"}' > /tmp/p.json
aws lambda invoke --function-name temp-sensor-scheduled-processor-ID-ENV \
  --payload file:///tmp/p.json --cli-binary-format raw-in-base64-out --region R /tmp/out.json

# ── Synthetic Toggle ─────────────────────────────────────────
make synth-on  STACK=TempMonitor-dev
make synth-off STACK=TempMonitor-dev

# ── CSV Import ────────────────────────────────────────────────
python scripts/import_csv_sensor.py \
  --csv data/temp-sensor-final.csv \
  --table temp-sensor-sensor-data-ID-ENV \
  --alerts-table temp-sensor-alerts-ID-ENV \
  --client-id CID --region R

# ── Teardown ─────────────────────────────────────────────────
aws s3 rm s3://temp-sensor-data-lake-ID-ENV --recursive --region R
aws cloudformation delete-stack --stack-name TempMonitor-dev --region R
```
