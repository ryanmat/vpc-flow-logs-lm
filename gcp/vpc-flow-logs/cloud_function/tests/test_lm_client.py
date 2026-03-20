# Description: Tests for the LogicMonitor API client.
# Description: Covers Ingest API, request format, auth headers, and error handling.
import json

import pytest
import responses

from cloud_function.config import Config
from cloud_function.lm_client import LMClient


@pytest.fixture
def ingest_config():
    """Config for Phase 1 Ingest API path."""
    return Config(
        lm_company_name="testportal",
        lm_access_id="test_access_id",
        lm_access_key="test_access_key",
        use_webhook=False,
    )


@pytest.fixture
def ingest_client(ingest_config):
    return LMClient(ingest_config)


INGEST_URL = "https://testportal.logicmonitor.com/rest/log/ingest"


class TestSendToIngestApi:
    """Test LMClient.send_to_ingest_api."""

    @responses.activate
    def test_successful_post_returns_true(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={"success": True}, status=202)

        payloads = [{"msg": "test log", "src_ip": "10.0.0.1"}]
        result = ingest_client.send_to_ingest_api(payloads)

        assert result is True

    @responses.activate
    def test_sends_json_array(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        payloads = [
            {"msg": "log one", "src_ip": "10.0.0.1"},
            {"msg": "log two", "src_ip": "10.0.0.2"},
        ]
        ingest_client.send_to_ingest_api(payloads)

        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, list)
        assert len(body) == 2
        assert body[0]["msg"] == "log one"

    @responses.activate
    def test_auth_header_is_lmv1(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        ingest_client.send_to_ingest_api([{"msg": "test"}])

        auth_header = responses.calls[0].request.headers["Authorization"]
        assert auth_header.startswith("LMv1 test_access_id:")

    @responses.activate
    def test_content_type_is_json(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        ingest_client.send_to_ingest_api([{"msg": "test"}])

        assert "application/json" in responses.calls[0].request.headers["Content-Type"]

    @responses.activate
    def test_url_constructed_from_config(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        ingest_client.send_to_ingest_api([{"msg": "test"}])

        assert responses.calls[0].request.url == INGEST_URL

    @responses.activate
    def test_custom_domain_in_url(self):
        config = Config(
            lm_company_name="euportal",
            lm_access_id="id",
            lm_access_key="key",
            lm_company_domain="logicmonitor.eu",
        )
        client = LMClient(config)
        eu_url = "https://euportal.logicmonitor.eu/rest/log/ingest"
        responses.add(responses.POST, eu_url, json={}, status=200)

        client.send_to_ingest_api([{"msg": "test"}])

        assert responses.calls[0].request.url == eu_url

    @responses.activate
    def test_401_returns_false(self, ingest_client):
        responses.add(
            responses.POST, INGEST_URL, json={"error": "unauthorized"}, status=401
        )

        result = ingest_client.send_to_ingest_api([{"msg": "test"}])

        assert result is False

    @responses.activate
    def test_500_returns_false(self, ingest_client):
        responses.add(
            responses.POST, INGEST_URL, json={"error": "server error"}, status=500
        )

        result = ingest_client.send_to_ingest_api([{"msg": "test"}])

        assert result is False

    @responses.activate
    def test_200_returns_true(self, ingest_client):
        responses.add(responses.POST, INGEST_URL, json={"success": True}, status=200)

        result = ingest_client.send_to_ingest_api([{"msg": "test"}])

        assert result is True


class TestIngestIntegration:
    """Integration test: parser output -> LM client."""

    @responses.activate
    def test_parser_output_compatible_with_client(self, cloud_event_vm, ingest_config):
        """Verify the parser output can be sent through the LM client."""
        from cloud_function.flow_log_parser import (
            extract_flow_log,
            extract_metadata,
            extract_resource_id,
            format_ingest_api_payload,
            parse_pubsub_message,
        )

        responses.add(responses.POST, INGEST_URL, json={}, status=202)

        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        resource_id = extract_resource_id(flow_log)
        metadata = extract_metadata(flow_log)
        payload = format_ingest_api_payload(flow_log, resource_id, metadata)

        client = LMClient(ingest_config)
        result = client.send_to_ingest_api([payload])

        assert result is True

        # Verify the request body structure
        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, list)
        assert len(body) == 1
        assert "msg" in body[0]
        assert "_lm.resourceId" in body[0]
        assert body[0]["_lm.resourceId"]["system.hostname"] == "web-frontend-01"


# --- Phase 5: Webhook tests ---

WEBHOOK_URL = "https://testportal.logicmonitor.com/rest/api/v1/webhook/ingest/GCP-VPC-FlowLogs"


@pytest.fixture
def webhook_config():
    """Config for Phase 2 Webhook path."""
    return Config(
        lm_company_name="testportal",
        lm_bearer_token="test_bearer_token_xyz",
        use_webhook=True,
    )


@pytest.fixture
def webhook_client(webhook_config):
    return LMClient(webhook_config)


class TestSendToWebhook:
    """Test LMClient.send_to_webhook."""

    @responses.activate
    def test_successful_post_returns_true(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={"success": True}, status=200)

        payload = {"message": "test", "src_ip": "10.0.0.1"}
        result = webhook_client.send_to_webhook(payload)

        assert result is True

    @responses.activate
    def test_sends_single_json_object(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        payload = {"message": "test log", "src_ip": "10.0.0.1", "protocol": 6}
        webhook_client.send_to_webhook(payload)

        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, dict)  # Single object, NOT array
        assert body["message"] == "test log"

    @responses.activate
    def test_auth_header_is_bearer(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        webhook_client.send_to_webhook({"message": "test"})

        auth_header = responses.calls[0].request.headers["Authorization"]
        assert auth_header == "Bearer test_bearer_token_xyz"

    @responses.activate
    def test_url_contains_source_name(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        webhook_client.send_to_webhook({"message": "test"})

        assert "GCP-VPC-FlowLogs" in responses.calls[0].request.url

    @responses.activate
    def test_custom_source_name_in_url(self):
        config = Config(
            lm_company_name="testportal",
            lm_bearer_token="tok",
            webhook_source_name="GCP-VPC-FlowLogs-ProjectX",
            use_webhook=True,
        )
        client = LMClient(config)
        custom_url = "https://testportal.logicmonitor.com/rest/api/v1/webhook/ingest/GCP-VPC-FlowLogs-ProjectX"
        responses.add(responses.POST, custom_url, json={}, status=200)

        client.send_to_webhook({"message": "test"})

        assert "GCP-VPC-FlowLogs-ProjectX" in responses.calls[0].request.url

    @responses.activate
    def test_401_returns_false(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={"error": "bad token"}, status=401)

        result = webhook_client.send_to_webhook({"message": "test"})

        assert result is False

    @responses.activate
    def test_500_returns_false(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=500)

        result = webhook_client.send_to_webhook({"message": "test"})

        assert result is False

    @responses.activate
    def test_content_type_is_json(self, webhook_client):
        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        webhook_client.send_to_webhook({"message": "test"})

        assert "application/json" in responses.calls[0].request.headers["Content-Type"]


class TestWebhookIntegration:
    """Integration test: parser output -> webhook client."""

    @responses.activate
    def test_parser_output_compatible_with_webhook(self, cloud_event_vm, webhook_config):
        from cloud_function.flow_log_parser import (
            extract_flow_log,
            format_webhook_payload,
            parse_pubsub_message,
        )

        responses.add(responses.POST, WEBHOOK_URL, json={}, status=200)

        log_entry = parse_pubsub_message(cloud_event_vm)
        flow_log = extract_flow_log(log_entry)
        payload = format_webhook_payload(flow_log, log_entry)

        client = LMClient(webhook_config)
        result = client.send_to_webhook(payload)

        assert result is True

        body = json.loads(responses.calls[0].request.body)
        assert isinstance(body, dict)
        assert "message" in body
        assert body["src_ip"] == "10.128.0.15"
        assert "connection" in body

        auth = responses.calls[0].request.headers["Authorization"]
        assert auth == "Bearer test_bearer_token_xyz"
