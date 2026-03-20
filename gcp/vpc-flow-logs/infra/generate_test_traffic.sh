#!/usr/bin/env bash
# Description: Generates network traffic to produce VPC Flow Log entries for testing.
# Description: Sends HTTP, HTTPS, SSH, and DNS traffic to a target IP within the VPC.

set -euo pipefail

# ------------------------------------------------------------------
# Usage and parameter validation
# ------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") --target TARGET_IP [OPTIONS]

Required:
  --target    IP address of a VM within the VPC that has flow logs enabled

Options:
  --burst     Number of rapid HTTP requests to generate volume (default: 50)
  --ports     Comma-separated list of additional ports to probe (e.g., 8080,3306)
  --project   GCP project ID (for log verification commands)
  --help      Show this help message

This script must be run from a VM within the same VPC (or a peered VPC)
to generate internal flow log entries. External traffic will also produce
flow logs if the target VM has a public IP.

Example:
  $(basename "$0") --target 10.128.0.5 --burst 100 --project my-gcp-project
EOF
    exit 1
}

# Defaults
TARGET_IP=""
BURST_COUNT=50
EXTRA_PORTS=""
PROJECT_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)   TARGET_IP="$2";     shift 2 ;;
        --burst)    BURST_COUNT="$2";   shift 2 ;;
        --ports)    EXTRA_PORTS="$2";   shift 2 ;;
        --project)  PROJECT_ID="$2";    shift 2 ;;
        --help)     usage ;;
        *)          echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$TARGET_IP" ]]; then
    echo "Error: --target is required."
    usage
fi

echo "=========================================="
echo " VPC Flow Log Traffic Generator"
echo "=========================================="
echo "Target:     $TARGET_IP"
echo "Burst size: $BURST_COUNT"
echo ""

TOTAL_REQUESTS=0
FAILED_REQUESTS=0

# Helper: run a command and count success/failure
run_probe() {
    local label="$1"
    shift
    TOTAL_REQUESTS=$((TOTAL_REQUESTS + 1))
    if "$@" &>/dev/null; then
        echo "  [OK]   $label"
    else
        echo "  [FAIL] $label (expected for closed/filtered ports)"
        FAILED_REQUESTS=$((FAILED_REQUESTS + 1))
    fi
}

# ------------------------------------------------------------------
# Step 1: HTTP traffic (port 80)
# ------------------------------------------------------------------

echo "[1/6] HTTP traffic (port 80)..."
run_probe "GET http://$TARGET_IP/" \
    curl -s -o /dev/null -w "" --connect-timeout 5 --max-time 10 "http://$TARGET_IP/"
echo ""

# ------------------------------------------------------------------
# Step 2: HTTPS traffic (port 443)
# ------------------------------------------------------------------

echo "[2/6] HTTPS traffic (port 443)..."
# Using --insecure since the target may not have a valid certificate
run_probe "GET https://$TARGET_IP/" \
    curl -sk -o /dev/null -w "" --connect-timeout 5 --max-time 10 "https://$TARGET_IP/"
echo ""

# ------------------------------------------------------------------
# Step 3: SSH probe (port 22)
# ------------------------------------------------------------------

echo "[3/6] SSH probe (port 22)..."
# Use bash /dev/tcp to attempt a TCP connection without needing nc/ncat
run_probe "TCP connect $TARGET_IP:22" \
    bash -c "echo > /dev/tcp/$TARGET_IP/22" 2>/dev/null || true
echo ""

# ------------------------------------------------------------------
# Step 4: DNS probe (port 53)
# ------------------------------------------------------------------

echo "[4/6] DNS probe (port 53)..."
if command -v dig &>/dev/null; then
    run_probe "DNS query @$TARGET_IP" \
        dig +short +time=3 +tries=1 "@$TARGET_IP" example.com A
elif command -v nslookup &>/dev/null; then
    run_probe "DNS query @$TARGET_IP" \
        nslookup -timeout=3 example.com "$TARGET_IP"
else
    echo "  [SKIP] Neither dig nor nslookup available"
fi
echo ""

# ------------------------------------------------------------------
# Step 5: Additional port probes
# ------------------------------------------------------------------

if [[ -n "$EXTRA_PORTS" ]]; then
    echo "[5/6] Additional port probes..."
    IFS=',' read -ra PORTS <<< "$EXTRA_PORTS"
    for port in "${PORTS[@]}"; do
        run_probe "TCP connect $TARGET_IP:$port" \
            bash -c "echo > /dev/tcp/$TARGET_IP/$port" 2>/dev/null || true
    done
    echo ""
else
    echo "[5/6] No additional ports specified, skipping."
    echo ""
fi

# ------------------------------------------------------------------
# Step 6: Burst traffic (rapid HTTP requests)
# ------------------------------------------------------------------

echo "[6/6] Burst traffic: $BURST_COUNT rapid HTTP requests..."
for i in $(seq 1 "$BURST_COUNT"); do
    curl -s -o /dev/null --connect-timeout 3 --max-time 5 "http://$TARGET_IP/" &>/dev/null || true
    TOTAL_REQUESTS=$((TOTAL_REQUESTS + 1))
    # Print progress every 10 requests
    if (( i % 10 == 0 )); then
        echo "  Sent $i/$BURST_COUNT"
    fi
done
echo "  Burst complete."
echo ""

# ------------------------------------------------------------------
# Summary and verification
# ------------------------------------------------------------------

echo "=========================================="
echo " Traffic Generation Summary"
echo "=========================================="
echo "Total requests:  $TOTAL_REQUESTS"
echo "Failed probes:   $FAILED_REQUESTS (expected for closed ports)"
echo ""
echo "VPC Flow Logs are aggregated over the configured interval (default 5 min)."
echo "Wait at least 5-10 minutes before checking for flow log entries."
echo ""
echo "=========================================="
echo " Verification Steps"
echo "=========================================="
echo ""
echo "1. Check Cloud Logging for flow log entries:"
echo ""
echo "   gcloud logging read \\"
echo "     'resource.type=\"gce_subnetwork\" log_id(\"compute.googleapis.com/vpc_flows\")' \\"
if [[ -n "$PROJECT_ID" ]]; then
echo "     --project=$PROJECT_ID \\"
fi
echo "     --limit=10 \\"
echo "     --format=json"
echo ""
echo "2. In the GCP Console, open Log Explorer and use this query:"
echo ""
echo "   resource.type=\"gce_subnetwork\""
echo "   log_id(\"compute.googleapis.com/vpc_flows\")"
echo "   jsonPayload.connection.dest_ip=\"$TARGET_IP\""
echo ""
echo "3. To filter for just the burst traffic (HTTP port 80):"
echo ""
echo "   resource.type=\"gce_subnetwork\""
echo "   log_id(\"compute.googleapis.com/vpc_flows\")"
echo "   jsonPayload.connection.dest_ip=\"$TARGET_IP\""
echo "   jsonPayload.connection.dest_port=80"
echo ""
echo "4. Check if the Cloud Function processed any messages:"
echo ""
if [[ -n "$PROJECT_ID" ]]; then
echo "   gcloud functions logs read vpc-flowlogs-to-lm \\"
echo "     --project=$PROJECT_ID \\"
echo "     --region=us-central1 \\"
echo "     --gen2 --limit=20"
else
echo "   gcloud functions logs read vpc-flowlogs-to-lm --gen2 --limit=20"
fi
echo ""
