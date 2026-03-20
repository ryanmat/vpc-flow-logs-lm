# Description: Configuration loading for the GCP VPC Flow Logs Cloud Function.
# Description: Reads settings from environment variables with Secret Manager fallback.
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """Holds all configuration for the LM relay Cloud Function."""

    lm_company_name: str
    lm_bearer_token: str | None = None
    lm_access_id: str | None = None
    lm_access_key: str | None = None
    lm_company_domain: str = "logicmonitor.com"
    webhook_source_name: str = "GCP-VPC-FlowLogs"
    use_webhook: bool = False


def _parse_bool(value: str) -> bool:
    """Parse a string to a boolean value."""
    return value.lower() in ("true", "1", "yes")


def load_config() -> Config:
    """Load configuration from environment variables.

    Falls back to GCP Secret Manager if env vars are not set
    and the function is running in a GCP environment.
    Raises ValueError if required values are missing from all sources.
    """
    lm_company_name = os.environ.get("LM_COMPANY_NAME")
    if not lm_company_name:
        lm_company_name = _load_from_secret_manager("lm-company-name")
    if not lm_company_name:
        raise ValueError(
            "LM_COMPANY_NAME must be set as an environment variable "
            "or available in GCP Secret Manager"
        )

    lm_bearer_token = os.environ.get("LM_BEARER_TOKEN")
    if not lm_bearer_token:
        lm_bearer_token = _load_from_secret_manager("lm-bearer-token")

    lm_access_id = os.environ.get("LM_ACCESS_ID")
    lm_access_key = os.environ.get("LM_ACCESS_KEY")

    lm_company_domain = os.environ.get("LM_COMPANY_DOMAIN", "logicmonitor.com")
    webhook_source_name = os.environ.get("WEBHOOK_SOURCE_NAME", "GCP-VPC-FlowLogs")

    use_webhook_str = os.environ.get("USE_WEBHOOK", "false")
    use_webhook = _parse_bool(use_webhook_str)

    config = Config(
        lm_company_name=lm_company_name,
        lm_bearer_token=lm_bearer_token,
        lm_access_id=lm_access_id,
        lm_access_key=lm_access_key,
        lm_company_domain=lm_company_domain,
        webhook_source_name=webhook_source_name,
        use_webhook=use_webhook,
    )

    _validate_config(config)
    return config


def _validate_config(config: Config) -> None:
    """Validate that the config has the required credentials for the selected mode.

    Raises ValueError if required credentials are missing.
    """
    if config.use_webhook and not config.lm_bearer_token:
        raise ValueError(
            "LM_BEARER_TOKEN is required when USE_WEBHOOK is true"
        )
    if not config.use_webhook and (not config.lm_access_id or not config.lm_access_key):
        raise ValueError(
            "LM_ACCESS_ID and LM_ACCESS_KEY are required when USE_WEBHOOK is false"
        )


def _load_from_secret_manager(secret_id: str) -> str | None:
    """Attempt to load a secret from GCP Secret Manager.

    Returns None if Secret Manager is unavailable or the secret does not exist.
    Only imports the GCP library when actually called to avoid import overhead
    in local development.
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        # The project ID is inferred from the environment in Cloud Functions
        project_id = os.environ.get("GCP_PROJECT") or os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )
        if not project_id:
            return None

        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception:
        return None
