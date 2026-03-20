#!/usr/bin/env bash
# Description: Validates LogicMonitor API credentials by making a test API call.
# Description: Checks that LM_COMPANY, LM_ACCESS_ID, and LM_ACCESS_KEY are set and functional.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env.sh"

echo "=== LogicMonitor Environment Validation ==="

# Check required variables
MISSING=0
for VAR in LM_COMPANY LM_ACCESS_ID LM_ACCESS_KEY; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set"
        MISSING=1
    else
        echo "[OK]   $VAR is set"
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "[ERROR] Missing required LogicMonitor environment variables."
    echo "        Set them in .env or export them in your shell."
    exit 1
fi

# Build LMv1 authentication signature
EPOCH=$(date +%s%3N)
REQUEST_VARS="GET${EPOCH}/setting/accesslogs"
SIGNATURE=$(echo -n "$REQUEST_VARS" | openssl dgst -sha256 -hmac "$LM_ACCESS_KEY" -binary | base64)
AUTH="LMv1 ${LM_ACCESS_ID}:${SIGNATURE}:${EPOCH}"

echo ""
echo "Testing API connectivity to ${LM_COMPANY}.logicmonitor.com ..."

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: $AUTH" \
    -H "Content-Type: application/json" \
    "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/accesslogs?size=1")

if [ "$HTTP_CODE" -eq 200 ]; then
    echo "[OK]   API call successful (HTTP $HTTP_CODE)"
    echo ""
    echo "=== LogicMonitor validation PASSED ==="
    exit 0
else
    echo "[FAIL] API call returned HTTP $HTTP_CODE"
    echo ""
    echo "=== LogicMonitor validation FAILED ==="
    exit 1
fi
