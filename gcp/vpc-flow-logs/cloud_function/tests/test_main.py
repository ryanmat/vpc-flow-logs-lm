# Description: Tests for the Cloud Function entry point.
# Description: Validates handle_pubsub processes CloudEvents and calls the LM client.
import json

import pytest

from cloud_function.tests.conftest import build_cloud_event


class TestHandlePubsub:
    """Test the Cloud Function entry point."""

    def test_processes_valid_cloud_event(self, monkeypatch, flow_log_src_vm):
        """Valid CloudEvent is parsed and sent to LM."""
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_ACCESS_ID", "test_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "test_key")
        monkeypatch.setenv("USE_WEBHOOK", "false")

        sent_payloads = []

        # Patch the LMClient at module level
        import cloud_function.main as main_module

        # Force re-initialization
        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_ingest_api(self, payloads):
                sent_payloads.extend(payloads)
                return True

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_src_vm)
        main_module.handle_pubsub(event)

        assert len(sent_payloads) == 1
        assert "msg" in sent_payloads[0]
        assert "_lm.resourceId" in sent_payloads[0]

    def test_malformed_message_does_not_crash(self, monkeypatch):
        """Malformed messages are logged but don't raise."""
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_ACCESS_ID", "test_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "test_key")

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        bad_event = {"data": {"message": {"data": "not-valid-base64!!!"}}}

        # Should not raise
        main_module.handle_pubsub(bad_event)

    def test_calls_ingest_api_with_correct_payload(self, monkeypatch, flow_log_src_vm):
        """Verify the payload sent to LM contains expected fields."""
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_ACCESS_ID", "test_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "test_key")
        monkeypatch.setenv("USE_WEBHOOK", "false")

        captured = []

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_ingest_api(self, payloads):
                captured.extend(payloads)
                return True

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_src_vm)
        main_module.handle_pubsub(event)

        payload = captured[0]
        assert payload["src_ip"] == "10.128.0.15"
        assert payload["dest_ip"] == "10.128.0.22"
        assert payload["_lm.resourceId"]["system.hostname"] == "web-frontend-01"
        assert "VPC Flow:" in payload["msg"]

    def test_external_traffic_has_resource_id_from_dest(
        self, monkeypatch, flow_log_external
    ):
        """External traffic uses dest_instance for resource mapping."""
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_ACCESS_ID", "test_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "test_key")
        monkeypatch.setenv("USE_WEBHOOK", "false")

        captured = []

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_ingest_api(self, payloads):
                captured.extend(payloads)
                return True

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_external)
        main_module.handle_pubsub(event)

        payload = captured[0]
        assert payload["_lm.resourceId"]["system.hostname"] == "api-backend-02"


class TestHandlePubsubWebhook:
    """Test the webhook path in handle_pubsub."""

    def test_webhook_mode_calls_send_to_webhook(self, monkeypatch, flow_log_src_vm):
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("USE_WEBHOOK", "true")

        captured = []

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_webhook(self, payload):
                captured.append(payload)
                return True

            def send_to_ingest_api(self, payloads):
                raise AssertionError("Should not call ingest API in webhook mode")

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_src_vm)
        main_module.handle_pubsub(event)

        assert len(captured) == 1
        assert isinstance(captured[0], dict)
        assert "message" in captured[0]
        assert captured[0]["src_ip"] == "10.128.0.15"

    def test_webhook_payload_is_single_dict(self, monkeypatch, flow_log_src_vm):
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_BEARER_TOKEN", "test_token")
        monkeypatch.setenv("USE_WEBHOOK", "true")

        captured = []

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_webhook(self, payload):
                captured.append(payload)
                return True

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_src_vm)
        main_module.handle_pubsub(event)

        # Webhook gets a single dict, not a list
        assert not isinstance(captured[0], list)
        assert isinstance(captured[0], dict)

    def test_ingest_mode_does_not_call_webhook(self, monkeypatch, flow_log_src_vm):
        monkeypatch.setenv("LM_COMPANY_NAME", "testportal")
        monkeypatch.setenv("LM_ACCESS_ID", "test_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "test_key")
        monkeypatch.setenv("USE_WEBHOOK", "false")

        captured_ingest = []

        import cloud_function.main as main_module

        main_module._initialized = False

        class FakeLMClient:
            def __init__(self, config):
                pass

            def send_to_ingest_api(self, payloads):
                captured_ingest.extend(payloads)
                return True

            def send_to_webhook(self, payload):
                raise AssertionError("Should not call webhook in ingest mode")

        monkeypatch.setattr(main_module, "LMClient", FakeLMClient)
        main_module._init()

        event = build_cloud_event(flow_log_src_vm)
        main_module.handle_pubsub(event)

        assert len(captured_ingest) == 1
