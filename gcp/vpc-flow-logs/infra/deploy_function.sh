#!/usr/bin/env bash
# Description: Deploys the VPC Flow Logs Cloud Function to GCP (2nd gen).
# Description: Configures Eventarc Pub/Sub trigger and Secret Manager references.

set -euo pipefail

# ------------------------------------------------------------------
# Usage and parameter validation
# ------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") --project PROJECT_ID --region REGION [OPTIONS]

Required:
  --project       GCP project ID
  --region        GCP region (e.g., us-central1)

Options:
  --function      Cloud Function name (default: vpc-flowlogs-to-lm)
  --topic         Pub/Sub topic name (default: vpc-flowlogs-lm)
  --source-name   Webhook source name (default: GCP-VPC-FlowLogs)
  --memory        Function memory allocation (default: 256Mi)
  --timeout       Function timeout in seconds (default: 60)
  --use-ingest    Use Phase 1 Ingest API instead of Phase 2 Webhook
  --service-account  Custom service account email for the function
  --help          Show this help message

Example:
  $(basename "$0") --project my-gcp-project --region us-central1
EOF
    exit 1
}

# Defaults
FUNCTION_NAME="vpc-flowlogs-to-lm"
TOPIC_NAME="vpc-flowlogs-lm"
WEBHOOK_SOURCE_NAME="GCP-VPC-FlowLogs"
MEMORY="256Mi"
TIMEOUT="60"
USE_WEBHOOK="true"
PROJECT_ID=""
REGION=""
SERVICE_ACCOUNT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)          PROJECT_ID="$2";              shift 2 ;;
        --region)           REGION="$2";                  shift 2 ;;
        --function)         FUNCTION_NAME="$2";           shift 2 ;;
        --topic)            TOPIC_NAME="$2";              shift 2 ;;
        --source-name)      WEBHOOK_SOURCE_NAME="$2";     shift 2 ;;
        --memory)           MEMORY="$2";                  shift 2 ;;
        --timeout)          TIMEOUT="$2";                 shift 2 ;;
        --use-ingest)       USE_WEBHOOK="false";          shift ;;
        --service-account)  SERVICE_ACCOUNT="$2";         shift 2 ;;
        --help)             usage ;;
        *)                  echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$PROJECT_ID" || -z "$REGION" ]]; then
    echo "Error: --project and --region are required."
    usage
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/../cloud_function" && pwd)"

echo "=========================================="
echo " Deploy Cloud Function: $FUNCTION_NAME"
echo "=========================================="
echo "Project:      $PROJECT_ID"
echo "Region:       $REGION"
echo "Source:       $SOURCE_DIR"
echo "Topic:        $TOPIC_NAME"
echo "Webhook mode: $USE_WEBHOOK"
echo "Memory:       $MEMORY"
echo "Timeout:      ${TIMEOUT}s"
echo ""

# Set the active project
gcloud config set project "$PROJECT_ID" --quiet

# ------------------------------------------------------------------
# Step 1: Verify prerequisites
# ------------------------------------------------------------------

echo "[1/3] Verifying prerequisites..."

# Check that the Pub/Sub topic exists
if ! gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo "  Error: Pub/Sub topic '$TOPIC_NAME' does not exist."
    echo "  Run setup_gcp.sh first to create the required resources."
    exit 1
fi
echo "  Pub/Sub topic: OK"

# Check that required secrets exist
REQUIRED_SECRETS=("lm-company-name" "lm-bearer-token")
if [[ "$USE_WEBHOOK" == "false" ]]; then
    # Ingest API mode also needs access credentials
    REQUIRED_SECRETS+=("lm-access-id" "lm-access-key")
fi

for secret in "${REQUIRED_SECRETS[@]}"; do
    if ! gcloud secrets describe "$secret" --project="$PROJECT_ID" &>/dev/null; then
        echo "  Error: Secret '$secret' does not exist in Secret Manager."
        echo "  Run setup_gcp.sh first or create the secret manually."
        exit 1
    fi
