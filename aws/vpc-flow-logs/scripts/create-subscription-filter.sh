#!/usr/bin/env bash
# Description: Creates a CloudWatch Logs subscription filter linking a log group to the LM Logs Forwarder Lambda.
# Description: Adds invoke permission for CloudWatch Logs and creates the filter with an empty pattern (all logs).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

LOG_GROUP_NAME="${1:-/aws/vpc/flowlogs}"
FILTER_NAME="${2:-LMLogsForwarder}"
FUNCTION_NAME="LMLogsForwarder"

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "=== Creating CloudWatch Subscription Filter ==="
echo "Log Group:     $LOG_GROUP_NAME"
echo "Filter Name:   $FILTER_NAME"
echo "Lambda:        $FUNCTION_NAME"
echo ""

# Get Lambda ARN
echo "[1/3] Looking up Lambda function ARN..."
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text \
    $PROFILE_FLAG)
echo "  [OK] Lambda ARN: $LAMBDA_ARN"

# Build a statement ID from the log group name (replace / with -)
STATEMENT_ID="CloudWatchLogsInvoke${LOG_GROUP_NAME//\//-}"

# Add Lambda permission for CloudWatch Logs to invoke
echo "[2/3] Adding Lambda invoke permission for CloudWatch Logs..."
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text $PROFILE_FLAG)
SOURCE_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}:*"

if aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --action "lambda:InvokeFunction" \
    --principal "logs.amazonaws.com" \
    --source-arn "$SOURCE_ARN" \
    $PROFILE_FLAG > /dev/null 2>&1; then
    echo "  [OK] Permission added"
else
    echo "  [OK] Permission already exists"
fi

# Create subscription filter
echo "[3/3] Creating subscription filter..."
aws logs put-subscription-filter \
    --log-group-name "$LOG_GROUP_NAME" \
    --filter-name "$FILTER_NAME" \
    --filter-pattern "" \
    --destination-arn "$LAMBDA_ARN" \
    $PROFILE_FLAG
echo "  [OK] Subscription filter created"

# Verify
echo ""
echo "Verifying subscription filter..."
aws logs describe-subscription-filters \
    --log-group-name "$LOG_GROUP_NAME" \
    --query 'subscriptionFilters[*].{Name:filterName,Destination:destinationArn,Created:creationTime}' \
    --output table \
    $PROFILE_FLAG

echo ""
echo "=== Subscription Filter Complete ==="
echo "Log Group '$LOG_GROUP_NAME' is now forwarding to Lambda '$FUNCTION_NAME'."
