#!/usr/bin/env bash
# Description: Deploys the KPMG LM Logs Forwarder Lambda via CloudFormation.
# Description: Uses LogicMonitor's official CF template with a KPMG-specific function name.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common/load-env.sh"

# Validate required LM variables
MISSING=0
for VAR in LM_ACCESS_ID LM_ACCESS_KEY LM_COMPANY; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo "[ERROR] Missing required LogicMonitor environment variables."
    exit 1
fi

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

# KPMG-specific names to avoid conflicts with other deployments in this account
STACK_NAME="kpmg-lm-logs-forwarder"
FUNCTION_NAME="KPMGLMLogsForwarder"
TEMPLATE_URL="https://logicmonitor-logs-forwarder.s3.amazonaws.com/source/latest.yaml"

echo "=== Deploying KPMG LM Logs Forwarder ==="
echo "Stack Name:    $STACK_NAME"
echo "Function:      $FUNCTION_NAME"
echo "Template:      $TEMPLATE_URL"
echo "LM Company:    $LM_COMPANY"
echo ""

# Check if our stack already exists
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "DOES_NOT_EXIST")

if [ "$STACK_STATUS" = "CREATE_COMPLETE" ] || [ "$STACK_STATUS" = "UPDATE_COMPLETE" ]; then
    echo "[OK] Stack '$STACK_NAME' already exists (status: $STACK_STATUS)"
elif [ "$STACK_STATUS" = "DOES_NOT_EXIST" ]; then
    echo "[1/2] Creating CloudFormation stack..."

    # Write parameters to a temp file to handle special characters in credentials
    PARAMS_FILE=$(mktemp)
    trap "rm -f $PARAMS_FILE" EXIT
    cat > "$PARAMS_FILE" <<PARAMS_EOF
[
  {"ParameterKey": "FunctionName", "ParameterValue": "$FUNCTION_NAME"},
  {"ParameterKey": "LMAccessId", "ParameterValue": "$LM_ACCESS_ID"},
  {"ParameterKey": "LMAccessKey", "ParameterValue": "$LM_ACCESS_KEY"},
  {"ParameterKey": "LMCompanyName", "ParameterValue": "$LM_COMPANY"}
]
PARAMS_EOF

    aws cloudformation create-stack \
        --stack-name "$STACK_NAME" \
        --template-url "$TEMPLATE_URL" \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
        --parameters "file://$PARAMS_FILE" \
        $PROFILE_FLAG

    echo "[2/2] Waiting for stack creation to complete..."
    aws cloudformation wait stack-create-complete \
        --stack-name "$STACK_NAME" \
        $PROFILE_FLAG
    echo "  [OK] Stack created successfully"
elif [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ]; then
    echo "[WARN] Stack is in ROLLBACK_COMPLETE state. Deleting and retrying..."
    aws cloudformation delete-stack --stack-name "$STACK_NAME" $PROFILE_FLAG
    aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" $PROFILE_FLAG
    echo "  Deleted. Re-run this script to create fresh."
    exit 1
else
    echo "[WARN] Stack exists in unexpected state: $STACK_STATUS"
    echo "       You may need to delete and recreate."
    echo "       Run: aws cloudformation delete-stack --stack-name $STACK_NAME"
    exit 1
fi

# Output Lambda ARN
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text \
    $PROFILE_FLAG)

echo ""
echo "=== Deployment Complete ==="
echo "Stack Name:  $STACK_NAME"
echo "Function:    $FUNCTION_NAME"
echo "Lambda ARN:  $LAMBDA_ARN"
