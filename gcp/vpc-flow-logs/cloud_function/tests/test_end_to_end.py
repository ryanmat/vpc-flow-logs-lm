# Description: End-to-end tests covering the full pipeline for both LM endpoints.
# Description: Validates CloudEvent -> parse -> format -> HTTP send for all scenarios.
import json

import pytest
import responses

from cloud_function.config import Config
from cloud_function.flow_log_parser import (
    extract_flow_log,
    extract_metadata,
    extract_resource_id,
    format_ingest_api_payload,
    format_webhook_payload,
    parse_pubsub_message,
)
from cloud_function.lm_client import LMClient
from cloud_function.tests.conftest import build_cloud_event

INGEST_URL = "https://testportal.logicmonitor.com/rest/log/ingest"
WEBHOOK_URL = "https://testportal.logicmonitor.com/rest/api/v1/webhook/ingest/GCP-VPC-FlowLogs"


@pytest.fixture
def ingest_client():
    config = Config(
        lm_company_name="testportal",
        lm_access_id="test_id",
        lm_access_key="test_key",
        use_webhook=False,
    )
    return LMClient(config)


@pytest.fixture
def webhook_client():
    config = Config(
        lm_company_name="testportal",
        lm_bearer_token="test_token",
        use_webhook=True,
    )
    return LMClient(config)


class TestVmToVmEndToEnd:
    """Full pipeline for VM-to-VM internal traffic."""

    @responses.activate
    def test_ingest_api_path(self, cloud_event_vm, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        result = ingest_client.send_to_ingest_api([payload])

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, list)
        assert body[0]["_lm.resourceId"]["system.hostname"] == "web-frontend-01"
        assert "VPC Flow:" in body[0]["msg"]

    @responses.activate
    def test_webhook_path(self, cloud_event_vm, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        result = webhook_client.send_to_webhook(payload)

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, dict)
        assert body["src_ip"] == "10.128.0.15"
        assert body["connection"]["protocol"] == 6
        assert body["src_instance"]["vm_name"] == "web-frontend-01"

    def test_resource_id_present(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        assert resource_id is not None
        assert resource_id["system.hostname"] == "web-frontend-01"


class TestExternalTrafficEndToEnd:
    """Full pipeline for external-to-internal traffic."""

    @responses.activate
    def test_ingest_api_path(self, cloud_event_external, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        log_entry = parse_pubsub_message(cloud_event_external)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        result = ingest_client.send_to_ingest_api([payload])

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        # Falls back to dest_instance
        assert body[0]["_lm.resourceId"]["system.hostname"] == "api-backend-02"
        assert body[0]["src_ip"] == "203.0.113.45"

    @responses.activate
    def test_webhook_path(self, cloud_event_external, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        log_entry = parse_pubsub_message(cloud_event_external)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        result = webhook_client.send_to_webhook(payload)

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, dict)
        assert "src_instance" not in body
        assert body["dest_instance"]["vm_name"] == "api-backend-02"
        assert body["src_location"]["asn"] == 14618

    def test_resource_id_falls_back_to_dest(self, cloud_event_external):
        log_entry = parse_pubsub_message(cloud_event_external)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        assert resource_id == {"system.hostname": "api-backend-02"}


class TestGkeTrafficEndToEnd:
    """Full pipeline for GKE pod-to-pod traffic."""

    @responses.activate
    def test_webhook_includes_gke_details(self, flow_log_gke, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        event = build_cloud_event(flow_log_gke)
        log_entry = parse_pubsub_message(event)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        result = webhook_client.send_to_webhook(payload)

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert "src_gke_details" in body
        assert "dest_gke_details" in body
        assert body["src_gke_details"]["pod"]["pod_name"] == "frontend-7b8d9c6f4-xk2qm"
        assert len(body["dest_gke_details"]["service"]) == 2

    @responses.activate
    def test_ingest_api_uses_node_vm(self, flow_log_gke, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        event = build_cloud_event(flow_log_gke)
        log_entry = parse_pubsub_message(event)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        result = ingest_client.send_to_ingest_api([payload])

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert body[0]["_lm.resourceId"]["system.hostname"] == "gke-prod-cluster-node-pool-a1b2c3d4-wxyz"


class TestPayloadFormatDifferences:
    """Verify structural differences between Ingest API and Webhook payloads."""

    def test_ingest_uses_array_webhook_uses_object(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)

        ingest_payload = format_ingest_api_payload(flow_log, resource_id, metadata)
        webhook_payload = format_webhook_payload(flow_log, log_entry)

        # Ingest API wraps in array for transport
        ingest_body = [ingest_payload]
        assert isinstance(ingest_body, list)

        # Webhook is a single object
        assert isinstance(webhook_payload, dict)

    def test_all_metadata_fields_present(self, cloud_event_vm):
        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        metadata = extract_metadata(flow_log)
        webhook_payload = format_webhook_payload(flow_log, log_entry)

        # Both should have the key fields
        for key in ("src_ip", "dest_ip", "protocol", "bytes_sent", "reporter"):
            assert key in metadata, f"Missing {key} in metadata"
            assert key in webhook_payload, f"Missing {key} in webhook payload"
