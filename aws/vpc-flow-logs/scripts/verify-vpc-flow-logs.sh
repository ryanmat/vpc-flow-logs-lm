#!/usr/bin/env bash
# Description: Verifies VPC Flow Logs are flowing into LogicMonitor LM Logs.
# Description: Checks CloudWatch for log events and provides LM portal verification steps.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

WAIT_MINUTES="${1:-5}"
LOG_GROUP_NAME="${2:-/aws/vpc/flowlogs}"

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

echo "=== Verifying VPC Flow Logs Pipeline ==="
echo ""

# Step 1: Check CloudWatch log group has streams
echo "[1/3] Checking CloudWatch log streams..."
STREAM_COUNT=$(aws logs describe-log-streams \
    --log-group-name "$LOG_GROUP_NAME" \
    --order-by LastEventTime \
    --descending \
    --limit 5 \
    --query 'length(logStreams)' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "0")

if [ "$STREAM_COUNT" -gt 0 ]; then
    echo "  [OK] Found $STREAM_COUNT log stream(s) in $LOG_GROUP_NAME"
    echo "  Latest streams:"
    aws logs describe-log-streams \
        --log-group-name "$LOG_GROUP_NAME" \
        --order-by LastEventTime \
        --descending \
        --limit 3 \
        --query 'logStreams[*].{Name:logStreamName,LastEvent:lastEventTimestamp}' \
        --output table \
        $PROFILE_FLAG
else
    echo "  [WARN] No log streams found yet in $LOG_GROUP_NAME"
    echo "         Flow logs can take up to 10 minutes to appear after enabling."
fi

# Step 2: Check subscription filter is in place
echo ""
echo "[2/3] Checking subscription filter..."
FILTER_COUNT=$(aws logs describe-subscription-filters \
    --log-group-name "$LOG_GROUP_NAME" \
    --query 'length(subscriptionFilters)' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "0")

if [ "$FILTER_COUNT" -gt 0 ]; then
    echo "  [OK] Subscription filter active ($FILTER_COUNT filter(s))"
else
    echo "  [FAIL] No subscription filter found"
    echo "         Run create-subscription-filter.sh first"
fi

# Step 3: Check Lambda invocations (last 10 minutes)
echo ""
echo "[3/3] Checking LMLogsForwarder Lambda invocations..."
END_TIME=$(date +%s)
START_TIME=$((END_TIME - 600))

INVOCATIONS=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Invocations \
    --dimensions Name=FunctionName,Value=LMLogsForwarder \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --period 300 \
    --statistics Sum \
    --query 'Datapoints[0].Sum' \
    --output text \
    $PROFILE_FLAG 2>/dev/null || echo "None")

if [ "$INVOCATIONS" != "None" ] && [ "$INVOCATIONS" != "null" ]; then
    echo "  [OK] Lambda invoked $INVOCATIONS time(s) in the last 10 minutes"
else
    echo "  [INFO] No Lambda invocations detected in the last 10 minutes"
    echo "         This is normal if flow logs haven't started generating yet."
fi

# Summary and manual verification
echo ""
echo "════════════════════════════════════════"
echo "         VERIFICATION SUMMARY"
echo "════════════════════════════════════════"
echo ""
echo "CloudWatch Streams: $STREAM_COUNT"
echo "Subscription Filters: $FILTER_COUNT"
echo "Lambda Invocations (10m): $INVOCATIONS"
echo ""
echo "── Manual Verification in LogicMonitor ──"
echo ""
echo "1. Go to https://${LM_COMPANY:-your_company}.logicmonitor.com"
echo "2. Navigate to Logs > LM Logs"
echo "3. Search for logs containing VPC flow data"
echo "4. Verify resource mapping (instance-id should map to devices)"
echo ""
echo "If no logs appear after 15 minutes:"
echo "  - Check Lambda CloudWatch logs: /aws/lambda/LMLogsForwarder"
echo "  - Verify LM API credentials are correct"
echo "  - Confirm VPC has active network traffic"
