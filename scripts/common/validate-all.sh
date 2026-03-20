#!/usr/bin/env bash
# Description: Runs all environment validation scripts and reports aggregate status.
# Description: Executes LM, Azure, and AWS validators, summarizing pass/fail results.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS=0
FAIL=0
RESULTS=()

run_validator() {
    local name="$1"
    local script="$2"

    echo ""
    echo "────────────────────────────────────────"
    if bash "$script"; then
        RESULTS+=("[PASS] $name")
        PASS=$((PASS + 1))
    else
        RESULTS+=("[FAIL] $name")
        FAIL=$((FAIL + 1))
    fi
}

echo "Running all environment validations..."

run_validator "LogicMonitor" "$SCRIPT_DIR/validate-lm.sh"
run_validator "Azure"        "$SCRIPT_DIR/../azure/validate-azure.sh"
run_validator "AWS"           "$SCRIPT_DIR/../aws/validate-aws.sh"

echo ""
echo "════════════════════════════════════════"
echo "         VALIDATION SUMMARY"
echo "════════════════════════════════════════"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "  Passed: $PASS / $((PASS + FAIL))"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  Some validations FAILED. Fix issues above before proceeding."
    exit 1
else
    echo ""
    echo "  All validations PASSED."
    exit 0
fi
