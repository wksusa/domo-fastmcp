"""Tests for auth configuration factory."""

import pytest
from unittest.mock import patch

from domo_mcp.auth_config import create_auth


class TestCreateAuth:
    def test_bearer_mode_returns_none(self):
        assert create_auth("bearer") is None

    def test_none_mode_returns_none(self):
        assert create_auth(None) is None

    def test_empty_string_returns_none(self):
        assert create_auth("") is None

    def test_jwt_mode_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
        monkeypatch.delenv("GATEWAY_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="JWT_SIGNING_KEY"):
            create_auth("jwt")

    def test_jwt_mode_missing_gateway_raises(self, monkeypatch):
        monkeypatch.setenv("JWT_SIGNING_KEY", "test-secret-key-32chars-minimum!!")
        monkeypatch.delenv("GATEWAY_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="GATEWAY_BASE_URL"):
            create_auth("jwt")

    def test_jwt_mode_returns_verifier(self, monkeypatch):
        monkeypatch.setenv("JWT_SIGNING_KEY", "test-secret-key-32chars-minimum!!")
        monkeypatch.setenv("GATEWAY_BASE_URL", "https://gateway.example.com")
        result = create_auth("jwt")
        assert result is not None
        # Should be a JWTVerifier instance
        from fastmcp.server.auth import JWTVerifier
        assert isinstance(result, JWTVerifier)
