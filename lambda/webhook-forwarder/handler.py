# Description: AWS Lambda function that forwards CloudWatch Logs to LogicMonitor via webhook.
# Description: Decompresses CW subscription filter events and POSTs to LM webhook ingest endpoint.

import base64
import gzip
import json
import logging
import os
import re
import time
import urllib.request
import urllib.error

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables
LM_PORTAL_NAME = os.environ.get("LM_PORTAL_NAME", "")
LM_BEARER_TOKEN = os.environ.get("LM_BEARER_TOKEN", "")

# Rate control: pause between individual webhook POSTs (seconds).
# The LM webhook endpoint rate-limits at ~10 req/s. With reserved
# concurrency set to 2, two Lambda instances share the limit.
# 0.25s per instance = ~4 req/s each = ~8 req/s combined.
SEND_DELAY = float(os.environ.get("SEND_DELAY", "0.25"))

# Retry config for 429 responses
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.environ.get("RETRY_BASE_DELAY", "1.0"))

# Map CloudWatch log group names to webhook source names
LOG_GROUP_SOURCE_MAP = {
    "/aws/vpc/flowlogs": "vpc_flow_logs",
    "aws-waf-logs-kpmg": "waf_logs",
}

# Map CloudWatch log group names to resource type labels for LM Logs
LOG_GROUP_RESOURCE_TYPE_MAP = {
    "/aws/vpc/flowlogs": "AWS VPC Flow Logs",
    "aws-waf-logs-kpmg": "AWS WAF WebACL",
}


def lambda_handler(event, context):
    """Main Lambda entry point for CloudWatch Logs subscription filter events."""
    if not LM_PORTAL_NAME or not LM_BEARER_TOKEN:
        logger.error("LM_PORTAL_NAME and LM_BEARER_TOKEN environment variables are required")
        raise ValueError("Missing required environment variables")

    cw_data = decompress_cw_event(event)

    if cw_data.get("messageType") == "CONTROL_MESSAGE":
        logger.info("Received CONTROL_MESSAGE, skipping")
        return {"statusCode": 200, "body": "Control message, no action taken"}

    if cw_data.get("messageType") != "DATA_MESSAGE":
        logger.warning("Unknown messageType: %s", cw_data.get("messageType"))
        return {"statusCode": 200, "body": "Unknown message type, skipping"}

    log_group = cw_data.get("logGroup", "")
    log_stream = cw_data.get("logStream", "")
    log_events = cw_data.get("logEvents", [])
    owner = cw_data.get("owner", "")

    if not log_events:
        logger.info("No log events in payload")
        return {"statusCode": 200, "body": "No events"}

    source_name = resolve_source_name(log_group)
    logger.info(
        "Processing %d events from logGroup=%s logStream=%s source=%s",
        len(log_events), log_group, log_stream, source_name,
    )

    success_count = 0
    error_count = 0

    for i, log_event in enumerate(log_events):
        msg = log_event.get("message", "").strip()
        if not msg:
            continue

        payload = build_payload(log_event, log_group, log_stream, owner)
        sent = send_with_retry(source_name, payload)
        if sent:
            success_count += 1
        else:
            error_count += 1

        # Pace requests to avoid 429s (skip delay after last event)
        if SEND_DELAY > 0 and i < len(log_events) - 1:
            time.sleep(SEND_DELAY)

    logger.info("Done: %d sent, %d failed out of %d total", success_count, error_count, len(log_events))

    if error_count > 0 and success_count == 0:
        raise RuntimeError(f"All {error_count} events failed to send")

    return {
        "statusCode": 200,
        "body": json.dumps({"sent": success_count, "failed": error_count}),
    }


def decompress_cw_event(event):
    """Decode and decompress a CloudWatch Logs subscription filter event."""
    compressed = base64.b64decode(event["awslogs"]["data"])
    decompressed = gzip.decompress(compressed)
    return json.loads(decompressed)


def resolve_source_name(log_group):
    """Map a CloudWatch log group name to a webhook source name.

    Checks exact matches first, then prefix matches for log groups that
    may have variable suffixes (e.g. aws-waf-logs-<name>).
    """
    if log_group in LOG_GROUP_SOURCE_MAP:
        return LOG_GROUP_SOURCE_MAP[log_group]

    for prefix, source in LOG_GROUP_SOURCE_MAP.items():
        if log_group.startswith(prefix.rstrip("*")):
            return source

    fallback = log_group.strip("/").replace("/", "_").replace("-", "_")
    logger.warning("No source mapping for logGroup=%s, using fallback=%s", log_group, fallback)
    return fallback


ENI_PATTERN = re.compile(r"(eni-[a-f0-9]+)")

