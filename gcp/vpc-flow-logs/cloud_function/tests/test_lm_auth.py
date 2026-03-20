# Description: Tests for the LMv1 HMAC authentication helper.
# Description: Validates token format, signature behavior, and bearer header.
import re

import pytest

from cloud_function.lm_auth import generate_lmv1_token, get_bearer_header


class TestGenerateLmv1Token:
    """Test LMv1 HMAC token generation."""

    def test_returns_correct_format(self):
        token = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
        )
        # Format: LMv1 <id>:<base64_sig>:<epoch_ms>
        assert token.startswith("LMv1 test_id:")
        parts = token.split(":")
        assert len(parts) == 3

    def test_epoch_ms_is_numeric(self):
        token = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
        )
        epoch_ms = token.split(":")[-1]
        assert epoch_ms.isdigit()
        assert len(epoch_ms) == 13  # millisecond epoch is 13 digits in 2026

    def test_signature_changes_with_different_body(self):
        token_a = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
            body='[{"msg": "test a"}]',
        )
        token_b = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
            body='[{"msg": "test b"}]',
        )
        sig_a = token_a.split(":")[1]
        sig_b = token_b.split(":")[1]
        assert sig_a != sig_b

    def test_signature_changes_with_different_key(self):
        token_a = generate_lmv1_token(
            access_id="test_id",
            access_key="key_one",
            http_method="POST",
            resource_path="/log/ingest",
        )
        token_b = generate_lmv1_token(
            access_id="test_id",
            access_key="key_two",
            http_method="POST",
            resource_path="/log/ingest",
        )
        sig_a = token_a.split(":")[1]
        sig_b = token_b.split(":")[1]
        assert sig_a != sig_b

    def test_signature_changes_with_different_resource_path(self):
        token_a = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
        )
        token_b = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="POST",
            resource_path="/santaba/rest/log/ingest",
        )
        sig_a = token_a.split(":")[1]
        sig_b = token_b.split(":")[1]
        assert sig_a != sig_b

    def test_access_id_included_in_token(self):
        token = generate_lmv1_token(
            access_id="my_access_id_123",
            access_key="test_key",
            http_method="POST",
            resource_path="/log/ingest",
        )
        assert "LMv1 my_access_id_123:" in token

    def test_empty_body_is_valid(self):
        token = generate_lmv1_token(
            access_id="test_id",
            access_key="test_key",
            http_method="GET",
            resource_path="/santaba/rest/device/devices",
        )
        assert token.startswith("LMv1 test_id:")


class TestGetBearerHeader:
    """Test Bearer token header construction."""

    def test_returns_correct_header(self):
        header = get_bearer_header("my_token_xyz")
        assert header == {"Authorization": "Bearer my_token_xyz"}

    def test_token_value_is_exact(self):
        header = get_bearer_header("abc123")
        assert header["Authorization"] == "Bearer abc123"
