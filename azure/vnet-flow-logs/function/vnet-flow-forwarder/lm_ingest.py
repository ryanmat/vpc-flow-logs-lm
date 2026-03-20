# Description: LM Logs REST Ingest API client with LMv1 HMAC-SHA256 auth and gzip compression.
# Description: Sends batched log entries to the /rest/log/ingest endpoint with retry on failure.

import gzip
import hashlib
import hmac
import base64
import json
import logging
import time
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

LM_INGEST_PATH = "/log/ingest"


def build_lmv1_signature(access_key, http_verb, epoch_ms, body, resource_path):
    """Build the LMv1 HMAC-SHA256 signature.

    The signature is computed as:
      base64(hex(HMAC-SHA256(access_key, verb + timestamp + body + path)))
    """
    request_vars = http_verb + epoch_ms + body + resource_path
    hex_digest = hmac.new(
        access_key.encode("utf-8"),
        msg=request_vars.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return base64.b64encode(hex_digest.encode("utf-8")).decode("utf-8")


def build_auth_header(access_id, access_key, body):
    """Build the full LMv1 Authorization header value.

    Format: "LMv1 {access_id}:{signature}:{epoch_ms}"
    """
    epoch_ms = str(int(time.time() * 1000))
    signature = build_lmv1_signature(
        access_key=access_key,
        http_verb="POST",
        epoch_ms=epoch_ms,
        body=body,
        resource_path=LM_INGEST_PATH,
    )
    return f"LMv1 {access_id}:{signature}:{epoch_ms}"


def compress_payload(body_str):
    """Gzip-compress a JSON string for the LM ingest endpoint."""
    return gzip.compress(body_str.encode("utf-8"))


def send_batch(entries, company, access_id, access_key, timeout=30):
    """POST a batch of log entries to the LM Logs Ingest API.

    Returns True on success (HTTP 2xx), False on any error.
    """
    url = f"https://{company}.logicmonitor.com/rest/log/ingest"
    body_str = json.dumps(entries)
    compressed = compress_payload(body_str)
    auth_header = build_auth_header(access_id, access_key, body_str)

    req = urllib.request.Request(url, data=compressed, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Encoding", "gzip")
    req.add_header("Authorization", auth_header)
    req.add_header("User-Agent", "lm-vnet-flow-forwarder/1.0.0")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8")
            logger.info("LM ingest response %d: %s (%d entries)", status, resp_body[:200], len(entries))
            return 200 <= status < 300
    except urllib.error.HTTPError as e:
        logger.error("LM ingest HTTP %d: %s", e.code, e.read().decode("utf-8", errors="replace")[:200])
        return False
    except Exception:
        logger.exception("LM ingest request failed")
        return False


def send_with_retry(entries, company, access_id, access_key, max_retries=3, retry_base_delay=1.0):
    """Send a batch with exponential backoff retry on failure.

    Retries up to max_retries times with delays of retry_base_delay * 2^attempt.
    Returns True if any attempt succeeds, False if all fail.
    """
    for attempt in range(max_retries + 1):
        success = send_batch(entries, company, access_id, access_key)
        if success:
            return True

        if attempt < max_retries:
            wait = retry_base_delay * (2 ** attempt)
            logger.warning("LM ingest failed, retry %d/%d after %.1fs", attempt + 1, max_retries, wait)
            time.sleep(wait)

    logger.error("LM ingest failed after %d retries, dropping %d entries", max_retries, len(entries))
    return False
