#!/usr/bin/env bash
# Description: End-to-end test for Azure VNet IP Usage DataSource.
# Description: Validates Azure credentials, ARM API access, and LM portal state.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../../../.."
source "$PROJECT_ROOT/shared/scripts/load-env.sh"

PASS=0
FAIL=0
WARN=0

pass() { echo "[PASS] $1"; ((PASS++)); }
fail() { echo "[FAIL] $1"; ((FAIL++)); }
warn() { echo "[WARN] $1"; ((WARN++)); }

echo "=== Azure VNet IP Usage DataSource E2E Tests ==="
echo ""

# Test 1: Required Azure env vars
echo "--- Test 1: Azure credentials are set ---"
ALL_SET=true
for VAR in AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET AZURE_SUBSCRIPTION_ID; do
    if [ -z "${!VAR:-}" ]; then
        fail "$VAR is not set"
        ALL_SET=false
    fi
done
if [ "$ALL_SET" = true ]; then
    pass "All Azure credential env vars are set"
fi

# Test 2: Acquire Azure access token
echo "--- Test 2: Azure token acquisition ---"
TOKEN_RESPONSE=$(curl -s -X POST \
    "https://login.microsoftonline.com/${AZURE_TENANT_ID}/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${AZURE_CLIENT_ID}&client_secret=${AZURE_CLIENT_SECRET}&scope=https%3A%2F%2Fmanagement.azure.com%2F.default&grant_type=client_credentials")

AZURE_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty' 2>/dev/null)
if [ -n "$AZURE_TOKEN" ]; then
    pass "Azure token acquired"
else
    fail "Failed to acquire Azure token"
    echo "  Response: $(echo "$TOKEN_RESPONSE" | jq -r '.error_description // .error // "unknown"' 2>/dev/null)"
fi

# Test 3: VNet usages API is reachable
echo "--- Test 3: ARM API reachable ---"
if [ -n "$AZURE_TOKEN" ]; then
    API_RESPONSE=$(curl -s \
        -H "Authorization: Bearer $AZURE_TOKEN" \
        -H "Content-Type: application/json" \
        "https://management.azure.com/subscriptions/${AZURE_SUBSCRIPTION_ID}/providers/Microsoft.Network/virtualNetworks?api-version=2024-05-01")

    if echo "$API_RESPONSE" | jq -e '.value' > /dev/null 2>&1; then
        VNET_COUNT=$(echo "$API_RESPONSE" | jq '.value | length')
        pass "ARM API reachable, found $VNET_COUNT VNet(s)"
    else
        fail "ARM API returned unexpected response"
    fi
else
    warn "Skipped (no token)"
fi

# Test 4: Subnet usage data available
echo "--- Test 4: Subnet usage data ---"
if [ -n "$AZURE_TOKEN" ] && [ "${VNET_COUNT:-0}" -gt 0 ]; then
    FIRST_VNET=$(echo "$API_RESPONSE" | jq -r '.value[0].name')
    FIRST_RG=$(echo "$API_RESPONSE" | jq -r '.value[0].id' | cut -d'/' -f5)

    USAGE_RESPONSE=$(curl -s \
        -H "Authorization: Bearer $AZURE_TOKEN" \
        -H "Content-Type: application/json" \
        "https://management.azure.com/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${FIRST_RG}/providers/Microsoft.Network/virtualNetworks/${FIRST_VNET}/usages?api-version=2024-05-01")

    SUBNET_COUNT=$(echo "$USAGE_RESPONSE" | jq '.value | length' 2>/dev/null || echo "0")
    if [ "$SUBNET_COUNT" -gt 0 ]; then
        pass "Subnet usage data available ($SUBNET_COUNT subnets in $FIRST_VNET)"
    else
        warn "No subnets found in $FIRST_VNET"
    fi
else
    warn "Skipped (no VNets or no token)"
fi

# Test 5: LM portal credentials
echo "--- Test 5: LM portal credentials ---"
if [ -n "${LM_COMPANY:-}" ] && [ -n "${LM_BEARER_TOKEN:-}" ]; then
    pass "LM portal credentials are set"
else
    warn "LM_COMPANY or LM_BEARER_TOKEN not set (portal tests skipped)"
fi

# Test 6: DataSource exists in LM portal
echo "--- Test 6: DataSource in portal ---"
if [ -n "${LM_COMPANY:-}" ] && [ -n "${LM_BEARER_TOKEN:-}" ]; then
    AUTH_FILE=$(mktemp)
    trap "rm -f $AUTH_FILE" EXIT
    printf 'header = "Authorization: Bearer %s"\n' "$LM_BEARER_TOKEN" > "$AUTH_FILE"

    DS_CHECK=$(curl -s \
        -K "$AUTH_FILE" \
        -H "X-Version: 3" \
        "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/datasources?filter=name:%22Azure_VNet_IPUsage%22&size=1&fields=id,name")

    DS_ID=$(echo "$DS_CHECK" | jq -r '.items[0]?.id // empty' 2>/dev/null)
    if [ -n "$DS_ID" ]; then
        pass "DataSource 'Azure_VNet_IPUsage' exists in portal (ID: $DS_ID)"
    else
        warn "DataSource 'Azure_VNet_IPUsage' not found in portal (import it first)"
    fi
else
    warn "Skipped (no LM credentials)"
fi

# Summary
echo ""
echo "=== Results ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "  WARN: $WARN"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
