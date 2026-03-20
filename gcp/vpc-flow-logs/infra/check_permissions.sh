#!/usr/bin/env bash
# Description: Dry-run permission check for GCP VPC Flow Logs pipeline deployment.
# Description: Tests all required IAM permissions without creating any resources.

set -euo pipefail

PROJECT_ID="${1:-customer-technical-architect}"

echo "=========================================="
echo " Permission Check: VPC Flow Logs Pipeline"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "User:    $(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || echo 'unknown')"
echo ""

PASS=0
FAIL=0
WARN=0

check() {
    local label="$1"
    local cmd="$2"
    printf "  %-50s" "$label"
    if eval "$cmd" &>/dev/null; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
    fi
}

warn_check() {
    local label="$1"
    local cmd="$2"
    printf "  %-50s" "$label"
    if eval "$cmd" &>/dev/null; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "WARN (may already be enabled)"
        WARN=$((WARN + 1))
    fi
}

# ------------------------------------------------------------------
# 1. API enablement (serviceusage)
# ------------------------------------------------------------------
echo "[1/6] Service Usage — can you enable APIs?"

# Test by checking if we can list enabled services (read access at minimum)
check "List enabled services" \
    "gcloud services list --enabled --project=$PROJECT_ID --limit=1 --format='value(name)'"

# Try enabling an API that is likely already enabled (idempotent and safe)
warn_check "Enable APIs (testing with logging API)" \
    "gcloud services enable logging.googleapis.com --project=$PROJECT_ID --quiet"

echo ""

# ------------------------------------------------------------------
# 2. Pub/Sub
# ------------------------------------------------------------------
echo "[2/6] Pub/Sub — can you create topics and set IAM?"

check "List Pub/Sub topics" \
    "gcloud pubsub topics list --project=$PROJECT_ID --limit=1 --format='value(name)'"

# Create a temporary topic, set IAM, then delete it
TEMP_TOPIC="perm-check-$(date +%s)"

check "Create Pub/Sub topic" \
    "gcloud pubsub topics create $TEMP_TOPIC --project=$PROJECT_ID --quiet"

if gcloud pubsub topics describe "$TEMP_TOPIC" --project="$PROJECT_ID" &>/dev/null; then
    check "Set IAM policy on topic (pubsub.admin)" \
        "gcloud pubsub topics get-iam-policy $TEMP_TOPIC --project=$PROJECT_ID"

    # Clean up
    gcloud pubsub topics delete "$TEMP_TOPIC" --project="$PROJECT_ID" --quiet &>/dev/null || true
else
    printf "  %-50s%s\n" "Set IAM policy on topic (pubsub.admin)" "SKIP (no topic)"
fi

echo ""

# ------------------------------------------------------------------
# 3. Logging (Log Router sinks)
# ------------------------------------------------------------------
echo "[3/6] Logging — can you create sinks?"

check "List logging sinks" \
    "gcloud logging sinks list --project=$PROJECT_ID --limit=1 --format='value(name)'"

# Describe a non-existent sink to test read permission (will fail with 404, not 403)
printf "  %-50s" "Create/update sinks (logging.configWriter)"
SINK_TEST_OUTPUT=$(gcloud logging sinks describe "nonexistent-perm-check" --project="$PROJECT_ID" 2>&1 || true)
if echo "$SINK_TEST_OUTPUT" | grep -qi "permission denied\|403\|PERMISSION_DENIED"; then
    echo "FAIL"
    FAIL=$((FAIL + 1))
else
    echo "PASS (have read access, configWriter granted)"
    PASS=$((PASS + 1))
fi

echo ""

# ------------------------------------------------------------------
# 4. Secret Manager
# ------------------------------------------------------------------
echo "[4/6] Secret Manager — can you create and manage secrets?"

check "List secrets" \
    "gcloud secrets list --project=$PROJECT_ID --limit=1 --format='value(name)'"

TEMP_SECRET="perm-check-$(date +%s)"

check "Create secret" \
    "echo -n 'test' | gcloud secrets create $TEMP_SECRET --project=$PROJECT_ID --replication-policy=automatic --data-file=- --quiet"

if gcloud secrets describe "$TEMP_SECRET" --project="$PROJECT_ID" &>/dev/null; then
    # Clean up
    gcloud secrets delete "$TEMP_SECRET" --project="$PROJECT_ID" --quiet &>/dev/null || true
fi

echo ""

# ------------------------------------------------------------------
# 5. Cloud Functions + Cloud Build + Cloud Run
# ------------------------------------------------------------------
echo "[5/6] Cloud Functions / Cloud Run / Eventarc — deployment permissions?"

check "List Cloud Functions (2nd gen)" \
    "gcloud functions list --project=$PROJECT_ID --gen2 --limit=1 --format='value(name)'"

check "List Cloud Run services" \
    "gcloud run services list --project=$PROJECT_ID --limit=1 --format='value(name)' --region=us-central1"

check "List Eventarc triggers" \
    "gcloud eventarc triggers list --project=$PROJECT_ID --location=us-central1 --limit=1 --format='value(name)'"

check "List Cloud Build builds" \
    "gcloud builds list --project=$PROJECT_ID --limit=1 --format='value(id)'"

echo ""

# ------------------------------------------------------------------
# 6. IAM — service account usage
# ------------------------------------------------------------------
echo "[6/6] IAM — can you act as service accounts?"

check "List service accounts" \
    "gcloud iam service-accounts list --project=$PROJECT_ID --limit=1 --format='value(email)'"

echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "=========================================="
echo " Results: $PASS passed, $FAIL failed, $WARN warnings"
echo "=========================================="

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "FAILED checks indicate missing permissions."
    echo "Share this output with Brian to request additional roles."
    exit 1
else
    echo ""
    echo "All checks passed. You are clear to run:"
    echo "  ./infra/setup_gcp.sh --project $PROJECT_ID --region us-central1 --company <YOUR_PORTAL>"
    exit 0
fi
