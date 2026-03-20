#!/usr/bin/env bash
# Description: Deploys separate VPC and WAF webhook forwarder Lambdas and wires subscription filters.
# Description: Each Lambda gets its own CloudFormation stack with isolated concurrency to prevent starvation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

# Validate required variables
MISSING=0
for VAR in LM_COMPANY LM_BEARER_TOKEN; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo "[ERROR] Missing required environment variables."
    exit 1
fi

REGION="${AWS_DEFAULT_REGION:-us-west-2}"
CF_TEMPLATE="$PROJECT_ROOT/lambda/webhook-forwarder/cloudformation.yaml"
HANDLER_PY="$PROJECT_ROOT/lambda/webhook-forwarder/handler.py"

# Lambda configurations: name, stack, log group, concurrency, statement ID
VPC_FUNCTION="WebhookForwarderVPC"
VPC_STACK="webhook-forwarder-vpc"
VPC_LOG_GROUP="/aws/vpc/flowlogs"
VPC_CONCURRENCY=5
VPC_STATEMENT_ID="AllowCWLogsVPC"

WAF_FUNCTION="WebhookForwarderWAF"
WAF_STACK="webhook-forwarder-waf"
WAF_LOG_GROUP="aws-waf-logs"
WAF_CONCURRENCY=1
WAF_STATEMENT_ID="AllowCWLogsWAF"

FILTER_NAME="WebhookForwarder"

# ============================================================
# Helper: deploy a single CloudFormation stack + Lambda code
# ============================================================
deploy_stack() {
    local STACK_NAME="$1"
    local FUNCTION_NAME="$2"
    local CONCURRENCY="$3"

    echo ""
    echo "--- Deploying stack: $STACK_NAME (function: $FUNCTION_NAME, concurrency: $CONCURRENCY) ---"

    PARAMS_FILE=$(mktemp)
    trap "rm -f $PARAMS_FILE" RETURN
    cat > "$PARAMS_FILE" <<PARAMS_EOF
[
  {"ParameterKey": "FunctionName", "ParameterValue": "$FUNCTION_NAME"},
  {"ParameterKey": "LMPortalName", "ParameterValue": "$LM_COMPANY"},
  {"ParameterKey": "LMBearerToken", "ParameterValue": "$LM_BEARER_TOKEN"},
  {"ParameterKey": "LogLevel", "ParameterValue": "INFO"},
  {"ParameterKey": "SendDelay", "ParameterValue": "0.25"},
  {"ParameterKey": "ReservedConcurrency", "ParameterValue": "$CONCURRENCY"},
  {"ParameterKey": "TimeoutSeconds", "ParameterValue": "300"}
]
PARAMS_EOF

    STACK_STATUS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "DOES_NOT_EXIST")

    if [ "$STACK_STATUS" = "CREATE_COMPLETE" ] || [ "$STACK_STATUS" = "UPDATE_COMPLETE" ]; then
        echo "  Stack exists (status: $STACK_STATUS), updating..."
        if aws cloudformation update-stack \
            --stack-name "$STACK_NAME" \
            --template-body "file://$CF_TEMPLATE" \
            --capabilities CAPABILITY_NAMED_IAM \
            --parameters "file://$PARAMS_FILE" \
            --region "$REGION" 2>/dev/null; then
            echo "  Waiting for update..."
            aws cloudformation wait stack-update-complete \
                --stack-name "$STACK_NAME" \
                --region "$REGION"
            echo "  [OK] Stack updated"
        else
            echo "  [OK] No updates needed"
        fi

    elif [ "$STACK_STATUS" = "DOES_NOT_EXIST" ]; then
        echo "  Creating stack..."
        aws cloudformation create-stack \
            --stack-name "$STACK_NAME" \
            --template-body "file://$CF_TEMPLATE" \
            --capabilities CAPABILITY_NAMED_IAM \
            --parameters "file://$PARAMS_FILE" \
            --region "$REGION"
        echo "  Waiting for creation..."
        aws cloudformation wait stack-create-complete \
            --stack-name "$STACK_NAME" \
            --region "$REGION"
        echo "  [OK] Stack created"

    elif [ "$STACK_STATUS" = "ROLLBACK_COMPLETE" ]; then
        echo "  [WARN] Stack in ROLLBACK_COMPLETE. Deleting and retrying..."
        aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
        echo "  Deleted. Re-run this script to create fresh."
        return 1
    else
        echo "  [WARN] Stack in unexpected state: $STACK_STATUS"
        echo "  Run: aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
        return 1
    fi

    # Deploy handler.py as index.py via zip upload
    echo "  Deploying handler code..."
    local ZIP_FILE=$(mktemp /tmp/lambda-XXXXXX.zip)
    cp "$HANDLER_PY" /tmp/index.py
    cd /tmp && zip -j "$ZIP_FILE" index.py > /dev/null && rm -f index.py
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" \
        --query '{CodeSize:CodeSize,LastModified:LastModified}' \
        --output table
    rm -f "$ZIP_FILE"
    echo "  [OK] Code deployed"
}

