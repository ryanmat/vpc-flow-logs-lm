# Description: Incremental block-level blob reader with Table Storage watermarking.
# Description: Reads only new blocks from VNet flow log PT1H.json blobs to avoid reprocessing.

import json
import hashlib
import logging
import re

from flow_parser import parse_flow_records_from_json

logger = logging.getLogger(__name__)

# Partition key used for all watermarks in Table Storage
WATERMARK_PARTITION_KEY = "vnet-flow-watermarks"


def watermark_key_for_blob(blob_path):
    """Generate a Table Storage RowKey from a blob path.

    Extracts the meaningful components (date, hour, MAC) and hashes the rest
    to stay under the 1KB RowKey limit while remaining human-debuggable.
    """
    # Extract date/hour/mac components for readability
    parts = []
    for pattern in [r"y=(\d+)", r"m=(\d+)", r"d=(\d+)", r"h=(\d+)", r"macAddress=([A-Fa-f0-9]+)"]:
        match = re.search(pattern, blob_path)
        if match:
            parts.append(match.group(1))

    readable = "_".join(parts) if parts else ""
    # Add a short hash of the full path for uniqueness
    path_hash = hashlib.sha256(blob_path.encode("utf-8")).hexdigest()[:12]
    return f"{readable}_{path_hash}" if readable else path_hash


def compute_byte_offset(blocks):
    """Sum the sizes of a list of blocks to compute the byte offset."""
    return sum(b.size for b in blocks)


def get_new_block_data(blob_client, last_block_count):
    """Download only the new blocks from a blob since the last watermark.

    Returns (data_bytes, total_block_count) where data_bytes is the raw bytes
    of the new blocks, or (None, current_count) if no new blocks exist.
    """
    block_list_result = blob_client.get_block_list(block_list_type="committed")
    # The Azure SDK returns a tuple: (committed_blocks, uncommitted_blocks)
    if isinstance(block_list_result, tuple):
        committed = block_list_result[0]
    else:
        committed = block_list_result.committed_blocks
    total_count = len(committed)

    if total_count <= last_block_count:
        logger.debug("No new blocks (total=%d, watermark=%d)", total_count, last_block_count)
        return None, total_count

    # Calculate byte range for new blocks
    already_processed = committed[:last_block_count]
    new_blocks = committed[last_block_count:]
    offset = compute_byte_offset(already_processed)
    length = compute_byte_offset(new_blocks)

    logger.info("Reading %d new blocks (offset=%d, length=%d, total=%d)",
                len(new_blocks), offset, length, total_count)

    download = blob_client.download_blob(offset=offset, length=length)
    data = download.readall()
    return data, total_count


def parse_json_fragments(data, vnet_resource_id, device_display_name=""):
    """Parse flow log entries from raw block data.

    Handles both complete JSON (full blob download) and partial fragments
    (incremental block reads that may start with a comma or lack array brackets).
    """
    if not data:
        return []

    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return []

    # Try parsing as complete JSON first
    try:
        parsed = json.loads(text)
        return parse_flow_records_from_json(parsed, vnet_resource_id, device_display_name)
    except json.JSONDecodeError:
        pass

    # Handle fragments: strip leading comma, try wrapping in records array
    text = text.lstrip(",").rstrip("]").strip()
    if not text:
        return []

    # Try wrapping fragment as a records array element
    try:
        # The fragment may be one or more record objects separated by commas
        wrapped = '{"records": [' + text + "]}"
        parsed = json.loads(wrapped)
        return parse_flow_records_from_json(parsed, vnet_resource_id, device_display_name)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON fragment (%d bytes), skipping", len(data))
        return []


def get_watermark(table_client, blob_key):
    """Read the last processed block count from Table Storage.

    Returns 0 if no watermark exists for this blob.
    """
    try:
        entity = table_client.get_entity(
            partition_key=WATERMARK_PARTITION_KEY,
            row_key=blob_key,
        )
        return entity.get("block_count", 0)
    except Exception:
        return 0


def set_watermark(table_client, blob_key, block_count):
    """Write or update the watermark for a blob in Table Storage."""
    entity = {
        "PartitionKey": WATERMARK_PARTITION_KEY,
        "RowKey": blob_key,
        "block_count": block_count,
    }
    table_client.upsert_entity(entity)
    logger.debug("Watermark updated: %s -> %d blocks", blob_key, block_count)


def should_cleanup_watermark(blob_key, hours_old):
    """Determine if a watermark should be cleaned up based on age.

    Watermarks for blobs older than 2 hours are safe to remove since
    VNet flow logs rotate hourly and a blob receives its final update
    within a few minutes of the hour boundary.
    """
    return hours_old >= 2
