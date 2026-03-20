# Description: Unit tests for incremental block-level blob reads and watermark management.
# Description: Uses mock Azure SDK objects to test block list diffing and watermark CRUD.

import json
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock
from collections import namedtuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "azure-function", "vnet-flow-forwarder"))

from block_reader import (
    get_new_block_data,
    compute_byte_offset,
    parse_json_fragments,
    get_watermark,
    set_watermark,
    watermark_key_for_blob,
    should_cleanup_watermark,
)


# Simulated Azure SDK block objects
Block = namedtuple("Block", ["name", "size"])


class TestWatermarkKeyForBlob:
    """Test watermark key generation from blob paths."""

    def test_standard_path(self):
        path = "insights-logs-flowlogflowevent/flowLogResourceID=/SUBSCRIPTIONS/sub/y=2024/m=02/d=02/h=12/m=00/macAddress=000D3A123456/PT1H.json"
        key = watermark_key_for_blob(path)
        # Key should be a safe string derived from the path
        assert "000D3A123456" in key
        assert "2024" in key
        assert len(key) < 256  # Table Storage RowKey limit

    def test_different_macs_produce_different_keys(self):
        path1 = "container/y=2024/m=02/d=02/h=12/m=00/macAddress=AABBCCDDEE01/PT1H.json"
        path2 = "container/y=2024/m=02/d=02/h=12/m=00/macAddress=AABBCCDDEE02/PT1H.json"
        assert watermark_key_for_blob(path1) != watermark_key_for_blob(path2)

    def test_different_hours_produce_different_keys(self):
        path1 = "container/y=2024/m=02/d=02/h=12/m=00/macAddress=AA/PT1H.json"
        path2 = "container/y=2024/m=02/d=02/h=13/m=00/macAddress=AA/PT1H.json"
        assert watermark_key_for_blob(path1) != watermark_key_for_blob(path2)


class TestComputeByteOffset:
    """Test computing byte offset from a list of blocks."""

    def test_no_blocks(self):
        assert compute_byte_offset([]) == 0

    def test_single_block(self):
        blocks = [Block("b1", 100)]
        assert compute_byte_offset(blocks) == 100

    def test_multiple_blocks(self):
        blocks = [Block("b1", 12), Block("b2", 2500), Block("b3", 2800)]
        assert compute_byte_offset(blocks) == 5312


class TestGetNewBlockData:
    """Test extracting data from only the new (unprocessed) blocks."""

    def test_no_previous_watermark_gets_all_blocks(self):
        committed_blocks = [
            Block("b0", 12),    # opening bracket
            Block("b1", 2500),  # record 1
            Block("b2", 2),     # closing bracket
        ]
        mock_blob_client = MagicMock()
        mock_blob_client.get_block_list.return_value = MagicMock(committed_blocks=committed_blocks)

        # Simulate downloading all block data
        full_data = b'[{"record": 1}]'
        mock_download = MagicMock()
        mock_download.readall.return_value = full_data
        mock_blob_client.download_blob.return_value = mock_download

        data, new_count = get_new_block_data(mock_blob_client, last_block_count=0)
        assert new_count == 3
        assert data == full_data

    def test_with_watermark_gets_only_new_blocks(self):
        committed_blocks = [
            Block("b0", 12),     # opening bracket (already processed)
            Block("b1", 2500),   # record 1 (already processed)
            Block("b2", 2800),   # record 2 (NEW)
            Block("b3", 2),      # closing bracket (NEW)
        ]
        mock_blob_client = MagicMock()
        mock_blob_client.get_block_list.return_value = MagicMock(committed_blocks=committed_blocks)

        new_data = b',{"record": 2}]'
        mock_download = MagicMock()
        mock_download.readall.return_value = new_data
        mock_blob_client.download_blob.return_value = mock_download

        data, new_count = get_new_block_data(mock_blob_client, last_block_count=2)
        assert new_count == 4
        # Should have requested download starting at offset 12 + 2500 = 2512
        mock_blob_client.download_blob.assert_called_once_with(offset=2512, length=2802)

    def test_no_new_blocks_returns_none(self):
        committed_blocks = [Block("b0", 12), Block("b1", 2500)]
        mock_blob_client = MagicMock()
        mock_blob_client.get_block_list.return_value = MagicMock(committed_blocks=committed_blocks)

        data, new_count = get_new_block_data(mock_blob_client, last_block_count=2)
        assert data is None
        assert new_count == 2


class TestParseJsonFragments:
    """Test parsing flow records from partial JSON block data."""

    def test_parse_full_json(self):
        data = json.dumps({
            "records": [{
                "macAddress": "AA",
                "targetResourceID": "/vnet",
                "flowRecords": {"flows": [{"flowGroups": [{"rule": "R1", "flowTuples": [
                    "1706886400000,10.0.0.4,168.62.32.14,443,52362,6,O,E,NX,10,1234,8,5678"
                ]}]}]}
            }]
        }).encode("utf-8")
        entries = parse_json_fragments(data, "/vnet")
        assert len(entries) == 1
        assert entries[0]["srcIP"] == "10.0.0.4"

    def test_parse_fragment_with_leading_comma(self):
        # When reading new blocks, data may start with a comma before the next record
        fragment = b',{"time":"2024-02-02","macAddress":"AA","targetResourceID":"/vnet","flowRecords":{"flows":[{"flowGroups":[{"rule":"R1","flowTuples":["1706886400000,10.0.0.4,168.62.32.14,443,52362,6,O,E,NX,10,1234,8,5678"]}]}]}}]'
        entries = parse_json_fragments(fragment, "/vnet")
        assert len(entries) == 1

    def test_empty_data_returns_empty(self):
        entries = parse_json_fragments(b"", "/vnet")
        assert len(entries) == 0

    def test_malformed_json_returns_empty(self):
        entries = parse_json_fragments(b"not json at all", "/vnet")
        assert len(entries) == 0


class TestGetSetWatermark:
    """Test watermark CRUD operations against Table Storage."""

    def test_get_watermark_returns_zero_when_not_found(self):
        mock_table_client = MagicMock()
        mock_table_client.get_entity.side_effect = Exception("Not found")
        result = get_watermark(mock_table_client, "test_blob_key")
        assert result == 0

    def test_get_watermark_returns_stored_value(self):
        mock_table_client = MagicMock()
        mock_table_client.get_entity.return_value = {"block_count": 5}
        result = get_watermark(mock_table_client, "test_blob_key")
        assert result == 5

    def test_set_watermark_upserts_entity(self):
        mock_table_client = MagicMock()
        set_watermark(mock_table_client, "test_blob_key", 10)
        mock_table_client.upsert_entity.assert_called_once()
        call_args = mock_table_client.upsert_entity.call_args[0][0]
        assert call_args["block_count"] == 10
        assert call_args["RowKey"] == "test_blob_key"


class TestShouldCleanupWatermark:
    """Test watermark cleanup logic for old blobs."""

    def test_current_hour_blob_should_not_cleanup(self):
        # Path with current hour should not be cleaned up
        assert should_cleanup_watermark("h=23", hours_old=0) is False

    def test_old_blob_should_cleanup(self):
        assert should_cleanup_watermark("h=10", hours_old=3) is True

    def test_threshold_check(self):
        assert should_cleanup_watermark("h=10", hours_old=1) is False
        assert should_cleanup_watermark("h=10", hours_old=2) is True
