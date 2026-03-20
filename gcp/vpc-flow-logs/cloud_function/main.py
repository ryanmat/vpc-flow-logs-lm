# Description: Cloud Function entry point for relaying VPC Flow Logs to LogicMonitor.
# Description: Receives Pub/Sub CloudEvents and forwards parsed flow logs to LM.
from __future__ import annotations

import logging

import functions_framework
import requests

from cloud_function.config import load_config
from cloud_function.flow_log_parser import (
    extract_flow_log,
    extract_metadata,
    extract_resource_id,
    format_ingest_api_payload,
    format_webhook_payload,
    parse_pubsub_message,
)
from cloud_function.lm_client import LMClient

logger = logging.getLogger(__name__)

# Module-level state for cold start optimization.
# Config and client are initialized once and reused across invocations.
_config = None
_client = None
_initialized = False


def _init():
    """Initialize module-level config and client. Called once on cold start."""
    global _config, _client, _initialized
    _config = load_config()
    _client = LMClient(_config)
    _initialized = True


@functions_framework.cloud_event
def handle_pubsub(cloud_event):
    """Cloud Function entry point for Pub/Sub-triggered VPC Flow Log processing.

    Parses the incoming CloudEvent, extracts the VPC Flow Log, and sends it
    to LogicMonitor via the configured endpoint (Ingest API or Webhook).

    Error handling strategy:
        - ValueError (bad message format): log warning, acknowledge (no retry)
        - RequestException (LM endpoint issues): log error, re-raise for Pub/Sub retry
        - Other exceptions: log error, acknowledge (no retry on unknown errors)
    """
    global _config, _client, _initialized

    if not _initialized:
        _init()

    try:
        log_entry = parse_pubsub_message(cloud_event)
        flow_log = extract_flow_log(log_entry)
    except ValueError as e:
        logger.warning("Skipping malformed message: %s", e)
        return

    try:
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)

        src_ip = metadata.get("src_ip", "?")
        dest_ip = metadata.get("dest_ip", "?")

        if _config.use_webhook:
            # Phase 2: Webhook path — thin relay, all mapping in LM portal
            payload = format_webhook_payload(flow_log, log_entry)
            success = _client.send_to_webhook(payload)
            endpoint = "webhook"
        else:
            # Phase 1: Ingest API path — resource mapping in code
            payload = format_ingest_api_payload(flow_log, resource_id, metadata)
            success = _client.send_to_ingest_api([payload])
            endpoint = "ingest_api"

        logger.info(
            "Processed flow log: %s -> %s, bytes=%s, endpoint=%s, success=%s",
            src_ip,
            dest_ip,
            metadata.get("bytes_sent", "?"),
            endpoint,
            success,
        )

    except requests.exceptions.RequestException as e:
        # LM endpoint connectivity issues — re-raise to trigger Pub/Sub retry
        logger.error("LM endpoint request failed, will retry: %s", e)
        raise

    except Exception as e:
        # Unknown errors — log and acknowledge to prevent infinite retry
        logger.error("Unexpected error processing flow log: %s", e, exc_info=True)
