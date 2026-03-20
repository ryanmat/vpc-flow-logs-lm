#!/usr/bin/env bash
# Description: Runs the Cloud Function locally using functions-framework.
# Description: Loads environment variables and starts the local development server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# Load environment variables from .env file if it exists
if [ -f "$ENV_FILE" ]; then
    echo "Loading environment from ${ENV_FILE}"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "No .env file found at ${ENV_FILE}"
    echo "Copy variables.env.example to .env and fill in your values:"
    echo "  cp ${SCRIPT_DIR}/variables.env.example ${ENV_FILE}"
    exit 1
fi

echo "Starting Cloud Function locally on port 8080..."
echo "Portal: ${LM_COMPANY_NAME}.${LM_COMPANY_DOMAIN:-logicmonitor.com}"
echo "Mode: $([ "${USE_WEBHOOK:-false}" = "true" ] && echo "Webhook" || echo "Ingest API")"
echo ""

# Run the Cloud Function locally
cd "$PROJECT_ROOT"
uv run functions-framework \
    --target=handle_pubsub \
    --signature-type=cloudevent \
    --source=cloud_function/main.py \
    --port=8080

# To send a test CloudEvent:
#
#   curl -X POST http://localhost:8080 \
#     -H "Content-Type: application/cloudevents+json" \
#     -d @cloud_function/tests/sample_data/pubsub_cloud_event.json
#
# To send the external traffic fixture:
#
#   curl -X POST http://localhost:8080 \
#     -H "Content-Type: application/cloudevents+json" \
#     -d @cloud_function/tests/sample_data/pubsub_cloud_event_external.json
#
# To test with real VPC traffic (from a VM within the VPC):
#
#   1. Start this script in one terminal (local function server)
#   2. In another terminal, run the traffic generator:
#      ./infra/generate_test_traffic.sh --target <VM_IP> --project <PROJECT_ID>
#   3. Wait 5-10 minutes for flow logs to aggregate
#   4. Flow logs will arrive via Pub/Sub and be processed by this local function
#
# Note: For the local function to receive real Pub/Sub messages, you need to
# configure a push subscription pointed at your local endpoint (e.g., via
# ngrok or Cloud Run proxy). For simpler testing, deploy to GCP and use
# the Eventarc trigger.
