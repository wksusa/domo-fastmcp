"""Tests for identity extraction from access tokens (JWT and bearer)."""

import pytest
from unittest.mock import patch, MagicMock

from domo_mcp.identity import get_user_email


class TestGetUserEmail:
    def test_no_token_returns_none(self):
        with patch("domo_mcp.identity.get_access_token", return_value=None):
            assert get_user_email() is None

    def test_email_from_upstream_claims(self):
        token = MagicMock()
        token.claims = {
            "upstream_claims": {"email": "alice@example.com"},
            "email": "should-not-use@example.com",
        }
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() == "alice@example.com"

    def test_email_from_top_level_claims(self):
        token = MagicMock()
        token.claims = {"email": "bob@example.com"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() == "bob@example.com"

    def test_no_email_in_claims(self):
        token = MagicMock()
        token.claims = {"sub": "user123"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None

    def test_empty_claims(self):
        token = MagicMock()
        token.claims = {}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None

    def test_none_claims(self):
        token = MagicMock()
        token.claims = None
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None


class TestBearerTokenIdentity:
    """Test identity extraction from bearer tokens with email mapping."""

    def test_email_from_bearer_claims(self):
        """ConstantTimeTokenVerifier sets email in top-level claims."""
        token = MagicMock()
        token.claims = {
            "client_id": "bearer:alice@corp.com",
            "scopes": [],
            "email": "alice@corp.com",
        }
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() == "alice@corp.com"

    def test_service_account_no_email(self):
        """Service account token (no email) returns None."""
        token = MagicMock()
        token.claims = {
            "client_id": "bearer:service",
            "scopes": [],
        }
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None


class TestEmailTypeValidation:
    """Test that non-string email claims are rejected."""

    def test_integer_email_returns_none(self):
        token = MagicMock()
        token.claims = {"email": 12345}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None

    def test_list_email_returns_none(self):
        token = MagicMock()
        token.claims = {"email": ["alice@example.com"]}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None

    def test_dict_email_returns_none(self):
        token = MagicMock()
        token.claims = {"email": {"addr": "alice@example.com"}}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert get_user_email() is None