# ============================================================
# Helper: wire a subscription filter from a log group to a Lambda
# ============================================================
wire_subscription() {
    local FUNCTION_NAME="$1"
    local LOG_GROUP="$2"
    local STATEMENT_ID="$3"

    echo ""
    echo "--- Wiring $LOG_GROUP -> $FUNCTION_NAME ---"

    # Check if log group exists
    if ! aws logs describe-log-groups \
        --log-group-name-prefix "$LOG_GROUP" \
        --region "$REGION" \
        --query "logGroups[?logGroupName=='$LOG_GROUP'].logGroupName" \
        --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
        echo "  [SKIP] Log group $LOG_GROUP does not exist"
        return 0
    fi

    local LAMBDA_ARN
    LAMBDA_ARN=$(aws lambda get-function \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --query 'Configuration.FunctionArn' \
        --output text)

    local ACCOUNT_ID
    ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
    local SOURCE_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP}:*"

    # Add Lambda invoke permission for CloudWatch Logs
    if aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --statement-id "$STATEMENT_ID" \
        --action "lambda:InvokeFunction" \
        --principal "logs.amazonaws.com" \
        --source-arn "$SOURCE_ARN" \
        --region "$REGION" > /dev/null 2>&1; then
        echo "  [OK] Lambda permission added"
    else
        echo "  [OK] Lambda permission already exists"
    fi

    # Remove old subscription filters (from previous single-Lambda setup)
    aws logs delete-subscription-filter \
        --log-group-name "$LOG_GROUP" \
        --filter-name "LMLogsForwarder" \
        --region "$REGION" 2>/dev/null || true

    aws logs delete-subscription-filter \
        --log-group-name "$LOG_GROUP" \
        --filter-name "WebhookForwarder" \
        --region "$REGION" 2>/dev/null || true

    # Create subscription filter
    aws logs put-subscription-filter \
        --log-group-name "$LOG_GROUP" \
        --filter-name "$FILTER_NAME" \
        --filter-pattern "" \
        --destination-arn "$LAMBDA_ARN" \
        --region "$REGION"
    echo "  [OK] Subscription filter created"
}

# ============================================================
# Main deployment
# ============================================================
echo "=== Deploying Webhook Forwarders ==="
echo "Region:    $REGION"
echo "Portal:    $LM_COMPANY"
echo "Template:  $CF_TEMPLATE"
echo ""
echo "VPC Lambda: $VPC_FUNCTION (concurrency=$VPC_CONCURRENCY)"
echo "WAF Lambda: $WAF_FUNCTION (concurrency=$WAF_CONCURRENCY)"

# Step 1: Deploy both stacks
echo ""
echo "========== STEP 1: Deploy CloudFormation Stacks =========="
deploy_stack "$VPC_STACK" "$VPC_FUNCTION" "$VPC_CONCURRENCY"
deploy_stack "$WAF_STACK" "$WAF_FUNCTION" "$WAF_CONCURRENCY"

# Step 2: Wire subscription filters
echo ""
echo "========== STEP 2: Wire Subscription Filters =========="
wire_subscription "$VPC_FUNCTION" "$VPC_LOG_GROUP" "$VPC_STATEMENT_ID"
wire_subscription "$WAF_FUNCTION" "$WAF_LOG_GROUP" "$WAF_STATEMENT_ID"

# Step 3: Clean up old single-Lambda stack if it exists
echo ""
echo "========== STEP 3: Clean Up Old Stack =========="
OLD_STACK="webhook-forwarder"
OLD_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$OLD_STACK" \
    --region "$REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "DOES_NOT_EXIST")

if [ "$OLD_STATUS" != "DOES_NOT_EXIST" ]; then
    echo "  Old stack '$OLD_STACK' exists (status: $OLD_STATUS). Deleting..."
    aws cloudformation delete-stack --stack-name "$OLD_STACK" --region "$REGION"
    echo "  [OK] Old stack deletion initiated"
else
    echo "  [OK] No old stack to clean up"
fi

# Step 4: Verify
echo ""
echo "========== STEP 4: Verify Deployment =========="
for FUNC in "$VPC_FUNCTION" "$WAF_FUNCTION"; do
    echo ""
    echo "  $FUNC:"
    aws lambda get-function \
        --function-name "$FUNC" \
        --region "$REGION" \
        --query 'Configuration.{State:State,Timeout:Timeout,Memory:MemorySize,Concurrency:RevisionId}' \
        --output table 2>/dev/null || echo "    (not found)"
done

echo ""
echo "  Subscription filters:"
for LG in "$VPC_LOG_GROUP" "$WAF_LOG_GROUP"; do
    echo "    $LG:"
    aws logs describe-subscription-filters \
        --log-group-name "$LG" \
        --region "$REGION" \
        --query 'subscriptionFilters[*].{Name:filterName,Dest:destinationArn}' \
        --output table 2>/dev/null || echo "      (no filters or log group does not exist)"
done

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "VPC Flow Logs: CloudWatch ($VPC_LOG_GROUP) -> $VPC_FUNCTION -> webhook (vpc_flow_logs) -> LM Logs"
echo "WAF Logs:      CloudWatch ($WAF_LOG_GROUP) -> $WAF_FUNCTION -> webhook (waf_logs) -> LM Logs"
echo ""
echo "NEXT STEPS:"
echo "  1. Verify VPC logs in LM Logs portal"
echo "  2. Generate WAF traffic and verify WAF logs in LM Logs portal"
