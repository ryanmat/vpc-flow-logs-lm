# Description: Parses and transforms GCP VPC Flow Log data from Pub/Sub CloudEvents.
# Description: Pure functions for extracting flow logs, resource IDs, and metadata.
from __future__ import annotations

import base64
import json


def parse_pubsub_message(cloud_event: dict) -> dict:
    """Extract and decode the Cloud Logging LogEntry from a Pub/Sub CloudEvent.

    The CloudEvent wraps a Pub/Sub message whose data field contains a
    base64-encoded JSON string of the full Cloud Logging LogEntry.

    Args:
        cloud_event: CloudEvent dict as delivered by Eventarc.

    Returns:
        Parsed LogEntry dict containing insertId, resource, jsonPayload, etc.

    Raises:
        ValueError: If the message is malformed or cannot be decoded.
    """
    data = cloud_event.get("data")
    if not data:
        raise ValueError("CloudEvent missing 'data' field")

    message = data.get("message")
    if not message:
        raise ValueError("CloudEvent missing 'data.message' field")

    encoded = message.get("data")
    if not encoded:
        raise ValueError("Pub/Sub message missing 'data' field")

    try:
        decoded_bytes = base64.b64decode(encoded)
    except Exception as e:
        raise ValueError(f"Failed to base64 decode Pub/Sub message data: {e}") from e

    try:
        log_entry = json.loads(decoded_bytes)
    except json.JSONDecodeError as e:
        raise ValueError(f"Decoded data is not valid JSON: {e}") from e

    return log_entry


def extract_flow_log(log_entry: dict) -> dict:
    """Extract the VPC Flow Log record from a Cloud Logging LogEntry.

    Args:
        log_entry: Parsed Cloud Logging LogEntry dict.

    Returns:
        The jsonPayload dict containing the flow log fields.

    Raises:
        ValueError: If jsonPayload is missing or empty.
    """
    json_payload = log_entry.get("jsonPayload")
    if json_payload is None:
        raise ValueError("LogEntry missing 'jsonPayload' field")
    if not json_payload:
        raise ValueError("LogEntry has empty 'jsonPayload'")
    return json_payload


def extract_resource_id(flow_log: dict) -> dict | None:
    """Extract the best LM resource ID mapping from a flow log.

    Priority order:
        1. src_instance.vm_name
        2. dest_instance.vm_name
        3. None (deviceless log)

    Args:
        flow_log: Parsed VPC Flow Log jsonPayload dict.

    Returns:
        Dict like {"system.hostname": "vm-name"} or None if no VM found.
    """
    src_instance = flow_log.get("src_instance", {})
    vm_name = src_instance.get("vm_name")
    if vm_name:
        return {"system.hostname": vm_name}

    dest_instance = flow_log.get("dest_instance", {})
    vm_name = dest_instance.get("vm_name")
    if vm_name:
        return {"system.hostname": vm_name}

    return None


def extract_metadata(flow_log: dict) -> dict:
    """Extract key metadata fields from a flow log for LM log enrichment.

    Handles missing nested fields gracefully, only including fields that
    are actually present in the flow log.

    Args:
        flow_log: Parsed VPC Flow Log jsonPayload dict.

    Returns:
        Flat dict of metadata key-value pairs.
    """
    metadata = {}

    # Connection fields
    connection = flow_log.get("connection", {})
    if connection:
        metadata["src_ip"] = connection.get("src_ip")
        metadata["dest_ip"] = connection.get("dest_ip")
        metadata["src_port"] = connection.get("src_port")
        metadata["dest_port"] = connection.get("dest_port")
        metadata["protocol"] = connection.get("protocol")

    # Traffic fields
    if "bytes_sent" in flow_log:
        metadata["bytes_sent"] = flow_log["bytes_sent"]
    if "packets_sent" in flow_log:
        metadata["packets_sent"] = flow_log["packets_sent"]
    if "reporter" in flow_log:
        metadata["reporter"] = flow_log["reporter"]

    # Source instance metadata
    src_instance = flow_log.get("src_instance", {})
    if src_instance.get("vm_name"):
        metadata["vm_name"] = src_instance["vm_name"]
    if src_instance.get("project_id"):
        metadata["project_id"] = src_instance["project_id"]

    # Source VPC metadata
    src_vpc = flow_log.get("src_vpc", {})
    if src_vpc.get("vpc_name"):
        metadata["vpc_name"] = src_vpc["vpc_name"]
    if src_vpc.get("subnetwork_name"):
        metadata["subnet_name"] = src_vpc["subnetwork_name"]

    # Remove any None values that slipped in from missing connection fields
    return {k: v for k, v in metadata.items() if v is not None}


def _build_summary(flow_log: dict) -> str:
    """Build a human-readable summary string from a flow log."""
    conn = flow_log.get("connection", {})
    src_ip = conn.get("src_ip", "?")
    dest_ip = conn.get("dest_ip", "?")
    src_port = conn.get("src_port", "?")
    dest_port = conn.get("dest_port", "?")
    protocol = conn.get("protocol", "?")
    bytes_sent = flow_log.get("bytes_sent", "?")
    return (
        f"VPC Flow: {src_ip}:{src_port} -> {dest_ip}:{dest_port} "
        f"proto={protocol} bytes={bytes_sent}"
    )


def format_ingest_api_payload(
    flow_log: dict, resource_id: dict | None, metadata: dict
) -> dict:
    """Format a flow log for the LM Logs Ingest API (/rest/log/ingest).

    Produces a single dict suitable for inclusion in the JSON array payload.

    Args:
        flow_log: Parsed VPC Flow Log jsonPayload.
        resource_id: Resource mapping dict or None for deviceless logs.
        metadata: Extracted metadata from extract_metadata().

    Returns:
        Dict with msg, metadata fields, and optionally _lm.resourceId.
    """
    payload = {"msg": _build_summary(flow_log)}

    if resource_id is not None:
        payload["_lm.resourceId"] = resource_id

    payload.update(metadata)
    return payload


def format_webhook_payload(flow_log: dict, log_entry: dict) -> dict:
    """Format a flow log for the LM Webhook endpoint.

    Produces a single JSON object with both the original nested structure
    (for flexible JSON path extraction in the Webhook LogSource) and
    convenience top-level keys for common fields.

    Args:
        flow_log: Parsed VPC Flow Log jsonPayload.
        log_entry: The full Cloud Logging LogEntry (for timestamp).

    Returns:
        Single flat-ish dict suitable for POST to the webhook endpoint.
    """
    payload = {}

    # Human-readable summary
    payload["message"] = _build_summary(flow_log)

    # LogEntry timestamp
    if "timestamp" in log_entry:
        payload["timestamp"] = log_entry["timestamp"]

    # Convenience top-level keys from connection
    conn = flow_log.get("connection", {})
    for key in ("src_ip", "dest_ip", "src_port", "dest_port", "protocol"):
        if key in conn:
            payload[key] = conn[key]

    # Traffic fields at top level
    for key in ("bytes_sent", "packets_sent", "reporter", "start_time", "end_time", "rtt_msec"):
        if key in flow_log:
            payload[key] = flow_log[key]

    # Preserve nested structures for JSON path extraction in Webhook LogSource
    # Only include blocks that are present in the flow log
    nested_keys = (
        "connection",
        "src_instance",
        "dest_instance",
        "src_vpc",
        "dest_vpc",
        "src_gke_details",
        "dest_gke_details",
        "src_location",
        "dest_location",
        "src_google_service",
        "dest_google_service",
    )
    for key in nested_keys:
        if key in flow_log:
            payload[key] = flow_log[key]

    return payload
