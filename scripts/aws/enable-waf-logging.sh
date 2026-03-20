#!/usr/bin/env bash
# Description: Enables AWS WAF logging to CloudWatch and wires it to KPMGLMLogsForwarder.
# Description: Creates the waf log group, enables WAF logging config, and creates subscription filter.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common/load-env.sh"

# Usage
if [ $# -lt 1 ]; then
    echo "Usage: $0 <WEB_ACL_ARN> [LOG_GROUP_NAME]"
    echo ""
    echo "  WEB_ACL_ARN      The WAF Web ACL ARN to enable logging on"
    echo "  LOG_GROUP_NAME   Optional, defaults to aws-waf-logs-kpmg"
    echo ""
    echo "  Note: WAF log group names MUST start with 'aws-waf-logs-'"
    echo ""
    echo "To list Web ACLs:"
    echo "  aws wafv2 list-web-acls --scope REGIONAL --profile \$AWS_PROFILE"
    exit 1
fi

WEB_ACL_ARN="$1"
LOG_GROUP_NAME="${2:-aws-waf-logs-kpmg}"

# WAF log group names must start with 'aws-waf-logs-'
if [[ "$LOG_GROUP_NAME" != aws-waf-logs-* ]]; then
    echo "[FAIL] WAF log group name must start with 'aws-waf-logs-'"
    echo "       Got: $LOG_GROUP_NAME"
    exit 1
fi

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

REGION="${AWS_DEFAULT_REGION:-us-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text $PROFILE_FLAG)}"

echo "=== Enabling AWS WAF Logging ==="
echo "Web ACL ARN:  $WEB_ACL_ARN"
echo "Log Group:    $LOG_GROUP_NAME"
echo ""

# Step 1: Create CloudWatch Log Group for WAF
echo "[1/4] Creating CloudWatch Log Group: $LOG_GROUP_NAME"
if aws logs create-log-group \
    --log-group-name "$LOG_GROUP_NAME" \
    $PROFILE_FLAG 2>/dev/null; then
    echo "  [OK] Log group created"
else
    echo "  [OK] Log group already exists"
fi

# Step 2: Set retention
echo "[2/4] Setting retention policy to 7 days"
aws logs put-retention-policy \
    --log-group-name "$LOG_GROUP_NAME" \
    --retention-in-days 7 \
    $PROFILE_FLAG
echo "  [OK] Retention set"

# Step 3: Enable WAF logging
echo "[3/4] Enabling WAF logging configuration..."
LOG_DEST_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}"

LOGGING_CONFIG=$(cat <<EOF
{
  "ResourceArn": "${WEB_ACL_ARN}",
  "LogDestinationConfigs": ["${LOG_DEST_ARN}"]
}
EOF
)

if aws wafv2 put-logging-configuration \
    --logging-configuration "$LOGGING_CONFIG" \
    $PROFILE_FLAG 2>/dev/null; then
    echo "  [OK] WAF logging enabled"
else
    echo "  [FAIL] Could not enable WAF logging"
    echo "         Verify the Web ACL ARN is correct and you have permissions."
    echo "         The WAF resource policy may need updating for CloudWatch Logs access."
    exit 1
fi

# Step 4: Create subscription filter to KPMGLMLogsForwarder
echo "[4/4] Creating subscription filter to KPMGLMLogsForwarder..."
FUNCTION_NAME="KPMGLMLogsForwarder"
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text \
    $PROFILE_FLAG 2>/dev/null) || {
    echo "  [WARN] KPMGLMLogsForwarder Lambda not found. Deploy it first."
    echo "         Run: scripts/aws/deploy-lm-logs-forwarder.sh"
    echo "         Then: scripts/aws/create-subscription-filter.sh $LOG_GROUP_NAME"
    exit 1
}

STATEMENT_ID="CloudWatchLogsInvoke${LOG_GROUP_NAME//\//-}"
SOURCE_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}:*"

# Add Lambda permission
if aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --action "lambda:InvokeFunction" \
    --principal "logs.amazonaws.com" \
    --source-arn "$SOURCE_ARN" \
    $PROFILE_FLAG > /dev/null 2>&1; then
    echo "  [OK] Lambda permission added"
else
    echo "  [OK] Lambda permission already exists"
fi

# Create subscription filter
aws logs put-subscription-filter \
    --log-group-name "$LOG_GROUP_NAME" \
    --filter-name "KPMGLMLogsForwarder" \
    --filter-pattern "" \
    --destination-arn "$LAMBDA_ARN" \
    $PROFILE_FLAG
echo "  [OK] Subscription filter created"

# Verify
echo ""
echo "Verifying WAF logging configuration..."
aws wafv2 get-logging-configuration \
    --resource-arn "$WEB_ACL_ARN" \
    $PROFILE_FLAG \
    --query 'LoggingConfiguration.{ResourceArn:ResourceArn,Destinations:LogDestinationConfigs}' \
    --output table 2>/dev/null || echo "  [INFO] Could not verify logging config"

echo ""
echo "=== WAF Logging Enabled ==="
echo "WAF logs will flow: WAF -> CloudWatch ($LOG_GROUP_NAME) -> Lambda -> LM Logs"