done
echo "  Secrets: OK"

# Verify source directory contains the function code
if [[ ! -f "$SOURCE_DIR/main.py" ]]; then
    echo "  Error: main.py not found in $SOURCE_DIR"
    exit 1
fi
echo "  Source code: OK"
echo ""

# ------------------------------------------------------------------
# Step 2: Build the secret environment variable flags
# ------------------------------------------------------------------

echo "[2/3] Preparing deployment configuration..."

# Secret Manager references are passed as environment variables to the
# function. The format is ENV_VAR=SECRET_NAME:VERSION where "latest"
# pulls the most recent version.
SECRET_ENV_VARS="LM_COMPANY_NAME=lm-company-name:latest"
SECRET_ENV_VARS+=",LM_BEARER_TOKEN=lm-bearer-token:latest"

if [[ "$USE_WEBHOOK" == "false" ]]; then
    SECRET_ENV_VARS+=",LM_ACCESS_ID=lm-access-id:latest"
    SECRET_ENV_VARS+=",LM_ACCESS_KEY=lm-access-key:latest"
fi

# Plain environment variables (non-sensitive configuration)
SET_ENV_VARS="USE_WEBHOOK=${USE_WEBHOOK}"
SET_ENV_VARS+=",WEBHOOK_SOURCE_NAME=${WEBHOOK_SOURCE_NAME}"

echo "  Environment vars: USE_WEBHOOK=$USE_WEBHOOK, WEBHOOK_SOURCE_NAME=$WEBHOOK_SOURCE_NAME"
echo "  Secret refs: $SECRET_ENV_VARS"
echo ""

# ------------------------------------------------------------------
# Step 3: Deploy the Cloud Function (2nd gen)
# ------------------------------------------------------------------

echo "[3/3] Deploying Cloud Function..."
echo ""

# Build the deploy command
# 2nd gen Cloud Functions use --gen2 flag and Eventarc for triggers.
DEPLOY_CMD=(
    gcloud functions deploy "$FUNCTION_NAME"
    --gen2
    --project="$PROJECT_ID"
    --region="$REGION"
    # Source directory containing main.py and requirements.txt
    --source="$SOURCE_DIR"
    # Python 3.12 runtime
    --runtime=python312
    # The function entry point (registered with functions-framework)
    --entry-point=handle_pubsub
    # Eventarc Pub/Sub trigger: fires on each message published to the topic
    --trigger-topic="$TOPIC_NAME"
    # Resource limits
    --memory="$MEMORY"
    --timeout="${TIMEOUT}s"
    # Concurrency: allow multiple concurrent requests per instance
    --concurrency=10
    # Min/max instances for cost control
    --min-instances=0
    --max-instances=100
    # Environment variables
    --set-env-vars="$SET_ENV_VARS"
    # Secrets from Secret Manager, mounted as environment variables
    --set-secrets="$SECRET_ENV_VARS"
    # Quiet mode for cleaner output
    --quiet
)

# Add custom service account if provided
if [[ -n "$SERVICE_ACCOUNT" ]]; then
    DEPLOY_CMD+=(--service-account="$SERVICE_ACCOUNT")
fi

echo "Running: ${DEPLOY_CMD[*]}"
echo ""

"${DEPLOY_CMD[@]}"

echo ""
echo "=========================================="
echo " Deployment Complete"
echo "=========================================="
echo ""

# Display function status
gcloud functions describe "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --gen2 \
    --format="table(name, state, updateTime, serviceConfig.uri)" \
    2>/dev/null || echo "  (Could not retrieve function details)"

echo ""
echo "Verify logs with:"
echo "  gcloud functions logs read $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --gen2 --limit=20"
echo ""
echo "To test, generate VPC traffic or publish a test message:"
echo "  gcloud pubsub topics publish $TOPIC_NAME --project=$PROJECT_ID --message='{\"test\": true}'"
echo ""
