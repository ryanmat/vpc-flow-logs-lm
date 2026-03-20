# Description: Tests for the configuration module.
# Description: Validates environment variable loading, defaults, and validation.
import os

import pytest

from cloud_function.config import Config, load_config


class TestConfigDataclass:
    """Verify Config dataclass holds the expected fields and defaults."""

    def test_config_has_all_fields(self):
        config = Config(
            lm_company_name="testportal",
            lm_bearer_token="tok_abc123",
            lm_access_id="id_123",
            lm_access_key="key_456",
        )
        assert config.lm_company_name == "testportal"
        assert config.lm_bearer_token == "tok_abc123"
        assert config.lm_access_id == "id_123"
        assert config.lm_access_key == "key_456"

    def test_config_default_domain(self):
        config = Config(lm_company_name="testportal")
        assert config.lm_company_domain == "logicmonitor.com"

    def test_config_default_webhook_source_name(self):
        config = Config(lm_company_name="testportal")
        assert config.webhook_source_name == "GCP-VPC-FlowLogs"

    def test_config_default_use_webhook_is_false(self):
        config = Config(lm_company_name="testportal")
        assert config.use_webhook is False


class TestLoadConfig:
    """Verify load_config reads environment variables correctly."""

    def test_load_from_env_vars(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_BEARER_TOKEN", "bearer_xyz")
        monkeypatch.setenv("LM_ACCESS_ID", "acc_id")
        monkeypatch.setenv("LM_ACCESS_KEY", "acc_key")
        monkeypatch.setenv("USE_WEBHOOK", "true")

        config = load_config()

        assert config.lm_company_name == "acmecorp"
        assert config.lm_bearer_token == "bearer_xyz"
        assert config.lm_access_id == "acc_id"
        assert config.lm_access_key == "acc_key"
        assert config.use_webhook is True

    def test_load_custom_domain(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_COMPANY_DOMAIN", "logicmonitor.eu")
        monkeypatch.setenv("LM_ACCESS_ID", "id")
        monkeypatch.setenv("LM_ACCESS_KEY", "key")

        config = load_config()

        assert config.lm_company_domain == "logicmonitor.eu"

    def test_load_custom_webhook_source_name(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("WEBHOOK_SOURCE_NAME", "GCP-VPC-FlowLogs-ProjectX")
        monkeypatch.setenv("LM_ACCESS_ID", "id")
        monkeypatch.setenv("LM_ACCESS_KEY", "key")

        config = load_config()

        assert config.webhook_source_name == "GCP-VPC-FlowLogs-ProjectX"

    def test_missing_company_name_raises_error(self, monkeypatch):
        monkeypatch.delenv("LM_COMPANY_NAME", raising=False)

        with pytest.raises(ValueError, match="LM_COMPANY_NAME"):
            load_config()

    def test_use_webhook_false_variants(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_ACCESS_ID", "id")
        monkeypatch.setenv("LM_ACCESS_KEY", "key")

        for val in ("false", "False", "FALSE", "0", "no"):
            monkeypatch.setenv("USE_WEBHOOK", val)
            config = load_config()
            assert config.use_webhook is False

    def test_use_webhook_true_variants(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_BEARER_TOKEN", "tok")

        for val in ("true", "True", "TRUE", "1", "yes"):
            monkeypatch.setenv("USE_WEBHOOK", val)
            config = load_config()
            assert config.use_webhook is True

    def test_defaults_with_ingest_credentials(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_ACCESS_ID", "id")
        monkeypatch.setenv("LM_ACCESS_KEY", "key")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)
        monkeypatch.delenv("LM_COMPANY_DOMAIN", raising=False)
        monkeypatch.delenv("WEBHOOK_SOURCE_NAME", raising=False)
        monkeypatch.delenv("USE_WEBHOOK", raising=False)

        config = load_config()

        assert config.lm_company_name == "acmecorp"
        assert config.lm_company_domain == "logicmonitor.com"
        assert config.webhook_source_name == "GCP-VPC-FlowLogs"
        assert config.use_webhook is False


class TestConfigValidation:
    """Verify config validation catches mismatched credential settings."""

    def test_webhook_mode_requires_bearer_token(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("USE_WEBHOOK", "true")
        monkeypatch.delenv("LM_BEARER_TOKEN", raising=False)

        with pytest.raises(ValueError, match="LM_BEARER_TOKEN"):
            load_config()

    def test_ingest_mode_requires_access_credentials(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("USE_WEBHOOK", "false")
        monkeypatch.delenv("LM_ACCESS_ID", raising=False)
        monkeypatch.delenv("LM_ACCESS_KEY", raising=False)

        with pytest.raises(ValueError, match="LM_ACCESS_ID"):
            load_config()

    def test_webhook_mode_with_token_passes(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_BEARER_TOKEN", "valid_token")
        monkeypatch.setenv("USE_WEBHOOK", "true")

        config = load_config()
        assert config.use_webhook is True
        assert config.lm_bearer_token == "valid_token"

    def test_ingest_mode_with_credentials_passes(self, monkeypatch):
        monkeypatch.setenv("LM_COMPANY_NAME", "acmecorp")
        monkeypatch.setenv("LM_ACCESS_ID", "id")
        monkeypatch.setenv("LM_ACCESS_KEY", "key")
        monkeypatch.setenv("USE_WEBHOOK", "false")

        config = load_config()
        assert config.use_webhook is False
