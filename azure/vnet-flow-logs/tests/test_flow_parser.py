# Description: Unit tests for VNet flow log tuple parsing and LM payload construction.
# Description: Covers all flow states, protocol mappings, edge cases, and batch assembly.

import json
import sys
import os

import pytest

# Add the azure function source to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "function", "vnet-flow-forwarder"))

from flow_parser import (
    parse_flow_tuple,
    build_lm_log_entry,
    protocol_name,
    flow_state_label,
    direction_label,
    build_msg_string,
    assemble_batches,
    parse_flow_records_from_json,
    FLOW_TUPLE_FIELDS,
)


# -- Test data --

SAMPLE_TUPLE_E = "1706886400000,10.0.0.4,168.62.32.14,443,52362,6,O,E,NX,10,1234,8,5678"
SAMPLE_TUPLE_B = "1706886400000,10.0.0.4,168.62.32.14,443,52362,6,O,B,NX,0,0,0,0"
SAMPLE_TUPLE_C = "1706886401000,10.0.0.4,168.62.32.14,443,52362,6,I,C,X,100,50000,80,40000"
SAMPLE_TUPLE_D = "1706886402000,192.168.1.5,10.0.0.4,8080,443,17,I,D,NX,0,0,0,0"

VNET_RESOURCE_ID = "/subscriptions/1eae27d8-cbaa-43fd-9f60-ce33de2c69b6/resourceGroups/CTA_Resource_Group/providers/Microsoft.Network/virtualNetworks/CTA-vnet"

