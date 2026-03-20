#!/usr/bin/env bash
# Description: Enables VPC Flow Logs with a custom format for LogicMonitor ingestion.
# Description: Places instance-id as the first field for proper LM resource mapping.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

# Usage check
if [ $# -lt 2 ]; then
    echo "Usage: $0 <VPC_ID> <IAM_ROLE_ARN> [LOG_GROUP_NAME]"
    echo ""
    echo "  VPC_ID         The VPC to enable flow logs on (e.g. vpc-0abc123)"
    echo "  IAM_ROLE_ARN   The IAM role ARN from setup-vpc-flow-log-group.sh"
    echo "  LOG_GROUP_NAME Optional, defaults to /aws/vpc/flowlogs"
    exit 1
fi

VPC_ID="$1"
IAM_ROLE_ARN="$2"
LOG_GROUP_NAME="${3:-/aws/vpc/flowlogs}"

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

# Custom log format with instance-id as first field (required by LogicMonitor)
FLOW_LOG_FORMAT='${instance-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status}'

echo "=== Enabling VPC Flow Logs ==="
echo "VPC:        $VPC_ID"
echo "Role ARN:   $IAM_ROLE_ARN"
echo "Log Group:  $LOG_GROUP_NAME"
echo "Format:     $FLOW_LOG_FORMAT"
echo ""

# Create the flow log
echo "[1/2] Creating VPC Flow Log..."
CREATE_OUTPUT=$(aws ec2 create-flow-logs \
    --resource-type VPC \
    --resource-ids "$VPC_ID" \
    --traffic-type ALL \
    --log-destination-type cloud-watch-logs \
    --log-group-name "$LOG_GROUP_NAME" \
    --deliver-logs-permission-arn "$IAM_ROLE_ARN" \
    --log-format "$FLOW_LOG_FORMAT" \
    --output json \
    $PROFILE_FLAG)

FLOW_LOG_ID=$(echo "$CREATE_OUTPUT" | jq -r '.FlowLogIds[0] // empty')
UNSUCCESSFUL=$(echo "$CREATE_OUTPUT" | jq -r '.Unsuccessful[0].Error.Message // empty')

if [ -n "$FLOW_LOG_ID" ]; then
    echo "  [OK] Flow log created: $FLOW_LOG_ID"
elif [ -n "$UNSUCCESSFUL" ]; then
    echo "  [WARN] $UNSUCCESSFUL"
    echo "  Checking for existing flow logs on this VPC..."
    FLOW_LOG_ID=$(aws ec2 describe-flow-logs \
        --filter "Name=resource-id,Values=$VPC_ID" \
        --query 'FlowLogs[0].FlowLogId' \
        --output text \
        $PROFILE_FLAG)
    echo "  [OK] Existing flow log: $FLOW_LOG_ID"
else
    echo "  [FAIL] Unexpected response:"
    echo "$CREATE_OUTPUT"
    exit 1
fi

# Verify the flow log
echo "[2/2] Verifying flow log..."
aws ec2 describe-flow-logs \
    --filter "Name=resource-id,Values=$VPC_ID" \
    --query 'FlowLogs[*].{ID:FlowLogId,Status:FlowLogStatus,LogGroup:LogGroupName,Traffic:TrafficType}' \
    --output table \
    $PROFILE_FLAG

echo ""
echo "=== VPC Flow Logs Enabled ==="
echo "Flow Log ID: $FLOW_LOG_ID"
