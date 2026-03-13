# Deployment Guide — TempSensor Dashboard

Complete, step-by-step guide from a blank machine to a fully automated CI/CD pipeline deploying to AWS. Written so that even someone who has never used AWS, GitHub Actions, or SAM can follow along.

---

## Table of Contents

1. [What You Are Deploying](#what-you-are-deploying)
2. [Prerequisites — Install Everything](#prerequisites--install-everything)
3. [Local Development (No AWS Needed)](#local-development-no-aws-needed)
4. [Local Validation Checklist](#local-validation-checklist)
5. [Standalone Simulator (No DB Needed)](#standalone-simulator-no-db-needed)
6. [AWS Account Setup (One-Time)](#aws-account-setup-one-time)
7. [Create an IAM User for GitHub Actions (One-Time)](#create-an-iam-user-for-github-actions-one-time)
8. [GitHub Repository Setup](#github-repository-setup)
9. [Configure SAM Per-Environment Settings](#configure-sam-per-environment-settings)
10. [CI Pipeline — Automatic Testing](#ci-pipeline--automatic-testing)
11. [CD Pipeline — Automatic Deployment](#cd-pipeline--automatic-deployment)
12. [Full Pipeline Flow Diagram](#full-pipeline-flow-diagram)
13. [Client Onboarding (Multi-Tenancy)](#client-onboarding-multi-tenancy)
14. [New Server Setup (Automated)](#new-server-setup-automated)
15. [AWS Resources Created & Costs](#aws-resources-created--costs)
16. [Rollback](#rollback)
17. [Manual Deployment (Without CI/CD)](#manual-deployment-without-cicd)
18. [Troubleshooting](#troubleshooting)
19. [Glossary](#glossary)

---

## What You Are Deploying

A serverless dashboard that monitors temperature sensors in correctional facilities. The system consists of:

| Component | Technology | Purpose |
|---|---|---|
| Dashboard UI | Dash (Python) | Single-page web app officers use daily |
| Backend | Flask + Gunicorn | Serves data, handles authentication |
| Data Source | MySQL Aurora / S3 Parquet | Stores sensor readings |
| Alerts | DynamoDB | Persists alert history, notes |
| Hosting | AWS Lambda + API Gateway | Serverless — auto-scales, pay-per-use |
| CI/CD | GitHub Actions | Automatic testing and deployment |

**Environments:**

| Environment | Branch/Tag | Purpose | Auto-deploy? | Approval needed? |
|---|---|---|---|---|
| `dev` | `develop` branch | Development testing | Yes | No |
| `staging` | `main` branch | Pre-production validation | Yes | No |
| `prod` | `v*` tag (e.g., `v1.2.0`) | Production for officers | Yes | Yes (reviewer must approve) |

---

## Prerequisites — Install Everything

Before starting, you need these tools on your computer. Follow each step exactly.

### 1. Python 3.10 or Later

Python is the programming language the dashboard is written in.

**Check if already installed:**
```bash
python3 --version
```
If it prints `Python 3.10.x` or higher, skip to the next tool.

**Install on Ubuntu/Debian (Linux):**
```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip
```

**Install on macOS:**
```bash
brew install python@3.10
```

**Install on Windows:**
Download from https://www.python.org/downloads/ — during install, check "Add Python to PATH".

### 2. pip (Python Package Manager)

pip installs Python libraries. It usually comes with Python.

**Upgrade to latest version:**
```bash
python3 -m pip install --upgrade pip
```

### 3. Git

Git tracks code changes and is used to push code to GitHub.

**Check if installed:**
```bash
git --version
```

**Install on Ubuntu/Debian:**
```bash
sudo apt install -y git
```

**Install on macOS:**
```bash
brew install git
```

**Install on Windows:**
Download from https://git-scm.com/downloads

### 4. AWS CLI v2

The AWS CLI lets you talk to AWS from your terminal. Needed for deployments.

**Check if installed:**
```bash
aws --version
```
You need version 2.x. If you see version 1.x, uninstall it first.

**Install on Linux:**
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip
```

**Install on macOS:**
```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
rm AWSCLIV2.pkg
```

**Install on Windows:**
Download and run: https://awscli.amazonaws.com/AWSCLIV2.msi

**Configure AWS CLI (one-time):**
```bash
aws configure
```
It will ask for:
- **AWS Access Key ID**: Get from your AWS admin (IAM → Users → Security Credentials)
- **AWS Secret Access Key**: Same place as above
- **Default region**: `us-east-1` (or whatever region your DB is in)
- **Default output format**: `json`

> **Note**: If you are only doing local development (no AWS deployment), you do NOT need AWS CLI.

### 5. AWS SAM CLI

SAM CLI packages and deploys your code to AWS Lambda.

**Install:**
```bash
pip install aws-sam-cli
```

**Verify:**
```bash
sam --version
```
You should see something like `SAM CLI, version 1.x.x`.

### 6. GitHub Account

You need a GitHub account to store code and run the CI/CD pipelines.

Sign up at https://github.com if you do not have one.

### Summary Checklist

Run these commands to verify everything is ready:

```bash
python3 --version    # Should print 3.10+
pip --version        # Should print pip 2x.x+
git --version        # Should print git 2.x+
aws --version        # Should print aws-cli/2.x.x
sam --version        # Should print SAM CLI, version 1.x.x
```

If all five print a version number, you are ready to proceed.

---

## Local Development (No AWS Needed)

This section gets the dashboard running on your own machine using just a database connection. No AWS account required.

### Step 1: Get the Code

```bash
# Clone the repository (replace <repo-url> with your actual GitHub URL)
git clone <repo-url>

# Move into the project folder
cd TemperatureSensor
```

Your folder structure now looks like:
```
TemperatureSensor/
├── dashboard/          ← The actual dashboard app
│   ├── app/            ← Python source code
│   ├── tests/          ← Unit tests
│   └── requirements.txt
├── infra/              ← AWS infrastructure templates
├── scripts/            ← Automation scripts
├── clients.yaml        ← Client registry
├── sensor_simulator.py ← Test simulator (no DB needed)
└── .github/workflows/  ← CI/CD pipeline definitions
```

### Step 2: Install Python Dependencies

```bash
# Install all runtime + development dependencies
pip install -r dashboard/requirements.txt -r requirements-dev.txt
```

This installs:
- **dash, flask, plotly** — Dashboard UI framework
- **pymysql** — MySQL database connector
- **boto3** — AWS SDK (for DynamoDB, S3, Secrets Manager)
- **gunicorn** — Production web server
- **python-dotenv** — Reads `.env` files
- **pytest, ruff, moto** — Testing and linting tools

### Step 3: Configure Database Connection

Create a file called `.env` in the project root (`TemperatureSensor/.env`):

```bash
# Open your text editor and create this file
nano .env
```

Paste the following, replacing the placeholder values with your real database credentials:

```env
# Database connection
MYSQL_HOST=your-aurora-host.cluster-ro.rds.amazonaws.com
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database_name
MYSQL_PORT=3306

# Data source: mysql (default), parquet, or hybrid
DATA_SOURCE=mysql

# Client identity (must match customer_key in DB, or "default" for no filter)
CLIENT_ID=14
CLIENT_NAME=County Jail West
```

**What each line means:**

| Variable | What it is | Example |
|---|---|---|
| `MYSQL_HOST` | The hostname of your MySQL/Aurora database | `demo-db.cluster-ro.rds.amazonaws.com` |
| `MYSQL_USER` | Database username | `Demo_aurora` |
| `MYSQL_PASSWORD` | Database password | `N0t32023#d3m0` |
| `MYSQL_DATABASE` | Database name | `Demo_aurora` |
| `MYSQL_PORT` | Database port (usually 3306) | `3306` |
| `DATA_SOURCE` | Where to read data from | `mysql` |
| `CLIENT_ID` | Filters data for this client (matches `customer_key` column in DB) | `14` |
| `CLIENT_NAME` | Display name shown in the dashboard navbar | `County Jail West` |

> **Security**: The `.env` file is listed in `.gitignore` so it will NEVER be pushed to GitHub. Never share this file.

### Step 4: Run the Dashboard

You have three options:

**Option A: Gunicorn (Recommended — matches production behavior)**
```bash
cd dashboard
gunicorn app.main:server -b 0.0.0.0:8051 --threads 4
```

**Option B: Flask dev server (auto-reloads when you change code)**
```bash
cd dashboard
python -m app.main
```

**Option C: Simulator (no database needed at all — see next section)**
```bash
python sensor_simulator.py
```

After running Option A or B, open your browser and go to:
```
http://localhost:8051
```

You should see the TempSensor dashboard with your sensors.

### Step 5: Run Tests, Lint, and Validate

```bash
cd dashboard

# Run all 161 unit tests (takes ~3 seconds)
python -m pytest tests/ -v

# Run the linter (should show 0 errors)
python -m ruff check app/ tests/

# Validate the SAM infrastructure template (catches config errors before deploy)
pip install aws-sam-cli    # one-time install if you haven't already
sam validate --template-file ../infra/template.yaml --lint
```

**All three must pass** before you commit any code changes. These are the same checks the CI pipeline runs automatically on every Pull Request.

### Data Source Switching

Switch the data source by changing `DATA_SOURCE` in your `.env`:

```env
DATA_SOURCE=mysql      # Only MySQL (default, simplest)
DATA_SOURCE=parquet    # Only S3 Parquet (fastest for large datasets)
DATA_SOURCE=hybrid     # Parquet first → MySQL fallback (best of both)
```

### Local DynamoDB (Automatic)

When running locally (no `AWS_MODE=true`), the system uses `moto` to simulate DynamoDB entirely in memory. No extra setup, no DynamoDB tables to create. Alert creation, resolution, notes — everything works identically to production.

---

## Local Validation Checklist

After starting the dashboard, verify each feature works:

| # | Feature | How to Validate | Expected Result |
|---|---|---|---|
| 1 | **Dashboard loads** | Open http://localhost:8051 | Navbar with clock and LIVE indicator |
| 2 | **Sensor tiles** | Look below the filter bar | Grid of sensor cards showing temp, battery, signal |
| 3 | **Facility filter** | Click "All Facilities" dropdown | Dropdown with location names from DB |
| 4 | **Sensor filter** | Select a facility, check sensor dropdown | Only sensors from that facility |
| 5 | **Sensor selection** | Click a sensor tile | KPIs appear, chart loads |
| 6 | **Chart — LIVE** | With sensor selected, click LIVE | Line chart with data + forecast |
| 7 | **Chart — History** | Click 6h or 12h | Historical data, no forecast |
| 8 | **Date range** | Pick dates in calendar | Chart for selected range |
| 9 | **Alerts** | Select a sensor with alerts (red tile) | Alert cards below filter bar |
| 10 | **Note action** | Click "Note" on alert | Green checkmark, alert disappears |
| 11 | **Remove action** | Click "Remove" on alert | Alert disappears, cooldown starts |
| 12 | **Status filters** | Click Critical / Warning / Normal | Only matching sensors shown |
| 13 | **Reset** | Click "Reset" button | All filters cleared |
| 14 | **Compliance** | Scroll to Live Compliance section | Gauge + stats + 7-day trend |
| 15 | **Healthz** | `curl http://localhost:8051/healthz` | JSON with mysql and provider status |

---

## Standalone Simulator (No DB Needed)

If you do not have database credentials, you can test the full dashboard with generated data:

```bash
# From the TemperatureSensor root directory
python sensor_simulator.py --port 8051 --interval 5
```

This creates:
- **10 live sensors** with different profiles (stable, drift, hot, cold, rapid)
- **3 offline sensors** matching real MAC addresses
- **10 days of history** at variable resolution
- **New readings every 5 seconds**
- **All alerts, forecasts, and compliance** computed live

Open http://localhost:8051 — you will see a fully working dashboard.

The simulator is a single file, completely independent from production code, and writes nothing to any database.

---

## AWS Account Setup (One-Time)

These steps configure your AWS account to accept deployments. You only do this once.

### Step 1: Log into AWS Console

1. Open https://console.aws.amazon.com
2. Sign in with your AWS account (you need admin or sufficient IAM permissions)
3. In the top-right corner, make sure you are in the correct region (e.g., `US East (N. Virginia)` = `us-east-1`)

### Step 2: Create an S3 Bucket for SAM Artifacts

SAM needs a bucket to upload your code before deploying it to Lambda. You can skip this if you use `resolve_s3 = true` in samconfig (which auto-creates one).

If you prefer a named bucket:

```bash
aws s3 mb s3://tempsensor-deploy-artifacts-YOUR_ACCOUNT_ID --region us-east-1
```

Replace `YOUR_ACCOUNT_ID` with your 12-digit AWS account number.

### Step 3: Generate a Deployment ID

Each server/deployment gets a unique 10-character ID. This ID appears in all AWS resource names.

```bash
python3 -c "import uuid; print(uuid.uuid4().hex[:10])"
```

Example output: `a1b2c3d4e5`

**Write this ID down.** You will use it throughout the setup.

---

## Create an IAM User for GitHub Actions (One-Time)

GitHub Actions needs AWS credentials to deploy your code. The simplest approach is to create a dedicated IAM user with access keys and store them as GitHub Secrets.

### Step 1: Create the IAM User

**Using AWS Console (easiest):**

1. Open https://console.aws.amazon.com
2. Go to **IAM** (search "IAM" in the top search bar)
3. In the left sidebar, click **Users**
4. Click **Create user**
5. User name: `github-actions-deployer`
6. Click **Next**
7. Select **Attach policies directly**
8. Search and check these two policies:
   - `PowerUserAccess` (allows creating Lambda, API Gateway, DynamoDB, S3, CloudWatch, etc.)
   - `IAMFullAccess` (needed because SAM creates IAM roles for Lambda)
9. Click **Next** → **Create user**

> **For production hardening later**: Replace these broad policies with a custom policy scoped to only the specific resources this stack creates. For now, these work.

**Using AWS CLI:**

```bash
# Create the user
aws iam create-user --user-name github-actions-deployer

# Attach permissions
aws iam attach-user-policy \
  --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/PowerUserAccess

aws iam attach-user-policy \
  --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess
```

### Step 2: Create Access Keys

**Using AWS Console:**

1. Click on the user `github-actions-deployer`
2. Go to the **Security credentials** tab
3. Scroll down to **Access keys** → click **Create access key**
4. Select **Third-party service** → check the confirmation → click **Next**
5. Description: `GitHub Actions CI/CD`
6. Click **Create access key**
7. **IMPORTANT**: You will see two values:
   - **Access key ID** — looks like `AKIAIOSFODNN7EXAMPLE`
   - **Secret access key** — looks like `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`
8. **Copy both values NOW** — the secret access key is only shown once. If you lose it, you must create new keys.

**Using AWS CLI:**

```bash
aws iam create-access-key --user-name github-actions-deployer
```

This prints JSON with `AccessKeyId` and `SecretAccessKey`. Save both.

### Step 3: Verify the Keys Work

Test from your terminal:

```bash
AWS_ACCESS_KEY_ID=AKIA...YOUR_KEY \
AWS_SECRET_ACCESS_KEY=wJal...YOUR_SECRET \
aws sts get-caller-identity
```

You should see output like:

```json
{
    "UserId": "AIDAEXAMPLE",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/github-actions-deployer"
}
```

If this works, your keys are valid. You will paste them into GitHub in the next section.

> **Security tip**: Rotate these keys every 90 days. Set a calendar reminder. To rotate: create new keys → update GitHub Secrets → delete old keys.

---

## GitHub Repository Setup

### Step 1: Push Your Code to GitHub

If the repository is not on GitHub yet:

```bash
cd TemperatureSensor

# Initialize git (skip if already a git repo)
git init

# Add all files
git add .

# Create the first commit
git commit -m "Initial commit — TempSensor dashboard"

# Create the repository on GitHub (requires GitHub CLI 'gh')
gh repo create YOUR_ORG/TemperatureSensor --private --push

# Or, if you created the repo manually on github.com:
git remote add origin https://github.com/YOUR_ORG/TemperatureSensor.git
git push -u origin main
```

### Step 2: Create Branches

The CI/CD pipeline uses two branches:

```bash
# Create the develop branch (for dev environment)
git checkout -b develop
git push -u origin develop

# Go back to main
git checkout main
```

- `develop` — developers push features here; triggers deploy to **dev**
- `main` — stable code; triggers deploy to **staging**
- `v*` tags (e.g., `v1.0.0`) — triggers deploy to **prod** (with approval)

### Step 3: Create GitHub Environments

Environments let you control which secrets and approvals are needed per deployment.

1. Go to your repository on GitHub
2. Click **Settings** (tab at the top)
3. In the left sidebar, click **Environments**
4. Click **New environment**

Create these three environments:

**Environment: `dev`**
- Name: `dev`
- No protection rules needed
- Click **Configure environment**

**Environment: `staging`**
- Name: `staging`
- No protection rules needed
- Click **Configure environment**

**Environment: `prod`**
- Name: `prod`
- Check **Required reviewers** → add yourself or your team lead
- This means production deploys will WAIT for a human to click "Approve" before running
- Click **Configure environment**

### Step 4: Add Secrets to Each Environment

For each environment (`dev`, `staging`, `prod`), add these secrets:

1. Go to **Settings** → **Environments** → click the environment name
2. Under **Environment secrets**, click **Add secret**

| Secret Name | Value | Where to Get It |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | `AKIAIOSFODNN7EXAMPLE` | From IAM User Step 2 above |
| `AWS_SECRET_ACCESS_KEY` | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` | From IAM User Step 2 above |
| `MYSQL_PASSWORD` | Your database password for that environment | Your database admin |
| `COOKIE_SECRET` | A random string for signing cookies (optional — auto-generated if empty) | `python3 -c "import secrets; print(secrets.token_hex(32))"` |

> **Tip**: If all environments use the **same** AWS account, you can add `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as **repository-level** secrets (Settings → Secrets and variables → Actions → New repository secret) instead of repeating them per environment. Only `MYSQL_PASSWORD` typically differs per environment.

### Step 5: Add Environment Variables

For each environment, you can also add **variables** (non-secret config):

1. Under the environment settings, click **Add variable**

| Variable Name | Value | Description |
|---|---|---|
| `AWS_REGION` | `us-east-1` | AWS region for this environment |
| `PROJECT_PREFIX` | `TempSensor` | Prefix for all AWS resource names |
| `STACK_NAME` | `TempSensor-Dashboard-dev` | CloudFormation stack name |

---

## Configure SAM Per-Environment Settings

The file `infra/samconfig.toml` contains deployment parameters for each environment. The CD pipeline reads this file to know HOW to deploy to each environment.

### Open the File

```bash
nano infra/samconfig.toml
```

### What to Change

For each environment section (`[dev.deploy.parameters]`, `[staging.deploy.parameters]`, `[prod.deploy.parameters]`), update:

1. **`DeploymentId`** — Replace `REPLACE_ME1`, `REPLACE_ME2`, `REPLACE_ME3` with actual deployment IDs (generate with `python3 -c "import uuid; print(uuid.uuid4().hex[:10])"`)
2. **`MysqlHost`** — Your Aurora/RDS endpoint for that environment
3. **`MysqlUser`** — Database username
4. **`MysqlDatabase`** — Database name
5. **`region`** — AWS region

**Example (filled in):**

```toml
[dev.deploy.parameters]
stack_name         = "TempSensor-Dashboard-dev"
resolve_s3         = true
capabilities       = "CAPABILITY_IAM"
confirm_changeset  = false
region             = "us-east-1"
parameter_overrides = """
  Environment=dev
  DeploymentId=f8c3a91b02
  ProjectPrefix=TempSensor
  DataSource=mysql
  MysqlHost=dev-aurora.cluster-ro.us-east-1.rds.amazonaws.com
  MysqlPort=3306
  MysqlUser=app_reader
  MysqlDatabase=sensor_dev
"""
```

> **MysqlPassword is NOT in this file.** It is passed securely from GitHub Secrets at deploy time. Never put passwords in files committed to git.

### Commit the Config

```bash
git add infra/samconfig.toml
git commit -m "Configure SAM deploy parameters for dev/staging/prod"
git push
```

---

## CI Pipeline — Automatic Testing

**File:** `.github/workflows/ci.yml`

This workflow runs automatically on every Pull Request to `main` or `develop`. It also runs on pushes to `develop`.

### What It Does (Step by Step)

```
Developer creates a Pull Request
         │
         ▼
1. GitHub spins up a fresh Ubuntu machine
2. Checks out your code
3. Installs Python 3.10
4. Installs all pip dependencies
5. Runs ruff (linter) — catches style errors
6. Runs pytest (161 tests) — catches bugs
7. Runs sam validate — catches infrastructure template errors
         │
         ▼
If ALL pass → Green checkmark ✓ on the PR
If ANY fail → Red X on the PR (merge is blocked)
```

### How to Use It

1. Create a feature branch:
   ```bash
   git checkout develop
   git pull
   git checkout -b feature/my-change
   ```

2. Make your changes, commit, and push:
   ```bash
   git add .
   git commit -m "Add feature X"
   git push -u origin feature/my-change
   ```

3. Open a Pull Request on GitHub:
   - Go to your repository on GitHub
   - Click **"Compare & pull request"** (the yellow banner at the top)
   - Base branch: `develop`
   - Click **"Create pull request"**

4. Wait for CI to finish:
   - Scroll down on the PR page
   - You will see "CI — Lint, Test, Validate" running
   - If it passes → green checkmark → safe to merge
   - If it fails → click "Details" to see which step failed and why

5. Fix any failures, push again, CI re-runs automatically.

### Viewing CI Results

- On the PR page, click the **Checks** tab
- Or go to **Actions** tab → click the workflow run
- Each step (Lint, Test, Validate) shows its output
- Failed steps are highlighted in red with the error message

---

## CD Pipeline — Automatic Deployment

**File:** `.github/workflows/cd.yml`

This workflow deploys your code to AWS after it is merged.

### Automatic Triggers

| Trigger | Target Environment | Approval Needed? |
|---|---|---|
| Push to `develop` branch | `dev` | No |
| Push to `main` branch | `staging` | No |
| Create a `v*` tag (e.g., `v1.2.0`) | `prod` | **Yes** (reviewer must approve) |

### Manual Trigger

You can also trigger a deployment manually:

1. Go to **Actions** tab on GitHub
2. Click **"CD — Deploy"** in the left sidebar
3. Click **"Run workflow"**
4. Select the target environment from the dropdown
5. Click **"Run workflow"** (green button)

### What It Does (Step by Step)

```
1. Determines target environment (dev/staging/prod)
2. Runs CI safety gate:
   a. ruff check      — lint (code style)
   b. pytest           — 161 unit tests
3. Authenticates to AWS using access keys (from GitHub Secrets)
4. Installs SAM CLI
5. Runs "sam build"   — packages the dashboard code into a Lambda ZIP
6. Runs "sam deploy"  — creates/updates AWS resources:
   - Lambda function  (the dashboard app)
   - API Gateway      (the public URL)
   - DynamoDB table   (alert persistence)
   - CloudWatch alarm (error monitoring)
7. Prints the deployed dashboard URL in the workflow summary
```

> **Note:** `sam validate` runs in the CI pipeline (on PRs). The CD pipeline trusts that code merged to `develop`/`main` already passed CI, so it skips re-validation and goes straight to build + deploy.

### Deploying to Production

Production deploys require manual approval:

1. Create a version tag:
   ```bash
   git checkout main
   git pull
   git tag v1.0.0
   git push origin v1.0.0
   ```

2. Go to **Actions** tab — you will see the CD workflow started

3. It will pause at the deploy step and show: **"Waiting for review"**

4. Click **"Review deployments"** → check **prod** → click **"Approve and deploy"**

5. The deployment proceeds and the URL is printed in the workflow summary

### Viewing Deployment Results

After deployment completes:

1. Go to **Actions** → click the CD workflow run
2. Open the **"Deploy to [env]"** job
3. Open the **"Print deployed URL"** step
4. The dashboard URL is printed there

Or from your terminal:

```bash
aws cloudformation describe-stacks \
  --stack-name TempSensor-Dashboard-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' \
  --output text
```

---

## Full Pipeline Flow Diagram

```
Developer writes code
         │
         ▼
  ┌─────────────────┐
  │ git push to      │
  │ feature branch   │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ Open Pull Request│ ──────────► CI runs automatically
  │ to develop       │             ┌──────────────────────┐
  └────────┬────────┘             │ 1. ruff (lint)       │
           │                       │ 2. pytest (161 tests)│
           │                       │ 3. sam validate      │
           │                       └──────────┬───────────┘
           │                                  │
           │                       Pass? ──── Yes ──── ✓ Green check
           │                        │
           │                        No ──── ✗ Red X (fix and push again)
           │
           ▼
  ┌─────────────────┐
  │ Merge PR to      │ ──────────► CD deploys to DEV
  │ develop          │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ Open PR from     │ ──────────► CI runs again
  │ develop → main   │
  └────────┬────────┘
           │ Merge
           ▼
  ┌─────────────────┐
  │ Push to main     │ ──────────► CD deploys to STAGING
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ Create tag       │ ──────────► CD deploys to PROD
  │ v1.0.0           │             (waits for approval)
  └─────────────────┘
```

### Day-to-Day Workflow for a Developer

1. **Start work**: `git checkout develop && git pull && git checkout -b feature/xyz`
2. **Code & test locally**: make changes, run `pytest`, run `ruff check`
3. **Push**: `git push -u origin feature/xyz`
4. **Open PR**: on GitHub, PR from `feature/xyz` → `develop`
5. **CI runs**: wait for green checkmark
6. **Merge**: click "Merge pull request" → code deploys to **dev** automatically
7. **Promote to staging**: PR from `develop` → `main`, merge → deploys to **staging**
8. **Release to prod**: `git tag v1.0.0 && git push origin v1.0.0` → reviewer approves → deploys to **prod**

---

## Client Onboarding (Multi-Tenancy)

Each "client" is a facility or group of facilities. Clients share the same deployed server but see only their own data.

### Client Registry (`clients.yaml`)

The file `clients.yaml` in the project root defines all clients:

```yaml
defaults:
  data_source: mysql
  isolation: shared

clients:
  "14":
    name: "County Jail West"
    isolation: shared
    db:
      host: ${MYSQL_HOST}
      user: ${MYSQL_USER}
      password: ${MYSQL_PASSWORD}
      database: ${MYSQL_DATABASE}
    parquet:
      bucket: ""
      prefix: "sensor-data/client-14/"
    alerts_table: ""

  "27":
    name: "State Prison East"
    isolation: isolated
    db:
      host: "cluster-east.rds.amazonaws.com"
      user: "app_user"
      password: ${CLIENT_27_DB_PASSWORD}
      database: "state_east_db"
    alerts_table: "TempSensor-Alerts-27"
```

**Isolation modes:**
- `shared` — Clients share one database. Queries filter by `client_id` automatically.
- `isolated` — Client has its own dedicated database. No filter needed.

### Automated Onboarding (One Command)

```bash
./scripts/onboard_client.sh \
  --client-id 14 \
  --client-name "County Jail West" \
  --deployment-id a1b2c3d4e5 \
  --db-host cluster.rds.amazonaws.com \
  --db-user app_user \
  --db-password-env CLIENT_14_DB_PASSWORD \
  --db-database county_west \
  --region us-east-1
```

This script:
1. Creates a Secrets Manager access token for the client
2. Creates a DynamoDB alerts table (if specified)
3. Appends the client configuration to `clients.yaml`
4. Prints the URL to share with officers

Add `--dry-run` to preview without executing.

### Manual Client Management

```bash
# Add a client
python scripts/manage_client.py add \
  --deployment-id a1b2c3d4e5 --client-id 14 --client-name "County Jail West"

# List all clients
python scripts/manage_client.py list --deployment-id a1b2c3d4e5

# Rotate access token
python scripts/manage_client.py rotate --deployment-id a1b2c3d4e5 --client-id 14

# Remove a client
python scripts/manage_client.py remove --deployment-id a1b2c3d4e5 --client-id 14
```

### How Officer Authentication Works

1. Admin runs onboarding → creates a Secrets Manager entry with a unique token
2. Officer visits `/connect/{token}` → app sets a signed HttpOnly cookie (30-day expiry)
3. All subsequent requests use the cookie — no passwords to remember
4. Token rotation invalidates old URLs within 5 minutes (cache TTL)

---

## New Server Setup (Automated)

For deploying a completely new server (e.g., a new production environment for a new region):

```bash
./scripts/setup_server.sh \
  --env prod \
  --deployment-id a1b2c3d4e5 \
  --db-host cluster.rds.amazonaws.com \
  --db-user app_user \
  --db-database county_db \
  --region us-east-1
```

This script:
1. Validates prerequisites (AWS CLI, SAM CLI, Python)
2. Prompts for the database password securely
3. Runs `sam build` (packages the code)
4. Runs `sam deploy` (creates all AWS resources)
5. Prints the dashboard URL and next steps

After server setup, run `onboard_client.sh` for each client on that server.

---

## AWS Resources Created & Costs

When you deploy, SAM creates these AWS resources:

| Resource | Name Pattern | Purpose | Estimated Cost |
|---|---|---|---|
| **Lambda** | `TempSensor-Dashboard-{id}-{env}` | Hosts the dashboard (512MB, 30s timeout) | ~$2–5/month |
| **HTTP API Gateway** | auto-generated | Routes HTTP traffic to Lambda | ~$3–5/month |
| **DynamoDB Table** | `TempSensor-Alerts-{id}-{env}` | Alert persistence (pay-per-request) | ~$1–3/month |
| **CloudWatch Alarm** | `TempSensor-Dashboard-Errors-{id}-{env}` | Alerts on Lambda errors | < $1/month |
| **Secrets Manager** | `TempSensor/{id}/{client_id}` (per client) | Access tokens for officers | ~$0.40/secret/month |

**DynamoDB Table Schema:**
- Partition key: `PK` (e.g., `ALERT#device_id#alert_type`)
- Sort key: `SK` (ISO timestamp)
- GSI: `ClientActiveAlerts` — `client_id` (partition) + `state_triggered` (sort)
- TTL: 90 days from creation

**Estimated total cost: ~$10–15/month per server** (assuming 20-30 users, moderate usage).

---

## Rollback

### Via GitHub Actions (Easiest)

1. Go to **Actions** → **CD — Deploy**
2. Click **"Run workflow"**
3. Select the target environment
4. In the **branch/tag** selector, pick the previous version (e.g., `v1.0.0` instead of `v1.1.0`)
5. Click **"Run workflow"**

### Via Command Line

```bash
# Check out the previous version
git checkout v1.0.0

# Build and deploy
sam build --template-file infra/template.yaml
sam deploy \
  --config-env prod \
  --config-file infra/samconfig.toml \
  --parameter-overrides "MysqlPassword=$MYSQL_PASSWORD"
```

### Emergency: Revert Lambda to Previous Version

If you need to roll back in seconds without rebuilding:

```bash
# List available Lambda versions
aws lambda list-versions-by-function \
  --function-name TempSensor-Dashboard-a1b2c3d4e5-prod

# Point to a previous version (replace 42 with the version number)
aws lambda update-alias \
  --function-name TempSensor-Dashboard-a1b2c3d4e5-prod \
  --name live \
  --function-version 42
```

---

## Manual Deployment (Without CI/CD)

If you want to deploy manually from your terminal without using GitHub Actions:

### Step 1: Run Tests and Lint (Same as CI)

Before deploying anything, make sure the code is clean — exactly the same checks the CI pipeline runs:

```bash
cd TemperatureSensor/dashboard

# 1a. Lint — checks code style (0 errors expected)
python -m ruff check app/ tests/

# 1b. Unit tests — catches bugs (158+ passed expected)
python -m pytest tests/ -v --tb=short

# 1c. Validate SAM template — catches infrastructure config errors
sam validate --template-file ../infra/template.yaml --lint
```

**Do NOT proceed to Step 2 unless all three pass.** If any fail, fix the issues first.

### Step 2: Build

This packages the dashboard code into a Lambda-ready ZIP:

```bash
cd TemperatureSensor    # back to project root
sam build --template-file infra/template.yaml
```

You should see `Build Succeeded` at the end. The built artifacts go into `.aws-sam/build/`.

### Step 3: Deploy

```bash
sam deploy \
  --config-env dev \
  --config-file infra/samconfig.toml \
  --parameter-overrides "MysqlPassword=YOUR_DB_PASSWORD"
```

Replace `dev` with `staging` or `prod` as needed. Replace `YOUR_DB_PASSWORD` with the actual database password for that environment.

**What happens during deploy:**
1. SAM uploads the Lambda package to S3
2. Creates/updates a CloudFormation stack
3. Creates or updates: Lambda function, API Gateway, DynamoDB table, CloudWatch alarm
4. Prints the outputs (dashboard URL, table name, etc.)

### Step 4: Verify the Deployment

```bash
# Get the dashboard URL from stack outputs
aws cloudformation describe-stacks \
  --stack-name TempSensor-Dashboard-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' \
  --output text

# Health check — should return JSON with "status": "ok"
curl https://XXXX.execute-api.us-east-1.amazonaws.com/healthz

# Check Lambda logs for any startup errors
sam logs --stack-name TempSensor-Dashboard-dev --tail
```

### Quick Reference: Full Manual Deploy (Copy-Paste)

All steps combined for easy copy-paste:

```bash
cd TemperatureSensor

# Pre-deploy checks (same as CI)
cd dashboard
python -m ruff check app/ tests/
python -m pytest tests/ -v --tb=short
sam validate --template-file ../infra/template.yaml --lint
cd ..

# Build + Deploy
sam build --template-file infra/template.yaml
sam deploy \
  --config-env dev \
  --config-file infra/samconfig.toml \
  --parameter-overrides "MysqlPassword=$MYSQL_PASSWORD"

# Verify
aws cloudformation describe-stacks \
  --stack-name TempSensor-Dashboard-dev \
  --query 'Stacks[0].Outputs' \
  --output table
```

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---|---|---|
| **Dashboard slow (3-5s clicks)** | Single-threaded server | Use `gunicorn --threads 4` |
| **Blank chart on long date range** | Too many data points | Downsampling is automatic (2000 pts); check MySQL query limits |
| **Location dropdown empty** | `name` column null/empty in DB | Ensure `name` is populated in `dg_gateway_data` |
| **No sensors after login** | `client_id` mismatch | Verify `CLIENT_ID` matches `customer_key` values in DB |
| **Compliance shows 0%** | All sensors offline | Expected — shows "Last Known" label |
| **`moto` import error** | Wrong version | `pip install 'moto>=5.0'` |
| **MySQL connection timeout** | Aurora idle pruning | Auto-retry built in; restart app if persistent |
| **Parquet not found (hybrid)** | S3 path wrong | Falls back to MySQL; check `PARQUET_BUCKET` |
| **Date picker hidden** | CSS missing | Ensure `app/assets/style.css` exists |
| **Lambda cold start slow** | First request after idle | Normal (~3-5s); subsequent requests fast |
| **Alerts not appearing** | DynamoDB table missing | Check `ALERTS_TABLE`; locally, moto auto-creates it |
| **Cookie expired** | 30-day timeout | Officer revisits `/connect/{token}` |
| **CI fails on "sam validate"** | SAM CLI not installed | The CI workflow installs it; check pip step |
| **CD "Waiting for review"** | Prod needs approval | Go to Actions → click "Review deployments" → Approve |
| **CD "AccessDenied" error** | AWS keys invalid or missing permissions | Verify `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in GitHub Secrets; check IAM user has `PowerUserAccess` + `IAMFullAccess` |

### Viewing Logs

**Local:**
```bash
# Logs appear in the terminal where you ran gunicorn/flask
```

**AWS Lambda (CloudWatch):**
```bash
# Tail live logs
sam logs --stack-name TempSensor-Dashboard-dev --tail

# Or via AWS CLI
aws logs tail /aws/lambda/TempSensor-Dashboard-a1b2c3d4e5-dev --follow
```

**GitHub Actions:**
1. Go to **Actions** tab
2. Click the failed workflow run
3. Click the failed job
4. Click the failed step to see the full output

---

## Glossary

| Term | What It Means |
|---|---|
| **AWS** | Amazon Web Services — cloud platform that hosts everything |
| **Lambda** | AWS service that runs your code without managing servers |
| **API Gateway** | AWS service that gives your Lambda a public URL |
| **DynamoDB** | AWS NoSQL database used for alert storage |
| **S3** | AWS file storage (for Parquet data files) |
| **SAM** | Serverless Application Model — tool to define and deploy AWS resources |
| **CloudFormation** | AWS service that creates resources from a template (SAM uses this under the hood) |
| **IAM User** | An AWS identity with access keys that GitHub Actions uses to deploy |
| **Access Keys** | A pair (Key ID + Secret) that authenticates API calls to AWS |
| **CI** | Continuous Integration — automatically tests code on every change |
| **CD** | Continuous Deployment — automatically deploys code to AWS after tests pass |
| **PR** | Pull Request — a request to merge code changes (also where CI runs) |
| **Environment** | A deployment target (dev, staging, prod) with its own config and secrets |
| **Deployment ID** | 10-character unique identifier for a server deployment |
| **client_id** | Identifier for a facility/client; maps to `customer_key` column in the database |
| **Gunicorn** | Production-grade Python web server |
| **ruff** | Fast Python linter that checks code style |
| **pytest** | Python testing framework that runs all unit tests |
| **moto** | Library that simulates AWS services locally (DynamoDB, S3, etc.) |
| **Parquet** | Columnar file format for large datasets; stored in S3 |
