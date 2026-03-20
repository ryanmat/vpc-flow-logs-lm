# Description: Parses Azure VNet flow log tuples and constructs LM Logs Ingest API payloads.
# Description: Handles the 13-field comma-separated format from PT1H.json flow log blobs.

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# VNet flow log tuple field names in positional order (version 4, 13 fields).
# Each PT1H.json blob contains records with flowTuples as comma-separated strings.
FLOW_TUPLE_FIELDS = [
    "timestamp_epoch_ms",
    "srcIP",
    "dstIP",
    "srcPort",
    "dstPort",
    "protocol",
    "direction",
    "flowState",
    "encryption",
    "pktsSrcDst",
    "bytesSrcDst",
    "pktsDstSrc",
    "bytesDstSrc",
]

PROTOCOL_MAP = {
    "1": "ICMP",
    "6": "TCP",
    "17": "UDP",
}

FLOW_STATE_MAP = {
    "B": "begin",
    "C": "continue",
    "E": "end",
    "D": "deny",
}

DIRECTION_MAP = {
    "I": "inbound",
    "O": "outbound",
}


def protocol_name(proto_num):
    """Convert IANA protocol number string to human-readable name."""
    return PROTOCOL_MAP.get(proto_num, proto_num)


def flow_state_label(state_code):
    """Convert flow state code (B/C/E/D) to human-readable label."""
    return FLOW_STATE_MAP.get(state_code, state_code)


def direction_label(dir_code):
    """Convert direction code (I/O) to human-readable label."""
    return DIRECTION_MAP.get(dir_code, dir_code)


def parse_flow_tuple(tuple_str):
    """Parse a single comma-separated VNet flow tuple into a dict.

    Returns None if the tuple is malformed or has fewer than 13 fields.
    """
    if not tuple_str or not tuple_str.strip():
        return None

    parts = tuple_str.strip().split(",")
    if len(parts) < len(FLOW_TUPLE_FIELDS):
        logger.warning("Malformed flow tuple with %d fields (expected %d): %s",
                        len(parts), len(FLOW_TUPLE_FIELDS), tuple_str[:80])
        return None

    return {field: parts[i] for i, field in enumerate(FLOW_TUPLE_FIELDS)}


def build_msg_string(parsed):
    """Build a human-readable log message string from parsed tuple fields.

    Format: "{ALLOW|DENY} {PROTO} {srcIP}:{srcPort} > {dstIP}:{dstPort} {dir} {bytesOut}B/{bytesIn}B"
    """
    state = parsed.get("flowState", "")
    action = "DENY" if state == "D" else "ALLOW"
    proto = protocol_name(parsed.get("protocol", ""))
    src = f"{parsed.get('srcIP', '')}:{parsed.get('srcPort', '')}"
    dst = f"{parsed.get('dstIP', '')}:{parsed.get('dstPort', '')}"
    direction = direction_label(parsed.get("direction", ""))
    bytes_out = parsed.get("bytesSrcDst", "0")
    bytes_in = parsed.get("bytesDstSrc", "0")

    return f"{action} {proto} {src} > {dst} {direction} {bytes_out}B/{bytes_in}B"


def _build_resource_id(vnet_resource_id, device_display_name=""):
    """Build the _lm.resourceId mapping dict.

    LM tries each key in order until one matches a device property.
    system.displayname is the most reliable for manually-created devices.
    azure.resourceid is included as a fallback for cloud-discovered devices.
    """
    resource_id = {}
    if device_display_name:
        resource_id["system.displayname"] = device_display_name
    resource_id["azure.resourceid"] = vnet_resource_id
    return resource_id


def build_lm_log_entry(parsed, vnet_resource_id, device_display_name="", mac_address="", rule=""):
    """Build a single LM Logs Ingest API entry from a parsed flow tuple.

    The entry includes the structured msg, _lm.resourceId for device mapping,
    a timestamp in ISO 8601, and all flow fields as top-level metadata keys.
    """
    msg = build_msg_string(parsed)

    # Convert epoch milliseconds to ISO 8601 UTC
    try:
        epoch_ms = int(parsed["timestamp_epoch_ms"])
        ts = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        timestamp_iso = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    except (ValueError, KeyError, OSError):
        timestamp_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    state = parsed.get("flowState", "")
    level = "warn" if state == "D" else "info"

    entry = {
        "msg": msg,
        "_lm.resourceId": _build_resource_id(vnet_resource_id, device_display_name),
        "timestamp": timestamp_iso,
        "Level": level,
        "srcIP": parsed.get("srcIP", ""),
        "dstIP": parsed.get("dstIP", ""),
        "srcPort": parsed.get("srcPort", ""),
        "dstPort": parsed.get("dstPort", ""),
        "protocol": protocol_name(parsed.get("protocol", "")),
        "direction": direction_label(parsed.get("direction", "")),
        "flowState": flow_state_label(parsed.get("flowState", "")),
        "encryption": parsed.get("encryption", ""),
        "pktsSrcDst": parsed.get("pktsSrcDst", "0"),
        "bytesSrcDst": parsed.get("bytesSrcDst", "0"),
        "pktsDstSrc": parsed.get("pktsDstSrc", "0"),
        "bytesDstSrc": parsed.get("bytesDstSrc", "0"),
        "resourceType": "Azure VNet Flow Logs",
        "source_type": "vnet_flow_logs",
    }

    if mac_address:
        entry["macAddress"] = mac_address
    if rule:
        entry["rule"] = rule

    return entry


def assemble_batches(entries, max_bytes=7340032):
    """Split a list of LM log entries into batches that fit under the size limit.

    Each batch is a list of entries whose combined JSON serialization is under
    max_bytes. A single entry that exceeds max_bytes still gets its own batch
    to avoid data loss.
    """
    if not entries:
        return []

    batches = []
    current_batch = []
    current_size = 2  # Account for the JSON array brackets []

    for entry in entries:
        entry_json = json.dumps(entry).encode("utf-8")
        entry_size = len(entry_json) + 1  # +1 for comma separator

        if current_batch and (current_size + entry_size) > max_bytes:
            batches.append(current_batch)
            current_batch = []
            current_size = 2

        current_batch.append(entry)
        current_size += entry_size

    if current_batch:
        batches.append(current_batch)

    return batches


def parse_flow_records_from_json(data, vnet_resource_id, device_display_name=""):
    """Parse the full PT1H.json structure into a flat list of LM log entries.

    Walks the nested records -> flows -> flowGroups -> flowTuples hierarchy
    and produces one LM log entry per flow tuple.
    """
    entries = []
    records = data.get("records", [])

    for record in records:
        mac_address = record.get("macAddress", "")
        # Use targetResourceID from the blob if available, fall back to parameter
        target_id = record.get("targetResourceID", vnet_resource_id)

        flow_records = record.get("flowRecords", {})
        flows = flow_records.get("flows", [])

        for flow in flows:
            flow_groups = flow.get("flowGroups", [])
            for group in flow_groups:
                rule = group.get("rule", "")
                tuples = group.get("flowTuples", [])
                for tuple_str in tuples:
                    parsed = parse_flow_tuple(tuple_str)
                    if parsed is None:
                        continue
                    entry = build_lm_log_entry(
                        parsed,
                        vnet_resource_id=target_id,
                        device_display_name=device_display_name,
                        mac_address=mac_address,
                        rule=rule,
                    )
                    entries.append(entry)

    return entries
