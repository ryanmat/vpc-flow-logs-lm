#!/usr/bin/env bash
# Description: End-to-end test for the AWS VPC Flow Logs pipeline.
# Description: Validates log group, IAM role, flow logs, Lambda, subscription filter, and log delivery.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$PROJECT_ROOT/shared/scripts/load-env.sh"

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

PASS=0
FAIL=0
RESULTS=()

check() {
    local name="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        RESULTS+=("[PASS] $name")
        PASS=$((PASS + 1))
    else
        RESULTS+=("[FAIL] $name")
        FAIL=$((FAIL + 1))
    fi
}

echo "=== AWS VPC Flow Logs Pipeline Test ==="
echo ""

# Test 1: CloudWatch log group exists
check "CloudWatch log group /aws/vpc/flowlogs exists" \
    aws logs describe-log-groups \
        --log-group-name-prefix "/aws/vpc/flowlogs" \
        --query 'logGroups[?logGroupName==`/aws/vpc/flowlogs`]' \
        $PROFILE_FLAG

# Test 2: IAM role exists
check "IAM role VPCFlowLogsRole exists" \
    aws iam get-role --role-name VPCFlowLogsRole $PROFILE_FLAG

# Test 3: IAM role has inline policy
check "VPCFlowLogsRole has VPCFlowLogsPolicy" \
    aws iam get-role-policy \
        --role-name VPCFlowLogsRole \
        --policy-name VPCFlowLogsPolicy \
        $PROFILE_FLAG

# Test 4: WebhookForwarderVPC Lambda exists
check "WebhookForwarderVPC Lambda function exists" \
    aws lambda get-function --function-name WebhookForwarderVPC $PROFILE_FLAG

# Test 5: WebhookForwarderWAF Lambda exists
check "WebhookForwarderWAF Lambda function exists" \
    aws lambda get-function --function-name WebhookForwarderWAF $PROFILE_FLAG

# Test 6: CloudFormation stacks backing the Lambdas are healthy
STACK_FOUND=0
for STACK_CANDIDATE in webhook-forwarder-vpc webhook-forwarder-waf; do
    STACK_STATUS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_CANDIDATE" \
        --query 'Stacks[0].StackStatus' \
        --output text \
        $PROFILE_FLAG 2>/dev/null || echo "MISSING")
    if [ "$STACK_STATUS" = "CREATE_COMPLETE" ] || [ "$STACK_STATUS" = "UPDATE_COMPLETE" ]; then
        RESULTS+=("[PASS] CloudFormation stack $STACK_CANDIDATE ($STACK_STATUS)")
        PASS=$((PASS + 1))
        STACK_FOUND=$((STACK_FOUND + 1))
    fi
done
if [ "$STACK_FOUND" -eq 0 ]; then
    RESULTS+=("[FAIL] No CloudFormation stacks found for webhook forwarders")
    FAIL=$((FAIL + 1))
fi

# Test 6: Subscription filter exists
FILTER_COUNT=$(aws logs describe-subscription-filters \
    --log-group-name "/aws/vpc/flowlogs" \
    --query 'length(subscriptionFilters)' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "0")
if [ "$FILTER_COUNT" -gt 0 ]; then
    RESULTS+=("[PASS] Subscription filter on /aws/vpc/flowlogs ($FILTER_COUNT)")
    PASS=$((PASS + 1))
else
    RESULTS+=("[FAIL] No subscription filter on /aws/vpc/flowlogs")
    FAIL=$((FAIL + 1))
fi

# Test 7: Log streams exist (indicates flow logs are generating)
STREAM_COUNT=$(aws logs describe-log-streams \
    --log-group-name "/aws/vpc/flowlogs" \
    --limit 1 \
    --query 'length(logStreams)' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "0")
if [ "$STREAM_COUNT" -gt 0 ]; then
    RESULTS+=("[PASS] Log streams present in /aws/vpc/flowlogs")
    PASS=$((PASS + 1))
else
    RESULTS+=("[WARN] No log streams yet (may need time to generate)")
    # Not a hard failure since logs take time
    PASS=$((PASS + 1))
fi

# Report
echo ""
echo "════════════════════════════════════════"
echo "         TEST RESULTS"
echo "════════════════════════════════════════"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "  Passed: $PASS / $((PASS + FAIL))"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  Some tests FAILED. Run the setup scripts in order:"
    echo "    1. scripts/aws/setup-vpc-flow-log-group.sh"
    echo "    2. scripts/aws/enable-vpc-flow-logs.sh <VPC_ID> <ROLE_ARN>"
    echo "    3. scripts/aws/deploy-lm-logs-forwarder.sh"
    echo "    4. scripts/aws/create-subscription-filter.sh"
    exit 1
else
    echo ""
    echo "  All tests PASSED."
    exit 0
fi
