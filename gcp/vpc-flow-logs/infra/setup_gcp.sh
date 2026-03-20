#!/usr/bin/env bash
# Description: Provisions GCP resources for the VPC Flow Logs to LogicMonitor pipeline.
# Description: Creates Pub/Sub topic, Log Router sink, and Secret Manager entries.

set -euo pipefail

# ------------------------------------------------------------------
# Usage and parameter validation
# ------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") --project PROJECT_ID --region REGION --company LM_COMPANY_NAME [OPTIONS]

Required:
  --project   GCP project ID
  --region    GCP region (e.g., us-central1)
  --company   LogicMonitor portal name (e.g., acmecorp)

Options:
  --topic     Pub/Sub topic name (default: vpc-flowlogs-lm)
  --sink      Log Router sink name (default: vpc-flowlogs-to-lm)
  --help      Show this help message

Example:
  $(basename "$0") --project my-gcp-project --region us-central1 --company acmecorp
EOF
    exit 1
}

# Defaults
TOPIC_NAME="vpc-flowlogs-lm"
SINK_NAME="vpc-flowlogs-to-lm"
PROJECT_ID=""
REGION=""
LM_COMPANY_NAME=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)   PROJECT_ID="$2";      shift 2 ;;
        --region)    REGION="$2";           shift 2 ;;
        --company)   LM_COMPANY_NAME="$2";  shift 2 ;;
        --topic)     TOPIC_NAME="$2";       shift 2 ;;
        --sink)      SINK_NAME="$2";        shift 2 ;;
        --help)      usage ;;
        *)           echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$PROJECT_ID" || -z "$REGION" || -z "$LM_COMPANY_NAME" ]]; then
    echo "Error: --project, --region, and --company are required."
    usage
fi

echo "=========================================="
echo " GCP VPC Flow Logs -> LogicMonitor Setup"
echo "=========================================="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Company:  $LM_COMPANY_NAME"
echo "Topic:    $TOPIC_NAME"
echo "Sink:     $SINK_NAME"
echo ""

# Set the active project for all gcloud commands
gcloud config set project "$PROJECT_ID" --quiet

# ------------------------------------------------------------------
# Step 1: Enable required APIs
# ------------------------------------------------------------------

echo "[1/5] Enabling required APIs..."

APIS=(
    "pubsub.googleapis.com"
    "cloudfunctions.googleapis.com"
    "cloudbuild.googleapis.com"
    "logging.googleapis.com"
    "secretmanager.googleapis.com"
    "eventarc.googleapis.com"
    "run.googleapis.com"
)

for api in "${APIS[@]}"; do
    if gcloud services list --enabled --filter="config.name=$api" --format="value(config.name)" 2>/dev/null | grep -q "$api"; then
        echo "  Already enabled: $api"
    else
        echo "  Enabling: $api"
        gcloud services enable "$api" --quiet
    fi
done
echo ""

# ------------------------------------------------------------------
# Step 2: Create Pub/Sub topic
# ------------------------------------------------------------------

echo "[2/5] Creating Pub/Sub topic: $TOPIC_NAME"

if gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo "  Topic already exists, skipping."
else
    gcloud pubsub topics create "$TOPIC_NAME" \
        --project="$PROJECT_ID" \
        --labels="purpose=vpc-flowlogs-lm,managed-by=setup-script"
    echo "  Topic created."
fi
echo ""

# ------------------------------------------------------------------
# Step 3: Create Log Router sink
# ------------------------------------------------------------------

echo "[3/5] Creating Log Router sink: $SINK_NAME"

# Sink filter captures VPC Flow Logs from both the Compute Engine API
# (gce_subnetwork) and the Network Management API (vpc_flow_logs_config).
SINK_FILTER='resource.type="gce_subnetwork" log_id("compute.googleapis.com/vpc_flows") OR resource.type="vpc_flow_logs_config" log_id("networkmanagement.googleapis.com/vpc_flows")'
SINK_DESTINATION="pubsub.googleapis.com/projects/${PROJECT_ID}/topics/${TOPIC_NAME}"

