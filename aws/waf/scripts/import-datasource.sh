#!/usr/bin/env bash
# Description: Imports a DataSource JSON definition into LogicMonitor via REST API.
# Description: Uses Bearer token auth to POST to /setting/datasources.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <datasource_json_file>"
    echo ""
    echo "  Imports a DataSource definition into LogicMonitor."
    echo ""
    echo "  Examples:"
    echo "    $0 datasources/AWS_WAF_Custom.json"
    echo "    $0 datasources/AWS_Shield_Custom.json"
    echo "    $0 datasources/AWS_NetworkFirewall_Custom.json"
    exit 1
fi

JSON_FILE="$1"

if [ ! -f "$JSON_FILE" ]; then
    echo "[FAIL] File not found: $JSON_FILE"
    exit 1
fi

# Validate LM credentials
for VAR in LM_COMPANY LM_BEARER_TOKEN; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set"
        exit 1
    fi
done

DS_NAME=$(jq -r '.name' "$JSON_FILE")
echo "=== Importing DataSource: $DS_NAME ==="
echo "File: $JSON_FILE"
echo "Portal: ${LM_COMPANY}.logicmonitor.com"
echo ""

# Write auth header to a temp file to handle special characters
AUTH_FILE=$(mktemp)
trap "rm -f $AUTH_FILE" EXIT
printf 'header = "Authorization: Bearer %s"\n' "$LM_BEARER_TOKEN" > "$AUTH_FILE"

# Check if DataSource already exists using exact name filter
CHECK_RESPONSE=$(curl -s \
    -K "$AUTH_FILE" \
    -H "X-Version: 3" \
    "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/datasources?filter=name:%22${DS_NAME}%22&size=1&fields=id,name")

EXISTING_ID=$(echo "$CHECK_RESPONSE" | jq -r '.items[0]?.id // empty' 2>/dev/null)

if [ -n "$EXISTING_ID" ]; then
    echo "[OK] DataSource '$DS_NAME' already exists (ID: $EXISTING_ID)"
    echo "     To update, delete it first or use the LM portal."
    exit 0
fi

# Import via POST
echo "Importing DataSource..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -K "$AUTH_FILE" \
    -H "Content-Type: application/json" \
    -H "X-Version: 3" \
    -d @"$JSON_FILE" \
    "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/datasources")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
RESPONSE_BODY=$(echo "$RESPONSE" | sed '$d')

if echo "$RESPONSE_BODY" | jq -e '.id' > /dev/null 2>&1; then
    DS_ID=$(echo "$RESPONSE_BODY" | jq -r '.id')
    if [ "$DS_ID" != "null" ]; then
        echo "[OK] DataSource imported successfully"
        echo "     ID: $DS_ID"
        echo "     Name: $DS_NAME"
        echo ""
        echo "=== Import Complete ==="
        exit 0
    fi
fi

ERROR_MSG=$(echo "$RESPONSE_BODY" | jq -r '.errorMessage // "unknown error"' 2>/dev/null || echo "$RESPONSE_BODY")
echo "[FAIL] Import failed (HTTP $HTTP_CODE): $ERROR_MSG"
exit 1
