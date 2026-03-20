# Description: HTTP client for sending logs to LogicMonitor endpoints.
# Description: Supports both the Ingest API (Phase 1) and Webhook (Phase 2) paths.
from __future__ import annotations

import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cloud_function.config import Config
from cloud_function.lm_auth import generate_lmv1_token, get_bearer_header

logger = logging.getLogger(__name__)

# Retry on 429 (rate limited) and 5xx (server errors), max 3 attempts
_RETRY_STRATEGY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
)


class LMClient:
    """Client for sending log data to LogicMonitor.

    Creates a persistent requests.Session with automatic retry for
    transient failures. Session is reused across invocations for
    connection pooling (important for Cloud Function performance).
    """

    def __init__(self, config: Config):
        self._config = config
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY_STRATEGY)
        self._session.mount("https://", adapter)
        self._base_url = (
            f"https://{config.lm_company_name}.{config.lm_company_domain}"
        )

    def send_to_ingest_api(self, payloads: list[dict]) -> bool:
        """Send log payloads to the LM Logs Ingest API.

        POSTs a JSON array of log objects to /rest/log/ingest
        using LMv1 HMAC authentication. Retries automatically on
        429/5xx responses.

        Args:
            payloads: List of formatted log payload dicts.

        Returns:
            True on success (HTTP 200/202), False on failure.
        """
        url = f"{self._base_url}/rest/log/ingest"
        resource_path = "/log/ingest"
        body = json.dumps(payloads)

        auth_token = generate_lmv1_token(
            access_id=self._config.lm_access_id,
            access_key=self._config.lm_access_key,
            http_method="POST",
            resource_path=resource_path,
            body=body,
        )

        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "X-Version": "3",
        }

        try:
            response = self._session.post(url, data=body, headers=headers)
            if response.status_code in (200, 202):
                return True
            logger.error(
                "LM Ingest API error: status=%d body=%s",
                response.status_code,
                response.text,
            )
            return False
        except requests.exceptions.RequestException as e:
            logger.error("LM Ingest API request failed: %s", e)
            return False

    def send_to_webhook(self, payload: dict) -> bool:
        """Send a single log payload to the LM Webhook endpoint.

        POSTs a single JSON object to
        /rest/api/v1/webhook/ingest/{source_name}
        using Bearer token authentication. Retries automatically on
        429/5xx responses.

        Args:
            payload: Single formatted log payload dict.

        Returns:
            True on success (HTTP 200/202), False on failure.
        """
        url = (
            f"{self._base_url}/rest/api/v1/webhook/ingest/"
            f"{self._config.webhook_source_name}"
        )
        headers = get_bearer_header(self._config.lm_bearer_token)
        headers["Content-Type"] = "application/json"

        try:
            response = self._session.post(url, json=payload, headers=headers)
            if response.status_code in (200, 202):
                return True
            logger.error(
                "LM Webhook error: status=%d body=%s",
                response.status_code,
                response.text,
            )
            return False
        except requests.exceptions.RequestException as e:
            logger.error("LM Webhook request failed: %s", e)
            return False
