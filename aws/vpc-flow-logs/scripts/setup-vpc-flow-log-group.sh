#!/usr/bin/env bash
# Description: Creates CloudWatch Log Group and IAM role for VPC Flow Logs.
# Description: Sets up /aws/vpc/flowlogs with 7-day retention and VPCFlowLogsRole.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

# Validate AWS environment
bash "$SCRIPT_DIR/validate-aws.sh"

PROFILE_FLAG=""
if [ -n "${AWS_PROFILE:-}" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

LOG_GROUP_NAME="/aws/vpc/flowlogs"
ROLE_NAME="VPCFlowLogsRole"
POLICY_NAME="VPCFlowLogsPolicy"

echo ""
echo "=== Setting up CloudWatch Log Group for VPC Flow Logs ==="

# Step 1: Create CloudWatch Log Group
echo ""
echo "[1/4] Creating CloudWatch Log Group: $LOG_GROUP_NAME"
if aws logs create-log-group \
    --log-group-name "$LOG_GROUP_NAME" \
    $PROFILE_FLAG 2>/dev/null; then
    echo "  [OK] Log group created"
else
    echo "  [OK] Log group already exists"
fi

# Step 2: Set retention policy to 7 days
echo "[2/4] Setting retention policy to 7 days"
aws logs put-retention-policy \
    --log-group-name "$LOG_GROUP_NAME" \
    --retention-in-days 7 \
    $PROFILE_FLAG
echo "  [OK] Retention set to 7 days"

# Step 3: Create IAM role with trust policy for VPC Flow Logs
echo "[3/4] Creating IAM role: $ROLE_NAME"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "vpc-flow-logs.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}'

if aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Allows VPC Flow Logs to publish to CloudWatch Logs" \
    $PROFILE_FLAG > /dev/null 2>&1; then
    echo "  [OK] Role created"
else
    echo "  [OK] Role already exists"
fi

# Step 4: Attach inline policy for CloudWatch Logs permissions
echo "[4/4] Attaching CloudWatch Logs permissions policy"

PERMISSIONS_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/vpc/flowlogs:*"
    }
  ]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$POLICY_NAME" \
    --policy-document "$PERMISSIONS_POLICY" \
    $PROFILE_FLAG
echo "  [OK] Policy attached"

# Output the role ARN
ROLE_ARN=$(aws iam get-role \
    --role-name "$ROLE_NAME" \
    --query 'Role.Arn' \
    --output text \
    $PROFILE_FLAG)

echo ""
echo "=== Setup Complete ==="
echo "Log Group:  $LOG_GROUP_NAME"
echo "Role Name:  $ROLE_NAME"
echo "Role ARN:   $ROLE_ARN"
echo ""
echo "Use this Role ARN in the next step (enable-vpc-flow-logs.sh)."