# VPC Flow Log field names matching the custom format configured in CloudWatch.
# Order: instance_id srcaddr dstaddr srcport dstport protocol packets bytes start end action log_status
VPC_FLOW_LOG_FIELDS = [
    "instance_id", "srcaddr", "dstaddr", "srcport", "dstport",
    "protocol", "packets", "bytes", "start", "end", "action", "log_status",
]


def build_payload(log_event, log_group, log_stream, owner):
    """Build a webhook payload from a single CloudWatch log event.

    The payload includes the raw message plus metadata fields that the
    Webhook LogSource can extract via Webhook Attribute mappings.
    """
    resource_type = LOG_GROUP_RESOURCE_TYPE_MAP.get(log_group, "")
    if not resource_type:
        for prefix, rt in LOG_GROUP_RESOURCE_TYPE_MAP.items():
            if log_group.startswith(prefix.rstrip("*")):
                resource_type = rt
                break

    payload = {
        "message": log_event.get("message", ""),
        "timestamp": log_event.get("timestamp", 0),
        "logGroup": log_group,
        "logStream": log_stream,
        "owner": owner,
        "id": log_event.get("id", ""),
        "resourceType": resource_type,
    }

    # Extract clean ENI ID from log stream name (e.g. "eni-abc123-all" -> "eni-abc123")
    eni_match = ENI_PATTERN.search(log_stream)
    if eni_match:
        payload["eni"] = eni_match.group(1)

    # Parse log-group-specific fields into top-level keys for Webhook Attribute mapping
    if log_group.startswith("/aws/vpc/flowlogs"):
        parse_vpc_flow_log(payload)
    elif log_group.startswith("aws-waf-logs"):
        parse_waf_log(payload)

    return payload


def parse_vpc_flow_log(payload):
    """Parse VPC flow log message fields into top-level payload keys.

    Splits the space-delimited flow log message and maps each positional
    field to a named key. This lets the Webhook LogSource use Webhook
    Attribute mappings instead of fragile regex extraction.
    """
    msg = payload.get("message", "").strip()
    parts = msg.split()
    for i, field_name in enumerate(VPC_FLOW_LOG_FIELDS):
        if i < len(parts):
            payload[field_name] = parts[i]

    # Derive log level from flow action for LogSource log_level mapping
    action = payload.get("action", "")
    payload["Level"] = "warn" if action == "REJECT" else "info"


# WAF log fields to extract from the JSON message into top-level payload keys.
WAF_LOG_FIELDS = [
    "action", "webaclId", "terminatingRuleId", "terminatingRuleType",
    "httpMethod", "clientIp", "country", "uri",
]


def parse_waf_log(payload):
    """Parse WAF JSON log message fields into top-level payload keys.

    WAF log messages are JSON objects. This extracts key fields so the
    Webhook LogSource can use Webhook Attribute mappings. Also extracts
    nested fields like httpRequest.clientIp and httpRequest.country.
    """
    msg = payload.get("message", "").strip()
    try:
        waf_data = json.loads(msg)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse WAF log message as JSON")
        return

    for field in WAF_LOG_FIELDS:
        if field in waf_data:
            payload[field] = str(waf_data[field])

    # httpRequest contains nested fields: clientIp, country, uri, httpMethod
    http_req = waf_data.get("httpRequest", {})
    if http_req:
        for field in ("clientIp", "country", "uri", "httpMethod"):
            if field in http_req and field not in payload:
                payload[field] = str(http_req[field])

    # Derive log level from WAF action for LogSource log_level mapping
    action = waf_data.get("action", "")
    payload["Level"] = "warn" if action == "BLOCK" else "info"


def send_with_retry(source_name, payload):
    """Send a single event to the webhook with exponential backoff on 429."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            send_to_webhook(source_name, payload)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("429 rate limited, retry %d/%d after %.1fs", attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
            else:
                logger.error("Failed to send event (attempt %d): HTTP %s", attempt + 1, getattr(e, 'code', 'unknown'))
                return False
        except Exception:
            logger.exception("Unexpected error sending event (attempt %d)", attempt + 1)
            return False
    return False


def send_to_webhook(source_name, payload):
    """POST a single log event to the LogicMonitor webhook ingest endpoint."""
    url = f"https://{LM_PORTAL_NAME}.logicmonitor.com/rest/api/v1/webhook/ingest/{source_name}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {LM_BEARER_TOKEN}")
    req.add_header("User-Agent", "kpmg-webhook-forwarder/1.0.0")

    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status
        body = resp.read().decode("utf-8")
        logger.debug("Webhook response %d: %s", status, body)
