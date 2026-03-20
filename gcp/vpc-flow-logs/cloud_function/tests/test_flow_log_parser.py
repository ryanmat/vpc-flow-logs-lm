# Description: Tests for the VPC Flow Log parser module.
# Description: Covers message parsing, field extraction, formatters, and edge cases.
import base64
import json

import pytest

from cloud_function.flow_log_parser import (
    extract_flow_log,
    extract_metadata,
    extract_resource_id,
    format_ingest_api_payload,
    format_webhook_payload,
    parse_pubsub_message,
)
from cloud_function.tests.conftest import build_cloud_event


class TestParsePubsubMessage:
    """Test CloudEvent -> LogEntry parsing."""

    def test_extracts_log_entry_from_cloud_event(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        assert "insertId" in log_entry
        assert "jsonPayload" in log_entry
        assert "resource" in log_entry

    def test_extracts_log_entry_from_external_event(self, cloud_event_external):
        log_entry = parse_pubsub_message(cloud_event_external)
        assert "jsonPayload" in log_entry

    def test_raises_on_missing_data_field(self):
        bad_event = {"specversion": "1.0", "type": "test"}
        with pytest.raises(ValueError, match="data"):
            parse_pubsub_message(bad_event)

    def test_raises_on_missing_message_field(self):
        bad_event = {"data": {"subscription": "test"}}
        with pytest.raises(ValueError, match="message"):
            parse_pubsub_message(bad_event)

    def test_raises_on_missing_message_data(self):
        bad_event = {"data": {"message": {"messageId": "123"}}}
        with pytest.raises(ValueError, match="data"):
            parse_pubsub_message(bad_event)

    def test_raises_on_invalid_base64(self):
        bad_event = {"data": {"message": {"data": "!!!not-base64!!!"}}}
        with pytest.raises(ValueError, match="decode"):
            parse_pubsub_message(bad_event)

    def test_raises_on_invalid_json_after_decode(self):
        not_json = base64.b64encode(b"this is not json").decode("utf-8")
        bad_event = {"data": {"message": {"data": not_json}}}
        with pytest.raises(ValueError, match="JSON"):
            parse_pubsub_message(bad_event)

    def test_round_trips_via_build_helper(self, flow_log_src_vm):
        event = build_cloud_event(flow_log_src_vm)
        log_entry = parse_pubsub_message(event)
        assert log_entry["jsonPayload"] == flow_log_src_vm


class TestExtractFlowLog:
    """Test LogEntry -> flow log extraction."""

    def test_extracts_json_payload(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        assert "connection" in flow_log
        assert "bytes_sent" in flow_log

    def test_raises_on_missing_json_payload(self):
        log_entry = {"insertId": "abc", "resource": {}}
        with pytest.raises(ValueError, match="jsonPayload"):
            extract_flow_log(log_entry)

    def test_raises_on_empty_json_payload(self):
        log_entry = {"jsonPayload": {}}
        with pytest.raises(ValueError, match="empty"):
            extract_flow_log(log_entry)


class TestExtractResourceId:
    """Test resource ID extraction for LM device mapping."""

    def test_returns_src_vm_name_when_present(self, flow_log_src_vm):
        result = extract_resource_id(flow_log_src_vm)
        assert result == {"system.hostname": "web-frontend-01"}

    def test_falls_back_to_dest_vm_name(self, flow_log_external):
        result = extract_resource_id(flow_log_external)
        assert result == {"system.hostname": "api-backend-02"}

    def test_returns_none_when_no_instances(self):
        flow_log = {
            "connection": {"src_ip": "8.8.8.8", "dest_ip": "1.1.1.1"},
            "bytes_sent": "100",
        }
        result = extract_resource_id(flow_log)
        assert result is None

    def test_prefers_src_over_dest(self, flow_log_src_vm):
        """When both are present, src_instance takes priority."""
        result = extract_resource_id(flow_log_src_vm)
        assert result["system.hostname"] == "web-frontend-01"

    def test_gke_uses_node_vm_name(self, flow_log_gke):
        result = extract_resource_id(flow_log_gke)
        assert result == {
            "system.hostname": "gke-prod-cluster-node-pool-a1b2c3d4-wxyz"
        }


class TestExtractMetadata:
    """Test metadata extraction for log enrichment."""

    def test_extracts_connection_fields(self, flow_log_src_vm):
        meta = extract_metadata(flow_log_src_vm)
        assert meta["src_ip"] == "10.128.0.15"
        assert meta["dest_ip"] == "10.128.0.22"
        assert meta["src_port"] == 443
        assert meta["dest_port"] == 52340
        assert meta["protocol"] == 6

    def test_extracts_traffic_fields(self, flow_log_src_vm):
        meta = extract_metadata(flow_log_src_vm)
        assert meta["bytes_sent"] == "15234"
        assert meta["packets_sent"] == "42"
        assert meta["reporter"] == "SRC"

    def test_extracts_vm_name(self, flow_log_src_vm):
        meta = extract_metadata(flow_log_src_vm)
        assert meta["vm_name"] == "web-frontend-01"

    def test_extracts_vpc_fields(self, flow_log_src_vm):
        meta = extract_metadata(flow_log_src_vm)
        assert meta["vpc_name"] == "acme-prod-vpc"
        assert meta["subnet_name"] == "web-tier-subnet"

    def test_extracts_project_id(self, flow_log_src_vm):
        meta = extract_metadata(flow_log_src_vm)
        assert meta["project_id"] == "acme-prod-123456"

    def test_handles_missing_src_instance(self, flow_log_external):
        meta = extract_metadata(flow_log_external)
        assert "vm_name" not in meta
        assert "project_id" not in meta
        assert meta["src_ip"] == "203.0.113.45"

    def test_handles_missing_src_vpc(self, flow_log_external):
        meta = extract_metadata(flow_log_external)
        assert "vpc_name" not in meta
        assert "subnet_name" not in meta

    def test_extracts_gke_fields(self, flow_log_gke):
        meta = extract_metadata(flow_log_gke)
        assert meta["src_ip"] == "10.128.1.50"
        assert meta["vm_name"] == "gke-prod-cluster-node-pool-a1b2c3d4-wxyz"

    def test_handles_minimal_flow_log(self):
        """A flow log with only connection data and no metadata annotations."""
        minimal = {
            "connection": {
                "src_ip": "10.0.0.1",
                "dest_ip": "10.0.0.2",
                "src_port": 80,
                "dest_port": 12345,
                "protocol": 6,
            },
            "bytes_sent": "500",
            "packets_sent": "5",
            "reporter": "SRC",
        }
        meta = extract_metadata(minimal)
        assert meta["src_ip"] == "10.0.0.1"
        assert meta["bytes_sent"] == "500"
        assert "vm_name" not in meta
        assert "vpc_name" not in meta
        assert "project_id" not in meta


class TestFormatIngestApiPayload:
    """Test LM Ingest API payload formatting."""

    def test_has_msg_field(self, flow_log_src_vm):
        resource_id = extract_resource_id(flow_log_src_vm)
        metadata = extract_metadata(flow_log_src_vm)
        payload = format_ingest_api_payload(flow_log_src_vm, resource_id, metadata)
        assert "msg" in payload
        assert isinstance(payload["msg"], str)

    def test_msg_contains_summary(self, flow_log_src_vm):
        resource_id = extract_resource_id(flow_log_src_vm)
        metadata = extract_metadata(flow_log_src_vm)
        payload = format_ingest_api_payload(flow_log_src_vm, resource_id, metadata)
        assert "10.128.0.15" in payload["msg"]
        assert "10.128.0.22" in payload["msg"]

    def test_includes_resource_id(self, flow_log_src_vm):
        resource_id = extract_resource_id(flow_log_src_vm)
        metadata = extract_metadata(flow_log_src_vm)
        payload = format_ingest_api_payload(flow_log_src_vm, resource_id, metadata)
        assert payload["_lm.resourceId"] == {"system.hostname": "web-frontend-01"}

    def test_omits_resource_id_when_none(self, flow_log_external):
        metadata = extract_metadata(flow_log_external)
        payload = format_ingest_api_payload(flow_log_external, None, metadata)
        assert "_lm.resourceId" not in payload

    def test_includes_metadata_fields(self, flow_log_src_vm):
        resource_id = extract_resource_id(flow_log_src_vm)
        metadata = extract_metadata(flow_log_src_vm)
        payload = format_ingest_api_payload(flow_log_src_vm, resource_id, metadata)
        assert payload["src_ip"] == "10.128.0.15"
        assert payload["protocol"] == 6
        assert payload["bytes_sent"] == "15234"

    def test_external_traffic_payload(self, flow_log_external):
        resource_id = extract_resource_id(flow_log_external)
        metadata = extract_metadata(flow_log_external)
        payload = format_ingest_api_payload(flow_log_external, resource_id, metadata)
        # Falls back to dest_instance, so resource_id should be present
        assert payload["_lm.resourceId"] == {"system.hostname": "api-backend-02"}
        assert "203.0.113.45" in payload["msg"]


class TestFormatWebhookPayload:
    """Test LM Webhook payload formatting."""

    def test_is_single_dict(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert isinstance(payload, dict)

    def test_has_message_field(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert "message" in payload
        assert isinstance(payload["message"], str)

    def test_preserves_nested_connection(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert "connection" in payload
        assert payload["connection"]["src_ip"] == "10.128.0.15"

    def test_has_convenience_top_level_keys(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert payload["src_ip"] == "10.128.0.15"
        assert payload["dest_ip"] == "10.128.0.22"
        assert payload["src_port"] == 443
        assert payload["protocol"] == 6

    def test_includes_traffic_fields(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert payload["bytes_sent"] == "15234"
        assert payload["packets_sent"] == "42"
        assert payload["reporter"] == "SRC"

    def test_includes_instance_fields(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert "src_instance" in payload
        assert "dest_instance" in payload

    def test_includes_vpc_fields(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert "src_vpc" in payload
        assert "dest_vpc" in payload

    def test_includes_gke_details(self, flow_log_gke):
        log_entry = {"jsonPayload": flow_log_gke, "timestamp": "2026-02-26T12:00:00Z"}
        payload = format_webhook_payload(flow_log_gke, log_entry)
        assert "src_gke_details" in payload
        assert "dest_gke_details" in payload

    def test_external_traffic_no_src_instance(self, flow_log_external, cloud_event_external):
        log_entry = parse_pubsub_message(cloud_event_external)
        payload = format_webhook_payload(flow_log_external, log_entry)
        assert "src_instance" not in payload
        assert "dest_instance" in payload
        assert "src_location" in payload

    def test_includes_log_entry_timestamp(self, flow_log_src_vm, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        payload = format_webhook_payload(flow_log_src_vm, log_entry)
        assert "timestamp" in payload


class TestFullParsePipeline:
    """Integration tests: raw CloudEvent through full parse and format pipeline."""

    def test_vm_to_vm_ingest_pipeline(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        assert payload["msg"].startswith("VPC Flow:")
        assert payload["_lm.resourceId"] == {"system.hostname": "web-frontend-01"}
        assert payload["src_ip"] == "10.128.0.15"
        assert payload["dest_ip"] == "10.128.0.22"
        assert payload["protocol"] == 6
        assert payload["bytes_sent"] == "15234"

    def test_vm_to_vm_webhook_pipeline(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        assert isinstance(payload, dict)
        assert "message" in payload
        assert payload["src_ip"] == "10.128.0.15"
        assert payload["connection"]["dest_port"] == 52340
        assert "src_instance" in payload
        assert payload["src_instance"]["vm_name"] == "web-frontend-01"
        assert "timestamp" in payload

    def test_external_traffic_ingest_pipeline(self, cloud_event_external):
        log_entry = parse_pubsub_message(cloud_event_external)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        # External traffic falls back to dest_instance for resource mapping
        assert payload["_lm.resourceId"] == {"system.hostname": "api-backend-02"}
        assert payload["src_ip"] == "203.0.113.45"
        assert "vm_name" not in payload  # No src_instance

    def test_external_traffic_webhook_pipeline(self, cloud_event_external):
        log_entry = parse_pubsub_message(cloud_event_external)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        assert isinstance(payload, dict)
        assert "src_instance" not in payload
        assert "dest_instance" in payload
        assert "src_location" in payload
        assert payload["src_location"]["asn"] == 14618

    def test_gke_traffic_via_build_helper(self, flow_log_gke):
        """GKE flow log through full pipeline using build_cloud_event helper."""
        event = build_cloud_event(flow_log_gke)
        log_entry = parse_pubsub_message(event)
        flow_log = extract_flow_log(log_entry)

        resource_id = extract_resource_id(flow_log)
        assert resource_id == {
            "system.hostname": "gke-prod-cluster-node-pool-a1b2c3d4-wxyz"
        }

        webhook_payload = format_webhook_payload(flow_log, log_entry)
        assert "src_gke_details" in webhook_payload
        assert webhook_payload["src_gke_details"]["pod"]["pod_name"] == "frontend-7b8d9c6f4-xk2qm"
        assert len(webhook_payload["dest_gke_details"]["service"]) == 2