if gcloud logging sinks describe "$SINK_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo "  Sink already exists, updating filter..."
    gcloud logging sinks update "$SINK_NAME" \
        "$SINK_DESTINATION" \
        --project="$PROJECT_ID" \
        --log-filter="$SINK_FILTER" \
        --quiet
    echo "  Sink updated."
else
    gcloud logging sinks create "$SINK_NAME" \
        "$SINK_DESTINATION" \
        --project="$PROJECT_ID" \
        --log-filter="$SINK_FILTER" \
        --quiet
    echo "  Sink created."
fi

# Grant the sink's service account permission to publish to the topic.
# The sink creates a unique writer identity (service account) that needs
# the pubsub.publisher role on the destination topic.
SINK_SA=$(gcloud logging sinks describe "$SINK_NAME" \
    --project="$PROJECT_ID" \
    --format="value(writerIdentity)")

echo "  Sink service account: $SINK_SA"
echo "  Granting Pub/Sub Publisher role on topic..."

gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
    --project="$PROJECT_ID" \
    --member="$SINK_SA" \
    --role="roles/pubsub.publisher" \
    --quiet &>/dev/null

echo "  Permission granted."
echo ""

# ------------------------------------------------------------------
# Step 4: Create Secret Manager entries
# ------------------------------------------------------------------

echo "[4/5] Creating Secret Manager entries..."

create_secret() {
    local secret_name="$1"
    local prompt_msg="$2"
    local default_value="${3:-}"

    if gcloud secrets describe "$secret_name" --project="$PROJECT_ID" &>/dev/null; then
        echo "  Secret '$secret_name' already exists, skipping."
        return
    fi

    # Create the secret container
    gcloud secrets create "$secret_name" \
        --project="$PROJECT_ID" \
        --replication-policy="automatic" \
        --labels="purpose=vpc-flowlogs-lm,managed-by=setup-script" \
        --quiet

    # Set the secret value
    if [[ -n "$default_value" ]]; then
        echo -n "$default_value" | gcloud secrets versions add "$secret_name" \
            --project="$PROJECT_ID" \
            --data-file=- \
            --quiet
        echo "  Secret '$secret_name' created with provided value."
    else
        echo ""
        echo "  Enter value for secret '$secret_name':"
        echo "  ($prompt_msg)"
        read -rs SECRET_VALUE
        echo ""

        if [[ -z "$SECRET_VALUE" ]]; then
            echo "  Warning: Empty value provided for '$secret_name'. You can update it later:"
            echo "    echo -n 'VALUE' | gcloud secrets versions add $secret_name --data-file=-"
        fi

        echo -n "$SECRET_VALUE" | gcloud secrets versions add "$secret_name" \
            --project="$PROJECT_ID" \
            --data-file=- \
            --quiet
        echo "  Secret '$secret_name' created."
    fi
}

# lm-company-name can be set directly from the provided parameter
create_secret "lm-company-name" "LogicMonitor portal name" "$LM_COMPANY_NAME"

# lm-bearer-token must be entered interactively (sensitive credential)
create_secret "lm-bearer-token" "Bearer token for LM Webhook endpoint auth"

echo ""

# ------------------------------------------------------------------
# Step 5: Summary
# ------------------------------------------------------------------

echo "[5/5] Setup complete."
echo ""
echo "=========================================="
echo " Resource Summary"
echo "=========================================="
echo ""
echo "Pub/Sub Topic:"
echo "  projects/$PROJECT_ID/topics/$TOPIC_NAME"
echo ""
echo "Log Router Sink:"
echo "  Name:        $SINK_NAME"
echo "  Destination: $SINK_DESTINATION"
echo "  Filter:      $SINK_FILTER"
echo "  Writer SA:   $SINK_SA"
echo ""
echo "Secrets:"
echo "  lm-company-name   (set to: $LM_COMPANY_NAME)"
echo "  lm-bearer-token   (set interactively)"
echo ""
echo "Next steps:"
echo "  1. Deploy the Cloud Function:  ./deploy_function.sh --project $PROJECT_ID --region $REGION"
echo "  2. Enable VPC Flow Logs on target subnets (if not already enabled)"
echo "  3. Configure the Webhook LogSource in LogicMonitor portal"
echo "     (see docs/webhook_logsource_setup.md)"
echo ""
