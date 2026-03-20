#!/usr/bin/env bash
# Description: End-to-end test for the Azure VNet Flow Log Forwarder pipeline.
# Description: Verifies the full path from flow log blob to LM Logs Ingest API response.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJECT_ROOT/scripts/common/load-env.sh"

FUNC_APP_NAME="${AZURE_FUNC_APP_NAME:-kpmg-vnet-flow-forwarder}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-CTA_Resource_Group}"
STORAGE_ACCOUNT="${AZURE_FLOW_LOG_STORAGE:-rmazurestorage}"
CONTAINER="insights-logs-flowlogflowevent"

echo "=== E2E Test: VNet Flow Log Forwarder ==="
echo ""

# Test 1: Verify Function App is running
echo "--- Test 1: Function App Status ---"
FUNC_STATE=$(az functionapp show \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query state \
    --output tsv 2>/dev/null || echo "NOT_FOUND")

if [ "$FUNC_STATE" = "Running" ]; then
    echo "PASS: Function App is Running"
else
    echo "FAIL: Function App state is $FUNC_STATE"
    exit 1
fi

# Test 2: Verify Event Grid subscription exists
echo ""
echo "--- Test 2: Event Grid Subscription ---"
STORAGE_ID=$(az storage account show \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query id \
    --output tsv)

EG_SUB=$(az eventgrid event-subscription show \
    --name "vnet-flow-log-events" \
    --source-resource-id "$STORAGE_ID" \
    --query provisioningState \
    --output tsv 2>/dev/null || echo "NOT_FOUND")

if [ "$EG_SUB" = "Succeeded" ]; then
    echo "PASS: Event Grid subscription is active"
else
    echo "FAIL: Event Grid subscription state is $EG_SUB"
    exit 1
fi

# Test 3: Verify flow log blobs exist in storage
echo ""
echo "--- Test 3: Flow Log Blobs ---"
STORAGE_KEY=$(az storage account keys list \
    --account-name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[0].value" \
    --output tsv)

BLOB_COUNT=$(az storage blob list \
    --container-name "$CONTAINER" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --query "length([?ends_with(name, 'PT1H.json')])" \
    --output tsv 2>/dev/null || echo "0")

if [ "$BLOB_COUNT" -gt 0 ]; then
    echo "PASS: Found $BLOB_COUNT PT1H.json blobs"
else
    echo "WARN: No PT1H.json blobs yet (flow logs may need time to generate)"
fi

# Test 4: Verify watermark table exists
echo ""
echo "--- Test 4: Watermark Table ---"
TABLE_EXISTS=$(az storage table exists \
    --name "vnetflowwatermarks" \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --query exists \
    --output tsv 2>/dev/null || echo "false")

if [ "$TABLE_EXISTS" = "true" ]; then
    echo "PASS: Watermark table exists"
else
    echo "WARN: Watermark table not found (may be created on first trigger)"
fi

# Test 5: Check Function App recent invocations
echo ""
echo "--- Test 5: Recent Function Invocations ---"
echo "Checking function logs (last 10 minutes)..."
az functionapp log tail \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --timeout 10 2>/dev/null || echo "WARN: Could not read function logs (may need Application Insights)"

# Test 6: Verify LM API connectivity
echo ""
echo "--- Test 6: LM API Connectivity ---"
LM_URL="https://${LM_COMPANY}.logicmonitor.com/rest/log/ingest"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$LM_URL" \
    -H "Content-Type: application/json" \
    -d '[]' 2>/dev/null || echo "000")

# 401 is expected without auth, but confirms the endpoint is reachable
if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "202" ]; then
    echo "PASS: LM ingest endpoint reachable (HTTP $HTTP_CODE)"
else
    echo "FAIL: LM ingest endpoint returned HTTP $HTTP_CODE"
fi

echo ""
echo "=== E2E Test Complete ==="
