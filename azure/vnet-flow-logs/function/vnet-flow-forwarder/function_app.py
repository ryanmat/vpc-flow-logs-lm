# Description: Azure Function entry point for VNet flow log forwarding to LogicMonitor.
# Description: EventGrid trigger processes blob updates incrementally and sends batched logs via REST API.

import json
import logging
import os

import azure.functions as func
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from azure.data.tables import TableServiceClient

from block_reader import (
    get_new_block_data,
    parse_json_fragments,
    get_watermark,
    set_watermark,
    watermark_key_for_blob,
)
from flow_parser import assemble_batches
from lm_ingest import send_with_retry

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

app = func.FunctionApp()

# Configuration from environment variables
LM_COMPANY = os.environ.get("LM_COMPANY", "")
LM_ACCESS_ID = os.environ.get("LM_ACCESS_ID", "")
LM_ACCESS_KEY = os.environ.get("LM_ACCESS_KEY", "")
STORAGE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
WATERMARK_TABLE = os.environ.get("WATERMARK_TABLE_NAME", "vnetflowwatermarks")
TARGET_VNET_ID = os.environ.get("TARGET_VNET_RESOURCE_ID", "")
BATCH_SIZE_LIMIT = int(os.environ.get("BATCH_SIZE_LIMIT", "7340032"))
DEVICE_DISPLAY_NAME = os.environ.get("LM_DEVICE_DISPLAY_NAME", "")


@app.event_grid_trigger(arg_name="event")
def vnet_flow_processor(event: func.EventGridEvent):
    """Process a BlobCreated event from the VNet flow log storage account.

    Triggered by Event Grid when a PutBlockList operation commits new blocks
    to a PT1H.json flow log blob. Reads only the new blocks since the last
    watermark, parses flow tuples, and sends batched entries to the LM Logs
    Ingest API.
    """
    if not all([LM_COMPANY, LM_ACCESS_ID, LM_ACCESS_KEY, STORAGE_CONN_STR]):
        logger.error("Missing required environment variables (LM_COMPANY, LM_ACCESS_ID, LM_ACCESS_KEY, AZURE_STORAGE_CONNECTION_STRING)")
        raise ValueError("Missing required environment variables")

    event_data = event.get_json()
    event_type = event.event_type
    subject = event.subject or ""

    logger.info("Event received: type=%s subject=%s", event_type, subject)

    # Only process BlobCreated events from the flow log container
    if event_type != "Microsoft.Storage.BlobCreated":
        logger.info("Skipping non-BlobCreated event: %s", event_type)
        return

    api = event_data.get("api", "")
    if api != "PutBlockList":
        logger.info("Skipping non-PutBlockList event: api=%s", api)
        return

    # Extract blob path from the event subject
    # Subject format: /blobServices/default/containers/{container}/blobs/{blob_path}
    blob_url = event_data.get("url", "")
    content_type = event_data.get("contentType", "")

    # Parse container and blob path from subject
    container_name, blob_path = _parse_blob_subject(subject)
    if not container_name or not blob_path:
        logger.warning("Could not parse container/blob from subject: %s", subject)
        return

    if "insights-logs-flowlogflowevent" not in container_name:
        logger.info("Skipping non-flow-log container: %s", container_name)
        return

    logger.info("Processing flow log blob: container=%s blob=%s", container_name, blob_path)

    # Connect to storage and table services
    blob_service = BlobServiceClient.from_connection_string(STORAGE_CONN_STR)
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_path)

    table_service = TableServiceClient.from_connection_string(STORAGE_CONN_STR)
    table_client = table_service.get_table_client(WATERMARK_TABLE)

    # Ensure watermark table exists
    try:
        table_client.create_table()
    except ResourceExistsError:
        pass  # Table already exists

    # Read watermark and fetch new blocks
    blob_key = watermark_key_for_blob(blob_path)
    last_count = get_watermark(table_client, blob_key)

    data, new_count = get_new_block_data(blob_client, last_block_count=last_count)

    if data is None:
        logger.info("No new blocks to process (watermark=%d, current=%d)", last_count, new_count)
        return

    # Determine VNet resource ID: use env var, or extract from blob path if available
    vnet_resource_id = TARGET_VNET_ID

    # Parse flow tuples from the new block data
    entries = parse_json_fragments(data, vnet_resource_id, device_display_name=DEVICE_DISPLAY_NAME)

    if not entries:
        if not data or not data.strip():
            logger.info("No flow entries in empty blocks, advancing watermark")
            set_watermark(table_client, blob_key, new_count)
        else:
            logger.error("Parse produced no entries from %d bytes of block data, watermark NOT advanced", len(data))
        return

    logger.info("Parsed %d flow entries from %d new blocks", len(entries), new_count - last_count)

    # Batch and send to LM
    batches = assemble_batches(entries, max_bytes=BATCH_SIZE_LIMIT)
    total_sent = 0
    total_failed = 0

    for i, batch in enumerate(batches):
        success = send_with_retry(
            batch,
            company=LM_COMPANY,
            access_id=LM_ACCESS_ID,
            access_key=LM_ACCESS_KEY,
        )
        if success:
            total_sent += len(batch)
        else:
            total_failed += len(batch)
            logger.error("Batch %d/%d failed (%d entries)", i + 1, len(batches), len(batch))

    # Update watermark after successful processing
    if total_failed == 0:
        set_watermark(table_client, blob_key, new_count)
        logger.info("Complete: sent=%d entries in %d batches, watermark=%d", total_sent, len(batches), new_count)
    else:
        # Partial failure: do NOT advance watermark so we reprocess on next trigger
        logger.warning("Partial failure: sent=%d failed=%d, watermark NOT advanced", total_sent, total_failed)


def _parse_blob_subject(subject):
    """Extract container name and blob path from an Event Grid subject string.

    Subject format: /blobServices/default/containers/{container}/blobs/{blob_path}
    Returns (container_name, blob_path) or (None, None) if parsing fails.
    """
    prefix = "/blobServices/default/containers/"
    if prefix not in subject:
        return None, None

    remainder = subject.split(prefix, 1)[1]
    parts = remainder.split("/blobs/", 1)
    if len(parts) != 2:
        return None, None

    return parts[0], parts[1]
