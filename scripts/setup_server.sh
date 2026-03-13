#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_server.sh — Deploy TempMonitor stack to a new server
#
# Steps:
#   1. Validate prerequisites (AWS CLI, SAM CLI, Python, Docker)
#   2. Build SAM application
#   3. Deploy CloudFormation stack (Lambda + API GW + DynamoDB + IAM)
#   4. Print dashboard URL and next steps
#
# Usage:
#   ./scripts/setup_server.sh \
#     --env prod \
#     --deployment-id abc1234567 \
#     --db-host cluster.rds.amazonaws.com \
#     --db-user app_reader \
#     --db-database sensor_prod \
#     --region us-east-1
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

usage() {
  echo "Usage: $0 --env ENV --deployment-id DID --db-host HOST --db-user USER --db-database DB [options]"
  echo ""
  echo "Required:"
  echo "  --env ENV               dev|staging|prod"
  echo "  --deployment-id DID     Unique 10-char server identifier"
  echo "  --db-host HOST          MySQL/Aurora endpoint"
  echo "  --db-user USER          DB username"
  echo "  --db-database DB        Database name"
  echo ""
  echo "Optional:"
  echo "  --region REGION         AWS region (default: us-east-1)"
  echo "  --stack-name NAME       CloudFormation stack name (default: TempSensor-ENV)"
  echo "  --s3-bucket BUCKET      SAM artifact bucket (default: auto-managed)"
  echo "  --data-source SRC       mysql|parquet|hybrid (default: mysql)"
  echo "  --parquet-bucket B      S3 bucket for Parquet data"
  echo "  --project-prefix PFX    Resource name prefix (default: TempSensor)"
  echo "  --dry-run               Print commands without executing"
  exit 1
}

# ── Parse args ───────────────────────────────────────────────────────────────
ENV="" DEPLOYMENT_ID="" DB_HOST="" DB_USER="" DB_DATABASE=""
REGION="us-east-1" STACK_NAME="" S3_BUCKET=""
DATA_SOURCE="mysql" PARQUET_BUCKET="" PROJECT_PREFIX="TempSensor" DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)            ENV="$2"; shift 2;;
    --deployment-id)  DEPLOYMENT_ID="$2"; shift 2;;
    --db-host)        DB_HOST="$2"; shift 2;;
    --db-user)        DB_USER="$2"; shift 2;;
    --db-database)    DB_DATABASE="$2"; shift 2;;
    --region)         REGION="$2"; shift 2;;
    --stack-name)     STACK_NAME="$2"; shift 2;;
    --s3-bucket)      S3_BUCKET="$2"; shift 2;;
    --data-source)    DATA_SOURCE="$2"; shift 2;;
    --parquet-bucket) PARQUET_BUCKET="$2"; shift 2;;
    --project-prefix) PROJECT_PREFIX="$2"; shift 2;;
    --dry-run)        DRY_RUN=true; shift;;
    *) echo -e "${RED}Unknown option: $1${NC}"; usage;;
  esac
done

[[ -z "$ENV" ]]           && echo -e "${RED}--env is required${NC}" && usage
[[ -z "$DEPLOYMENT_ID" ]] && echo -e "${RED}--deployment-id is required${NC}" && usage
[[ -z "$DB_HOST" ]]       && echo -e "${RED}--db-host is required${NC}" && usage
[[ -z "$DB_USER" ]]       && echo -e "${RED}--db-user is required${NC}" && usage
[[ -z "$DB_DATABASE" ]]   && echo -e "${RED}--db-database is required${NC}" && usage

STACK_NAME="${STACK_NAME:-${PROJECT_PREFIX}-Dashboard-${ENV}}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   TempSensor — Server Setup                   ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Environment:   $ENV"
echo "  Stack:         $STACK_NAME"
echo "  Deployment ID: $DEPLOYMENT_ID"
echo "  Region:        $REGION"
echo "  DB Host:       $DB_HOST"
echo ""

# ── Step 1: Prerequisites ───────────────────────────────────────────────────
echo -e "${YELLOW}[1/4] Checking prerequisites...${NC}"
MISSING=()
command -v aws >/dev/null 2>&1  || MISSING+=("aws-cli")
command -v sam >/dev/null 2>&1  || MISSING+=("sam-cli")
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo -e "${RED}  Missing: ${MISSING[*]}${NC}"
  echo "  Install them and retry."
  exit 1
fi
echo -e "  ${GREEN}✓ All prerequisites found${NC}"

if [[ -z "${MYSQL_PASSWORD:-}" ]]; then
  read -rsp "  Enter DB password for $DB_USER@$DB_HOST: " MYSQL_PASSWORD
  echo ""
  export MYSQL_PASSWORD
fi

# ── Step 2: SAM Build ───────────────────────────────────────────────────────
echo -e "${YELLOW}[2/4] Building SAM application...${NC}"
cd "$PROJECT_ROOT/infra"

if [[ "$DRY_RUN" == true ]]; then
  echo "  DRY RUN: sam build"
else
  sam build --template-file template.yaml 2>&1 | tail -3
  echo -e "  ${GREEN}✓ Build complete${NC}"
fi

# ── Step 3: SAM Deploy ──────────────────────────────────────────────────────
echo -e "${YELLOW}[3/4] Deploying stack: ${STACK_NAME}...${NC}"

DEPLOY_CMD="sam deploy \
  --stack-name ${STACK_NAME} \
  --region ${REGION} \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    Environment=${ENV} \
    DeploymentId=${DEPLOYMENT_ID} \
    ProjectPrefix=${PROJECT_PREFIX} \
    MysqlHost=${DB_HOST} \
    MysqlUser=${DB_USER} \
    MysqlPassword=\${MYSQL_PASSWORD} \
    MysqlDatabase=${DB_DATABASE} \
    DataSource=${DATA_SOURCE}"

[[ -n "$PARQUET_BUCKET" ]] && DEPLOY_CMD+=" ParquetBucket=${PARQUET_BUCKET}"
[[ -n "$S3_BUCKET" ]]      && DEPLOY_CMD+=" --s3-bucket ${S3_BUCKET}"

if [[ "$DRY_RUN" == true ]]; then
  echo "  DRY RUN: $DEPLOY_CMD"
else
  eval "$DEPLOY_CMD" 2>&1 | tail -10
  echo -e "  ${GREEN}✓ Stack deployed${NC}"
fi

# ── Step 4: Output ───────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/4] Fetching outputs...${NC}"

if [[ "$DRY_RUN" == false ]]; then
  DASHBOARD_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' \
    --output text 2>/dev/null || echo "<check CloudFormation console>")
  ALERTS_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`AlertsTableName`].OutputValue' \
    --output text 2>/dev/null || echo "")
else
  DASHBOARD_URL="<DRY-RUN>"
  ALERTS_TABLE="<DRY-RUN>"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Server setup complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Dashboard URL:  ${CYAN}${DASHBOARD_URL}${NC}"
echo -e "  Alerts Table:   ${ALERTS_TABLE}"
echo ""
echo "Next steps:"
echo "  1. Onboard clients:"
echo "     ./scripts/onboard_client.sh \\"
echo "       --client-id 14 \\"
echo "       --client-name 'County Jail West' \\"
echo "       --deployment-id ${DEPLOYMENT_ID} \\"
echo "       --region ${REGION}"
echo ""
echo "  2. Health check:"
echo "     curl -s ${DASHBOARD_URL}/healthz | python3 -m json.tool"
echo ""
echo "  3. Share access URL with officers (printed during onboard step)"
