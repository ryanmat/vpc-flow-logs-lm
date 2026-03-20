#!/usr/bin/env bash
# Description: Queries LogicMonitor API for OOB AWS security DataSources (WAF, Shield, Network Firewall).
# Description: Generates a status report documenting what exists vs what needs custom building.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

# Validate LM credentials
for VAR in LM_COMPANY LM_ACCESS_ID LM_ACCESS_KEY; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set"
        exit 1
    fi
done

lm_api_get() {
    local endpoint="$1"
    local EPOCH
    EPOCH=$(date +%s%3N)
    local REQUEST_VARS="GET${EPOCH}${endpoint}"
    local SIGNATURE
    SIGNATURE=$(echo -n "$REQUEST_VARS" | openssl dgst -sha256 -hmac "$LM_ACCESS_KEY" -binary | base64)
    local AUTH="LMv1 ${LM_ACCESS_ID}:${SIGNATURE}:${EPOCH}"

    curl -s \
        -H "Authorization: $AUTH" \
        -H "Content-Type: application/json" \
        "https://${LM_COMPANY}.logicmonitor.com/santaba/rest${endpoint}"
}

echo "=== Verifying OOB AWS Security DataSources ==="
echo ""

REPORT_FILE="$SCRIPT_DIR/../../docs/aws-security-datasource-status.md"
mkdir -p "$(dirname "$REPORT_FILE")"

# Services and their search patterns (pipe-separated: service|pattern1,pattern2)
SERVICES="AWS WAF|WAF
AWS Shield|Shield
AWS Network Firewall|NetworkFirewall,Firewall"

FOUND_COUNT=0
MISSING_COUNT=0
FOUND_SERVICES=""
MISSING_SERVICES=""

# Begin building the report
REPORT="# AWS Security DataSource Status Report

Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')
Portal: ${LM_COMPANY}.logicmonitor.com

## Summary
"

while IFS='|' read -r SERVICE PATTERNS; do
    echo "Checking: $SERVICE"
    SERVICE_FOUND=0

    IFS=',' read -ra PATTERN_LIST <<< "$PATTERNS"
    for PATTERN in "${PATTERN_LIST[@]}"; do
        RESPONSE=$(lm_api_get "/setting/datasources?filter=name~\"${PATTERN}\"&size=100")
        TOTAL=$(echo "$RESPONSE" | jq -r '.total // 0')

        if [ "$TOTAL" -gt 0 ]; then
            SERVICE_FOUND=1
            echo "  [OK] Found $TOTAL DataSource(s) matching '$PATTERN'"
            echo "$RESPONSE" | jq -r '.items[] | "    - \(.name) (datapoints: \(.dataPoints | length), appliesTo: \(.appliesTo))"' 2>/dev/null || true
        fi
    done

    if [ "$SERVICE_FOUND" -eq 1 ]; then
        FOUND_COUNT=$((FOUND_COUNT + 1))
        REPORT="${REPORT}
- ${SERVICE}: OOB DataSource found"
    else
        MISSING_COUNT=$((MISSING_COUNT + 1))
        MISSING_SERVICES="${MISSING_SERVICES}${SERVICE}|"
        echo "  [MISS] No OOB DataSource found for $SERVICE"
        REPORT="${REPORT}
- ${SERVICE}: No OOB DataSource -- custom build required"
    fi
    echo ""
done <<< "$SERVICES"

REPORT="${REPORT}

## OOB DataSources Found: $FOUND_COUNT
## Custom DataSources Needed: $MISSING_COUNT
"

if [ "$MISSING_COUNT" -gt 0 ]; then
    REPORT="${REPORT}
## Required Custom DataSources
"
    if echo "$MISSING_SERVICES" | grep -q "AWS WAF"; then
        REPORT="${REPORT}
### AWS WAF (datasources/AWS_WAF_Custom.xml)
- Namespace: AWS/WAFV2
- Metrics: AllowedRequests, BlockedRequests, CountedRequests, PassedRequests
- AppliesTo: system.aws.resourcetype == \"wafv2-webacl\"
"
    fi
    if echo "$MISSING_SERVICES" | grep -q "AWS Shield"; then
        REPORT="${REPORT}
### AWS Shield Advanced (datasources/AWS_Shield_Custom.xml)
- Namespace: AWS/DDoSProtection
- Metrics: DDoSDetected, DDoSAttackBitsPerSecond, DDoSAttackPacketsPerSecond, DDoSAttackRequestsPerSecond
- AppliesTo: Shield Advanced subscription required
"
    fi
    if echo "$MISSING_SERVICES" | grep -q "AWS Network Firewall"; then
        REPORT="${REPORT}
### AWS Network Firewall (datasources/AWS_NetworkFirewall_Custom.xml)
- Namespace: AWS/NetworkFirewall
- Metrics: DroppedPackets, PassedPackets, ReceivedPackets
- AppliesTo: system.aws.resourcetype == \"network-firewall\"
"
    fi
fi

# Write the report
echo "$REPORT" > "$REPORT_FILE"

echo "════════════════════════════════════════"
echo "         DATASOURCE STATUS"
echo "════════════════════════════════════════"
echo ""
echo "  OOB Found:       $FOUND_COUNT"
echo "  Custom Needed:   $MISSING_COUNT"
echo ""
echo "  Report written to: docs/aws-security-datasource-status.md"
echo ""

if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "  Next steps: Build custom DataSources (Phase 2.3-2.5)"
fi
