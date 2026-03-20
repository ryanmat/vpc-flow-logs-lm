#!/usr/bin/env bash
# Description: Validates AWS CLI installation, credentials, and account identity.
# Description: Supports both env-var credentials and SSO profile via AWS_PROFILE.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common/load-env.sh"

echo "=== AWS Environment Validation ==="

# Check AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "[FAIL] AWS CLI is not installed"
    echo "       Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
fi

AWS_VER=$(aws --version 2>&1 | head -1)
echo "[OK]   AWS CLI installed ($AWS_VER)"

# Build profile flag if AWS_PROFILE is set
PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
    echo "[INFO] Using AWS profile: $AWS_PROFILE"
fi

# Check credentials by calling STS
IDENTITY_JSON=$(aws sts get-caller-identity $PROFILE_FLAG --output json 2>/dev/null) || {
    echo "[FAIL] AWS credentials not configured or expired"
    echo "       If using SSO: aws sso login --profile \$AWS_PROFILE"
    echo "       If using env vars: export AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY"
    exit 1
}

CURRENT_ACCOUNT=$(echo "$IDENTITY_JSON" | jq -r '.Account')
CURRENT_ARN=$(echo "$IDENTITY_JSON" | jq -r '.Arn')
echo "[OK]   Authenticated as: $CURRENT_ARN"

# Verify account ID if set
if [ -n "${AWS_ACCOUNT_ID:-}" ]; then
    if [ "$CURRENT_ACCOUNT" = "$AWS_ACCOUNT_ID" ]; then
        echo "[OK]   Account ID matches ($CURRENT_ACCOUNT)"
    else
        echo "[FAIL] Account ID mismatch"
        echo "       Expected: $AWS_ACCOUNT_ID"
        echo "       Current:  $CURRENT_ACCOUNT"
        exit 1
    fi
else
    echo "[WARN] AWS_ACCOUNT_ID not set, skipping match check"
    echo "       Current account: $CURRENT_ACCOUNT"
fi

echo ""
echo "=== AWS validation PASSED ==="
exit 0
