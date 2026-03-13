#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# onboard_client.sh — Automate new client onboarding
#
# Creates:  1) Secrets Manager access token
#           2) DynamoDB alerts table (optional, shared table by default)
#           3) Appends client block to clients.yaml
#           4) Prints access URL
#
# Usage:
#   ./scripts/onboard_client.sh \
#     --client-id 14 \
#     --client-name "County Jail West" \
#     --deployment-id abc1234567 \
#     --db-host cluster.rds.amazonaws.com \
#     --db-user app_user \
#     --db-password-env CLIENT_14_DB_PASSWORD \
#     --db-database county_west \
#     --region us-east-1 \
#     [--isolation shared|isolated] \
#     [--alerts-table TempMonitor-Alerts-14] \
#     [--dashboard-url https://xxx.execute-api.us-east-1.amazonaws.com]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

usage() {
  echo "Usage: $0 --client-id ID --client-name NAME --deployment-id DID [options]"
  echo ""
  echo "Required:"
  echo "  --client-id ID          Unique client identifier (matches customer_key in DB)"
  echo "  --client-name NAME      Human-readable name"
  echo "  --deployment-id DID     10-char deployment ID for this server"
  echo ""
  echo "Database (required for new registry entry):"
  echo "  --db-host HOST"
  echo "  --db-user USER"
  echo "  --db-password-env VAR   Env var name holding the DB password"
  echo "  --db-database DB"
  echo ""
  echo "Optional:"
  echo "  --region REGION         AWS region (default: us-east-1)"
  echo "  --isolation MODE        shared|isolated (default: shared)"
  echo "  --alerts-table NAME     DynamoDB table name (auto-generated if empty)"
  echo "  --dashboard-url URL     Dashboard base URL (auto-detected if omitted)"
  echo "  --skip-secrets          Skip Secrets Manager step"
  echo "  --skip-registry         Skip clients.yaml update"
  echo "  --dry-run               Print what would happen, don't execute"
  exit 1
}

# ── Parse args ───────────────────────────────────────────────────────────────
CLIENT_ID="" CLIENT_NAME="" DEPLOYMENT_ID="" REGION="us-east-1"
DB_HOST="" DB_USER="" DB_PASSWORD_ENV="" DB_DATABASE="" DB_PORT="3306"
ISOLATION="shared" ALERTS_TABLE="" DASHBOARD_URL=""
PROJECT_PREFIX="${PROJECT_PREFIX:-TempSensor}"
SKIP_SECRETS=false SKIP_REGISTRY=false DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-id)       CLIENT_ID="$2"; shift 2;;
    --client-name)     CLIENT_NAME="$2"; shift 2;;
    --deployment-id)   DEPLOYMENT_ID="$2"; shift 2;;
    --region)          REGION="$2"; shift 2;;
    --db-host)         DB_HOST="$2"; shift 2;;
    --db-user)         DB_USER="$2"; shift 2;;
    --db-password-env) DB_PASSWORD_ENV="$2"; shift 2;;
    --db-database)     DB_DATABASE="$2"; shift 2;;
    --db-port)         DB_PORT="$2"; shift 2;;
    --isolation)       ISOLATION="$2"; shift 2;;
    --alerts-table)    ALERTS_TABLE="$2"; shift 2;;
    --dashboard-url)   DASHBOARD_URL="$2"; shift 2;;
    --skip-secrets)    SKIP_SECRETS=true; shift;;
    --skip-registry)   SKIP_REGISTRY=true; shift;;
    --project-prefix)  PROJECT_PREFIX="$2"; shift 2;;
    --dry-run)         DRY_RUN=true; shift;;
    *) echo -e "${RED}Unknown option: $1${NC}"; usage;;
  esac
done

[[ -z "$CLIENT_ID" ]]      && echo -e "${RED}--client-id is required${NC}" && usage
[[ -z "$CLIENT_NAME" ]]    && echo -e "${RED}--client-name is required${NC}" && usage
[[ -z "$DEPLOYMENT_ID" ]]  && echo -e "${RED}--deployment-id is required${NC}" && usage

echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   TempMonitor — Client Onboarding             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Client ID:     $CLIENT_ID"
echo "  Client Name:   $CLIENT_NAME"
echo "  Deployment ID: $DEPLOYMENT_ID"
echo "  Region:        $REGION"
echo "  Isolation:     $ISOLATION"
echo ""

