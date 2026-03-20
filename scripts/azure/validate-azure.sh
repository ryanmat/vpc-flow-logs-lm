#!/usr/bin/env bash
# Description: Validates Azure CLI installation, login status, and subscription.
# Description: Checks az CLI is installed, user is logged in, and subscription ID matches.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common/load-env.sh"

echo "=== Azure Environment Validation ==="

# Check Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "[FAIL] Azure CLI (az) is not installed"
    echo "       Install: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

AZ_VERSION=$(az version --query '"azure-cli"' -o tsv 2>/dev/null)
echo "[OK]   Azure CLI installed (version $AZ_VERSION)"

# Check user is logged in
ACCOUNT_JSON=$(az account show -o json 2>/dev/null) || {
    echo "[FAIL] Not logged in to Azure. Run: az login"
    exit 1
}

CURRENT_SUB=$(echo "$ACCOUNT_JSON" | jq -r '.id')
CURRENT_NAME=$(echo "$ACCOUNT_JSON" | jq -r '.name')
echo "[OK]   Logged in to Azure (subscription: $CURRENT_NAME)"

# Verify subscription ID if set
if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ]; then
    if [ "$CURRENT_SUB" = "$AZURE_SUBSCRIPTION_ID" ]; then
        echo "[OK]   Subscription ID matches ($CURRENT_SUB)"
    else
        echo "[FAIL] Subscription mismatch"
        echo "       Expected: $AZURE_SUBSCRIPTION_ID"
        echo "       Current:  $CURRENT_SUB"
        echo "       Switch with: az account set --subscription $AZURE_SUBSCRIPTION_ID"
        exit 1
    fi
else
    echo "[WARN] AZURE_SUBSCRIPTION_ID not set, skipping match check"
    echo "       Current subscription: $CURRENT_SUB"
fi

echo ""
echo "=== Azure validation PASSED ==="
exit 0
