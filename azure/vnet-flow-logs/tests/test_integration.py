# Description: Integration tests against real Azure Storage for VNet flow log processing.
# Description: Requires AZURE_STORAGE_CONNECTION_STRING in environment. Reads actual flow log blobs.

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "azure-function", "vnet-flow-forwarder"))

STORAGE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
FLOW_LOG_CONTAINER = "insights-logs-flowlogflowevent"
VNET_RESOURCE_ID = "/subscriptions/1eae27d8-cbaa-43fd-9f60-ce33de2c69b6/resourceGroups/CTA_Resource_Group/providers/Microsoft.Network/virtualNetworks/CTA-vnet"

# Skip all tests in this module if no storage connection string is set
pytestmark = pytest.mark.skipif(
    not STORAGE_CONN_STR,
    reason="AZURE_STORAGE_CONNECTION_STRING not set"
)


@pytest.fixture(scope="module")
def blob_service():
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(STORAGE_CONN_STR)


@pytest.fixture(scope="module")
def flow_log_blobs(blob_service):
    """List available PT1H.json blobs in the flow log container."""
    container_client = blob_service.get_container_client(FLOW_LOG_CONTAINER)
    blobs = []
    for blob in container_client.list_blobs():
        if blob.name.endswith("PT1H.json"):
            blobs.append(blob)
        if len(blobs) >= 5:
            break
    return blobs


class TestFlowLogBlobExists:
    """Verify VNet flow logs are being written to storage."""

    def test_container_exists(self, blob_service):
        container_client = blob_service.get_container_client(FLOW_LOG_CONTAINER)
        props = container_client.get_container_properties()
        assert props is not None

    def test_at_least_one_blob(self, flow_log_blobs):
        assert len(flow_log_blobs) > 0, (
            f"No PT1H.json blobs found in {FLOW_LOG_CONTAINER}. "
            "VNet flow logs may not have generated data yet."
        )


class TestBlobStructure:
    """Verify the internal structure of flow log blobs."""

    def test_blob_is_valid_json(self, blob_service, flow_log_blobs):
        if not flow_log_blobs:
            pytest.skip("No blobs available")
        blob = flow_log_blobs[0]
        client = blob_service.get_blob_client(FLOW_LOG_CONTAINER, blob.name)
        data = client.download_blob().readall()
        parsed = json.loads(data)
        assert "records" in parsed

    def test_blob_has_committed_blocks(self, blob_service, flow_log_blobs):
        if not flow_log_blobs:
            pytest.skip("No blobs available")
        blob = flow_log_blobs[0]
        client = blob_service.get_blob_client(FLOW_LOG_CONTAINER, blob.name)
        block_list = client.get_block_list(block_list_type="committed")
        # Azure SDK returns a tuple: (committed_blocks, uncommitted_blocks)
        committed = block_list[0] if isinstance(block_list, tuple) else block_list.committed_blocks
        assert len(committed) >= 1, "Blob should have at least one committed block"

    def test_records_have_flow_tuples(self, blob_service, flow_log_blobs):
        if not flow_log_blobs:
            pytest.skip("No blobs available")
        blob = flow_log_blobs[0]
        client = blob_service.get_blob_client(FLOW_LOG_CONTAINER, blob.name)
        data = client.download_blob().readall()
        parsed = json.loads(data)
        records = parsed.get("records", [])
        if not records:
            pytest.skip("No records in blob (may be too new)")

        record = records[0]
        assert "flowRecords" in record
        assert "macAddress" in record


class TestIncrementalRead:
    """Verify the incremental block read pipeline works against real blobs."""

    def test_full_pipeline(self, blob_service, flow_log_blobs):
        """Read a real blob incrementally and parse flow entries."""
        if not flow_log_blobs:
            pytest.skip("No blobs available")

        from block_reader import get_new_block_data, parse_json_fragments

        blob = flow_log_blobs[0]
        client = blob_service.get_blob_client(FLOW_LOG_CONTAINER, blob.name)

        # First read: no watermark, get everything
        data, block_count = get_new_block_data(client, last_block_count=0)
        assert data is not None
        assert block_count > 0

        # Parse the data
        entries = parse_json_fragments(data, VNET_RESOURCE_ID)
        # Entries may be empty if the blob has records but no flow tuples yet
        if entries:
            entry = entries[0]
            assert "msg" in entry
            assert "_lm.resourceId" in entry
            assert "srcIP" in entry
            assert "protocol" in entry
            print(f"Parsed {len(entries)} flow entries from {blob.name}")
            print(f"Sample entry: {json.dumps(entry, indent=2)[:500]}")

        # Second read with same watermark: no new data
        data2, count2 = get_new_block_data(client, last_block_count=block_count)
        assert data2 is None, "Should have no new blocks on immediate re-read"


class TestLmPayloadFormat:
    """Verify the LM payload format from real flow log data."""

    def test_payload_has_required_fields(self, blob_service, flow_log_blobs):
        if not flow_log_blobs:
            pytest.skip("No blobs available")

        from block_reader import parse_json_fragments

        blob = flow_log_blobs[0]
        client = blob_service.get_blob_client(FLOW_LOG_CONTAINER, blob.name)
        data = client.download_blob().readall()
        entries = parse_json_fragments(data, VNET_RESOURCE_ID)

        if not entries:
            pytest.skip("No flow entries in blob")

        for entry in entries[:5]:
            assert "msg" in entry, "Missing msg field"
            assert "_lm.resourceId" in entry, "Missing _lm.resourceId"
            assert "azure.resourceid" in entry["_lm.resourceId"]
            assert "timestamp" in entry
            assert entry["timestamp"].endswith("Z"), "Timestamp should be UTC ISO 8601"
            assert entry["protocol"] in ("TCP", "UDP", "ICMP") or entry["protocol"].isdigit()
            assert entry["direction"] in ("inbound", "outbound")
            assert entry["flowState"] in ("begin", "continue", "end", "deny")
            assert entry["Level"] in ("info", "warn")

            # Verify payload size is under 32KB per-entry limit
            entry_size = len(json.dumps(entry).encode("utf-8"))
            assert entry_size < 32768, f"Entry too large: {entry_size} bytes"