SAMPLE_FLOW_LOG_JSON = {
    "records": [
        {
            "time": "2024-02-02T12:00:00.000Z",
            "flowLogVersion": 4,
            "flowLogGUID": "66aa66aa-bb77-cc88-dd99-00ee00ee00ee",
            "macAddress": "000D3A123456",
            "category": "FlowLogFlowEvent",
            "flowLogResourceID": "/SUBSCRIPTIONS/1eae27d8/RESOURCEGROUPS/NETWORKWATCHERRG/PROVIDERS/MICROSOFT.NETWORK/NETWORKWATCHERS/NETWORKWATCHER_EASTUS/FLOWLOGS/VNETFLOWLOG",
            "targetResourceID": VNET_RESOURCE_ID,
            "operationName": "FlowLogFlowEvent",
            "flowRecords": {
                "flows": [
                    {
                        "aclID": "acl-123",
                        "flowGroups": [
                            {
                                "rule": "DefaultRule_AllowInternetOutBound",
                                "flowTuples": [
                                    SAMPLE_TUPLE_E,
                                    SAMPLE_TUPLE_B,
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    ]
}


class TestParseFlowTuple:
    """Test parsing individual comma-separated flow tuples into dicts."""

    def test_parse_end_state_tuple(self):
        result = parse_flow_tuple(SAMPLE_TUPLE_E)
        assert result["timestamp_epoch_ms"] == "1706886400000"
        assert result["srcIP"] == "10.0.0.4"
        assert result["dstIP"] == "168.62.32.14"
        assert result["srcPort"] == "443"
        assert result["dstPort"] == "52362"
        assert result["protocol"] == "6"
        assert result["direction"] == "O"
        assert result["flowState"] == "E"
        assert result["encryption"] == "NX"
        assert result["pktsSrcDst"] == "10"
        assert result["bytesSrcDst"] == "1234"
        assert result["pktsDstSrc"] == "8"
        assert result["bytesDstSrc"] == "5678"

    def test_parse_begin_state_tuple(self):
        result = parse_flow_tuple(SAMPLE_TUPLE_B)
        assert result["flowState"] == "B"
        assert result["pktsSrcDst"] == "0"
        assert result["bytesSrcDst"] == "0"

    def test_parse_continue_state_tuple(self):
        result = parse_flow_tuple(SAMPLE_TUPLE_C)
        assert result["flowState"] == "C"
        assert result["direction"] == "I"
        assert result["encryption"] == "X"
        assert result["pktsSrcDst"] == "100"

    def test_parse_deny_state_tuple(self):
        result = parse_flow_tuple(SAMPLE_TUPLE_D)
        assert result["flowState"] == "D"
        assert result["protocol"] == "17"
        assert result["srcIP"] == "192.168.1.5"

    def test_parse_malformed_tuple_too_few_fields(self):
        result = parse_flow_tuple("1706886400000,10.0.0.4,168.62.32.14")
        assert result is None

    def test_parse_empty_string(self):
        result = parse_flow_tuple("")
        assert result is None

    def test_parse_whitespace_only(self):
        result = parse_flow_tuple("   ")
        assert result is None

    def test_field_count_matches_constant(self):
        assert len(FLOW_TUPLE_FIELDS) == 13


class TestProtocolName:
    """Test IANA protocol number to human-readable name mapping."""

    def test_tcp(self):
        assert protocol_name("6") == "TCP"

    def test_udp(self):
        assert protocol_name("17") == "UDP"

    def test_icmp(self):
        assert protocol_name("1") == "ICMP"

    def test_unknown_protocol(self):
        assert protocol_name("47") == "47"

    def test_empty_string(self):
        assert protocol_name("") == ""


class TestFlowStateLabel:
    """Test flow state code to human-readable label mapping."""

    def test_begin(self):
        assert flow_state_label("B") == "begin"

    def test_continue(self):
        assert flow_state_label("C") == "continue"

    def test_end(self):
        assert flow_state_label("E") == "end"

    def test_deny(self):
        assert flow_state_label("D") == "deny"

    def test_unknown(self):
        assert flow_state_label("X") == "X"


class TestDirectionLabel:
    """Test direction code to human-readable label mapping."""

    def test_inbound(self):
        assert direction_label("I") == "inbound"

    def test_outbound(self):
        assert direction_label("O") == "outbound"

    def test_unknown(self):
        assert direction_label("Z") == "Z"


class TestBuildMsgString:
    """Test human-readable log message construction from parsed tuple fields."""

    def test_allow_outbound_tcp(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_E)
        msg = build_msg_string(parsed)
        assert "TCP" in msg
        assert "10.0.0.4:443" in msg
        assert "168.62.32.14:52362" in msg
        assert "outbound" in msg
        assert "1234B" in msg
        assert "5678B" in msg

    def test_deny_message(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_D)
        msg = build_msg_string(parsed)
        assert "DENY" in msg
        assert "UDP" in msg


class TestBuildLmLogEntry:
    """Test construction of LM log ingest API payload entries."""

    def test_basic_entry(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_E)
        entry = build_lm_log_entry(
            parsed,
            vnet_resource_id=VNET_RESOURCE_ID,
            device_display_name="US-E1:virtualNetwork:CTA-vnet",
            mac_address="000D3A123456",
            rule="DefaultRule_AllowInternetOutBound",
        )
        assert "msg" in entry
        assert "_lm.resourceId" in entry
        assert entry["_lm.resourceId"]["azure.resourceid"] == VNET_RESOURCE_ID
        assert entry["_lm.resourceId"]["system.displayname"] == "US-E1:virtualNetwork:CTA-vnet"
        assert entry["srcIP"] == "10.0.0.4"
        assert entry["dstIP"] == "168.62.32.14"
        assert entry["protocol"] == "TCP"
        assert entry["direction"] == "outbound"
        assert entry["flowState"] == "end"
        assert entry["macAddress"] == "000D3A123456"
        assert entry["rule"] == "DefaultRule_AllowInternetOutBound"

    def test_timestamp_is_iso8601(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_E)
        entry = build_lm_log_entry(parsed, vnet_resource_id=VNET_RESOURCE_ID)
        # 1706886400000 ms = 2024-02-02T16:00:00.000Z
        assert "2024-02-02T" in entry["timestamp"]
        assert entry["timestamp"].endswith("Z")

    def test_deny_sets_level_warn(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_D)
        entry = build_lm_log_entry(parsed, vnet_resource_id=VNET_RESOURCE_ID)
        assert entry["Level"] == "warn"

    def test_allow_sets_level_info(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_E)
        entry = build_lm_log_entry(parsed, vnet_resource_id=VNET_RESOURCE_ID)
        assert entry["Level"] == "info"

    def test_entry_under_32kb(self):
        parsed = parse_flow_tuple(SAMPLE_TUPLE_E)
        entry = build_lm_log_entry(parsed, vnet_resource_id=VNET_RESOURCE_ID)
        assert len(json.dumps(entry).encode("utf-8")) < 32768


class TestAssembleBatches:
    """Test batch assembly respecting size limits."""

    def test_single_entry_single_batch(self):
        entries = [{"msg": "test", "_lm.resourceId": {}}]
        batches = assemble_batches(entries, max_bytes=8 * 1024 * 1024)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_empty_entries_no_batches(self):
        batches = assemble_batches([], max_bytes=8 * 1024 * 1024)
        assert len(batches) == 0

    def test_respects_size_limit(self):
        # Create entries that are ~1KB each, with a 3KB limit to force splitting
        entries = []
        for i in range(10):
            entries.append({"msg": "x" * 800, "i": i, "_lm.resourceId": {}})
        batches = assemble_batches(entries, max_bytes=3000)
        assert len(batches) > 1
        for batch in batches:
            assert len(json.dumps(batch).encode("utf-8")) <= 3000

    def test_single_oversized_entry_gets_own_batch(self):
        # An entry that alone exceeds the limit still gets its own batch
        entries = [{"msg": "x" * 5000, "_lm.resourceId": {}}]
        batches = assemble_batches(entries, max_bytes=1000)
        assert len(batches) == 1


class TestParseFlowRecordsFromJson:
    """Test parsing the full PT1H.json structure into flat LM log entries."""

    def test_parse_sample_json(self):
        entries = parse_flow_records_from_json(
            SAMPLE_FLOW_LOG_JSON,
            vnet_resource_id=VNET_RESOURCE_ID,
        )
        assert len(entries) == 2
        # First tuple is SAMPLE_TUPLE_E
        assert entries[0]["srcIP"] == "10.0.0.4"
        assert entries[0]["flowState"] == "end"
        assert entries[0]["rule"] == "DefaultRule_AllowInternetOutBound"
        assert entries[0]["macAddress"] == "000D3A123456"
        # Second tuple is SAMPLE_TUPLE_B
        assert entries[1]["flowState"] == "begin"

    def test_empty_records(self):
        entries = parse_flow_records_from_json({"records": []}, vnet_resource_id=VNET_RESOURCE_ID)
        assert len(entries) == 0

    def test_missing_flow_records(self):
        data = {"records": [{"time": "2024-01-01", "flowRecords": {"flows": []}}]}
        entries = parse_flow_records_from_json(data, vnet_resource_id=VNET_RESOURCE_ID)
        assert len(entries) == 0

    def test_preserves_target_resource_id_from_blob(self):
        entries = parse_flow_records_from_json(
            SAMPLE_FLOW_LOG_JSON,
            vnet_resource_id=VNET_RESOURCE_ID,
        )
        for entry in entries:
            assert entry["_lm.resourceId"]["azure.resourceid"] == VNET_RESOURCE_ID