# ── Step 1: Secrets Manager ─────────────────────────────────────────────────
if [[ "$SKIP_SECRETS" == false ]]; then
  SECRET_NAME="${PROJECT_PREFIX}/${DEPLOYMENT_ID}/${CLIENT_ID}"
  ACCESS_TOKEN=$(python3 -c "import uuid; print(uuid.uuid4())")
  SECRET_JSON=$(cat <<EOJSON
{
  "access_token": "${ACCESS_TOKEN}",
  "client_id": "${CLIENT_ID}",
  "client_name": "${CLIENT_NAME}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOJSON
)

  echo -e "${YELLOW}[1/3] Creating Secrets Manager entry: ${SECRET_NAME}${NC}"
  if [[ "$DRY_RUN" == true ]]; then
    echo "  DRY RUN: aws secretsmanager create-secret --name $SECRET_NAME ..."
  else
    aws secretsmanager create-secret \
      --name "$SECRET_NAME" \
      --secret-string "$SECRET_JSON" \
      --description "TempMonitor access token for ${CLIENT_NAME}" \
      --region "$REGION" 2>/dev/null \
    && echo -e "  ${GREEN}✓ Secret created${NC}" \
    || echo -e "  ${YELLOW}⚠ Secret already exists (use manage_client.py rotate to update)${NC}"
  fi

  if [[ -z "$DASHBOARD_URL" ]]; then
    DASHBOARD_URL=$(python3 scripts/manage_client.py list --deployment-id "$DEPLOYMENT_ID" --region "$REGION" 2>/dev/null | head -1 || echo "")
    [[ -z "$DASHBOARD_URL" ]] && DASHBOARD_URL="https://<YOUR-DASHBOARD-URL>"
  fi
  echo -e "  Access URL: ${GREEN}${DASHBOARD_URL}/connect/${ACCESS_TOKEN}${NC}"
else
  echo -e "${YELLOW}[1/3] Skipping Secrets Manager (--skip-secrets)${NC}"
fi

# ── Step 2: DynamoDB alerts table ────────────────────────────────────────────
if [[ -n "$ALERTS_TABLE" ]]; then
  echo -e "${YELLOW}[2/3] Creating DynamoDB table: ${ALERTS_TABLE}${NC}"
  if [[ "$DRY_RUN" == true ]]; then
    echo "  DRY RUN: aws dynamodb create-table --table-name $ALERTS_TABLE ..."
  else
    aws dynamodb create-table \
      --table-name "$ALERTS_TABLE" \
      --billing-mode PAY_PER_REQUEST \
      --attribute-definitions \
        AttributeName=PK,AttributeType=S \
        AttributeName=SK,AttributeType=S \
        AttributeName=client_id,AttributeType=S \
        AttributeName=state_triggered,AttributeType=S \
      --key-schema \
        AttributeName=PK,KeyType=HASH \
        AttributeName=SK,KeyType=RANGE \
      --global-secondary-indexes \
        "IndexName=ClientActiveAlerts,KeySchema=[{AttributeName=client_id,KeyType=HASH},{AttributeName=state_triggered,KeyType=RANGE}],Projection={ProjectionType=ALL}" \
      --region "$REGION" 2>/dev/null \
    && echo -e "  ${GREEN}✓ Table created${NC}" \
    || echo -e "  ${YELLOW}⚠ Table already exists${NC}"
  fi
else
  echo -e "${YELLOW}[2/3] Using shared alerts table (no --alerts-table specified)${NC}"
fi

# ── Step 3: Update clients.yaml ──────────────────────────────────────────────
REGISTRY_FILE="$(cd "$(dirname "$0")/.." && pwd)/clients.yaml"

if [[ "$SKIP_REGISTRY" == false ]] && [[ -f "$REGISTRY_FILE" ]]; then
  echo -e "${YELLOW}[3/3] Updating clients.yaml${NC}"

  PASSWORD_REF="\${${DB_PASSWORD_ENV:-MYSQL_PASSWORD}}"
  ALERTS_ENTRY="${ALERTS_TABLE:-\"\"}"

  CLIENT_BLOCK=$(cat <<EOYAML

  "${CLIENT_ID}":
    name: "${CLIENT_NAME}"
    isolation: ${ISOLATION}
    db:
      host: ${DB_HOST:-\${MYSQL_HOST}}
      user: ${DB_USER:-\${MYSQL_USER}}
      password: ${PASSWORD_REF}
      database: ${DB_DATABASE:-\${MYSQL_DATABASE}}
      port: ${DB_PORT}
    parquet:
      bucket: ""
      prefix: "sensor-data/client-${CLIENT_ID}/"
    alerts_table: ${ALERTS_ENTRY}
EOYAML
)

  if grep -q "\"${CLIENT_ID}\":" "$REGISTRY_FILE" 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ Client ${CLIENT_ID} already in registry — skipping${NC}"
  elif [[ "$DRY_RUN" == true ]]; then
    echo "  DRY RUN: Would append to $REGISTRY_FILE:"
    echo "$CLIENT_BLOCK"
  else
    echo "$CLIENT_BLOCK" >> "$REGISTRY_FILE"
    echo -e "  ${GREEN}✓ Added to clients.yaml${NC}"
  fi
else
  echo -e "${YELLOW}[3/3] Skipping registry update${NC}"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Onboarding complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify:   curl -s \$DASHBOARD_URL/healthz | python3 -m json.tool"
echo "  2. Share:     Send the access URL to facility officers"
echo "  3. Deploy:    sam deploy (if not auto-deployed via CI/CD)"
