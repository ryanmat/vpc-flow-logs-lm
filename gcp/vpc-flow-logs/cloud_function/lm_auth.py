# Description: Authentication helpers for LogicMonitor API endpoints.
# Description: Generates LMv1 HMAC tokens and Bearer token headers.
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def generate_lmv1_token(
    access_id: str,
    access_key: str,
    http_method: str,
    resource_path: str,
    body: str = "",
) -> str:
    """Generate an LMv1 HMAC authentication token.

    Algorithm:
        1. Build string: HTTP_METHOD + epoch_ms + body + resource_path
        2. HMAC-SHA256 sign with access_key
        3. Base64 encode the signature
        4. Return "LMv1 {access_id}:{signature}:{epoch_ms}"

    Args:
        access_id: LM API access ID.
        access_key: LM API access key (used as HMAC signing key).
        http_method: HTTP method (e.g., "POST").
        resource_path: API resource path (e.g., "/log/ingest").
        body: Request body string (empty string for GET requests).

    Returns:
        Complete Authorization header value.
    """
    epoch_ms = str(int(time.time() * 1000))

    request_vars = http_method + epoch_ms + body + resource_path

    signature = base64.b64encode(
        hmac.new(
            access_key.encode("utf-8"),
            msg=request_vars.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return f"LMv1 {access_id}:{signature}:{epoch_ms}"


def get_bearer_header(token: str) -> dict:
    """Build an Authorization header dict for Bearer token auth.

    Args:
        token: The Bearer token string.

    Returns:
        Dict with the Authorization header.
    """
    return {"Authorization": f"Bearer {token}"}
