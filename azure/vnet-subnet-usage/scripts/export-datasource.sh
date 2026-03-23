#!/usr/bin/env bash
# Description: Exports an Azure VNet IP Usage DataSource from LogicMonitor portal to JSON.
# Description: Fetches by name or ID, writes to stdout or a file for round-tripping.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../shared/scripts/load-env.sh"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <datasource_id_or_name> [output_file]"
    echo ""
    echo "  Exports a DataSource definition from LogicMonitor."
    echo ""
    echo "  Examples:"
    echo "    $0 11442088                              # by ID, print to stdout"
    echo "    $0 Azure_VNet_IPUsage output.json        # by name, write to file"
    exit 1
fi

DS_REF="$1"
OUTPUT_FILE="${2:-}"

for VAR in LM_COMPANY LM_BEARER_TOKEN; do
    if [ -z "${!VAR:-}" ]; then
        echo "[FAIL] $VAR is not set" >&2
        exit 1
    fi
done

AUTH_FILE=$(mktemp)
trap "rm -f $AUTH_FILE" EXIT
printf 'header = "Authorization: Bearer %s"\n' "$LM_BEARER_TOKEN" > "$AUTH_FILE"

# Determine if DS_REF is an ID (numeric) or name (string)
if [[ "$DS_REF" =~ ^[0-9]+$ ]]; then
    DS_ID="$DS_REF"
else
    # Look up by name
    LOOKUP=$(curl -s \
        -K "$AUTH_FILE" \
        -H "X-Version: 3" \
        "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/datasources?filter=name:%22${DS_REF}%22&size=1&fields=id,name")

    DS_ID=$(echo "$LOOKUP" | jq -r '.items[0]?.id // empty' 2>/dev/null)
    if [ -z "$DS_ID" ]; then
        echo "[FAIL] DataSource '${DS_REF}' not found in portal" >&2
        exit 1
    fi
    echo "Resolved '${DS_REF}' to ID: ${DS_ID}" >&2
fi

RESPONSE=$(curl -s \
    -K "$AUTH_FILE" \
    -H "X-Version: 3" \
    "https://${LM_COMPANY}.logicmonitor.com/santaba/rest/setting/datasources/${DS_ID}")

if ! echo "$RESPONSE" | jq -e '.id' > /dev/null 2>&1; then
    ERROR_MSG=$(echo "$RESPONSE" | jq -r '.errorMessage // "unknown error"' 2>/dev/null || echo "$RESPONSE")
    echo "[FAIL] Export failed: $ERROR_MSG" >&2
    exit 1
fi

if [ -n "$OUTPUT_FILE" ]; then
    echo "$RESPONSE" | jq '.' > "$OUTPUT_FILE"
    echo "[OK] Exported DataSource ${DS_ID} to ${OUTPUT_FILE}" >&2
else
    echo "$RESPONSE" | jq '.'
fi
