# Description: Unit tests for the LM REST Ingest API client.
# Description: Covers LMv1 HMAC signing, gzip compression, batching, and retry logic.

import gzip
import hashlib
import hmac
import base64
import json
import sys
import os
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from io import BytesIO

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "function", "vnet-flow-forwarder"))

from lm_ingest import (
    build_lmv1_signature,
    build_auth_header,
    compress_payload,
    send_batch,
    send_with_retry,
    LM_INGEST_PATH,
)


# -- Known test vectors for HMAC verification --

TEST_ACCESS_ID = "test_access_id_123"
TEST_ACCESS_KEY = "test_access_key_abc"
TEST_COMPANY = "testportal"
TEST_PAYLOAD = json.dumps([{"msg": "test log", "_lm.resourceId": {}}])


class TestBuildLmv1Signature:
    """Test LMv1 HMAC-SHA256 signature construction."""

    def test_signature_is_base64_of_raw_digest(self):
        epoch_ms = "1706886400000"
        sig = build_lmv1_signature(
            access_key=TEST_ACCESS_KEY,
            http_verb="POST",
            epoch_ms=epoch_ms,
            body=TEST_PAYLOAD,
            resource_path=LM_INGEST_PATH,
        )
        # Manually compute expected signature: base64(HMAC-SHA256(...).digest())
        request_vars = "POST" + epoch_ms + TEST_PAYLOAD + LM_INGEST_PATH
        digest = hmac.new(
            TEST_ACCESS_KEY.encode("utf-8"),
            msg=request_vars.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        assert sig == expected

    def test_different_bodies_produce_different_sigs(self):
        epoch_ms = "1706886400000"
        sig1 = build_lmv1_signature(TEST_ACCESS_KEY, "POST", epoch_ms, "body1", LM_INGEST_PATH)
        sig2 = build_lmv1_signature(TEST_ACCESS_KEY, "POST", epoch_ms, "body2", LM_INGEST_PATH)
        assert sig1 != sig2

    def test_different_timestamps_produce_different_sigs(self):
        sig1 = build_lmv1_signature(TEST_ACCESS_KEY, "POST", "1000", TEST_PAYLOAD, LM_INGEST_PATH)
        sig2 = build_lmv1_signature(TEST_ACCESS_KEY, "POST", "2000", TEST_PAYLOAD, LM_INGEST_PATH)
        assert sig1 != sig2


class TestBuildAuthHeader:
    """Test the full Authorization header construction."""

    def test_header_format(self):
        header = build_auth_header(
            access_id=TEST_ACCESS_ID,
            access_key=TEST_ACCESS_KEY,
            body=TEST_PAYLOAD,
        )
        assert header.startswith("LMv1 test_access_id_123:")
        parts = header.split(":")
        # Format: "LMv1 <id>:<sig>:<timestamp>"
        assert len(parts) == 3
        assert parts[0] == "LMv1 test_access_id_123"
        # Timestamp should be a valid integer (epoch ms)
        assert parts[2].isdigit()


class TestCompressPayload:
    """Test gzip compression of JSON payloads."""

    def test_compressed_output_is_valid_gzip(self):
        data = json.dumps([{"msg": "hello"}])
        compressed = compress_payload(data)
        decompressed = gzip.decompress(compressed)
        assert decompressed.decode("utf-8") == data

    def test_compression_reduces_size(self):
        # Repetitive data should compress well
        data = json.dumps([{"msg": "x" * 10000}])
        compressed = compress_payload(data)
        assert len(compressed) < len(data.encode("utf-8"))

    def test_empty_payload(self):
        data = "[]"
        compressed = compress_payload(data)
        assert gzip.decompress(compressed).decode("utf-8") == "[]"


class TestSendBatch:
    """Test sending a batch of log entries to the LM ingest endpoint."""

    @patch("lm_ingest.urllib.request.urlopen")
    def test_sends_gzip_compressed_post(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 202
        mock_resp.read.return_value = b'{"success":true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        entries = [{"msg": "test", "_lm.resourceId": {}}]
        result = send_batch(
            entries,
            company=TEST_COMPANY,
            access_id=TEST_ACCESS_ID,
            access_key=TEST_ACCESS_KEY,
        )
        assert result == 202

        # Verify the request was made
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_method() == "POST"
        assert "testportal.logicmonitor.com" in req.full_url
        assert req.get_header("Content-encoding") == "gzip"
        assert req.get_header("Content-type") == "application/json"
        assert req.get_header("Authorization").startswith("LMv1 ")

        # Verify the body is valid gzip containing our entries
        body_decompressed = gzip.decompress(req.data)
        body_json = json.loads(body_decompressed)
        assert len(body_json) == 1
        assert body_json[0]["msg"] == "test"

    @patch("lm_ingest.urllib.request.urlopen")
    def test_returns_false_on_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            url="https://test.logicmonitor.com/rest/log/ingest",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=BytesIO(b"error"),
        )
        entries = [{"msg": "test", "_lm.resourceId": {}}]
        result = send_batch(entries, TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY)
        assert result == 500


class TestSendWithRetry:
    """Test retry behavior with exponential backoff on 429."""

    @patch("lm_ingest.send_batch")
    def test_succeeds_on_first_attempt(self, mock_send):
        mock_send.return_value = 202
        result = send_with_retry(
            [{"msg": "test"}], TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY,
            max_retries=3, retry_base_delay=0.01,
        )
        assert result is True
        assert mock_send.call_count == 1

    @patch("lm_ingest.send_batch")
    def test_retries_on_5xx(self, mock_send):
        mock_send.side_effect = [500, 500, 202]
        result = send_with_retry(
            [{"msg": "test"}], TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY,
            max_retries=3, retry_base_delay=0.01,
        )
        assert result is True
        assert mock_send.call_count == 3

    @patch("lm_ingest.send_batch")
    def test_gives_up_after_max_retries(self, mock_send):
        mock_send.return_value = 500
        result = send_with_retry(
            [{"msg": "test"}], TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY,
            max_retries=2, retry_base_delay=0.01,
        )
        assert result is False
        assert mock_send.call_count == 3  # initial + 2 retries

    @patch("lm_ingest.send_batch")
    def test_does_not_retry_on_4xx(self, mock_send):
        mock_send.return_value = 401
        result = send_with_retry(
            [{"msg": "test"}], TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY,
            max_retries=3, retry_base_delay=0.01,
        )
        assert result is False
        assert mock_send.call_count == 1

    @patch("lm_ingest.send_batch")
    def test_retries_on_429(self, mock_send):
        mock_send.side_effect = [429, 429, 202]
        result = send_with_retry(
            [{"msg": "test"}], TEST_COMPANY, TEST_ACCESS_ID, TEST_ACCESS_KEY,
            max_retries=3, retry_base_delay=0.01,
        )
        assert result is True
        assert mock_send.call_count == 3
