"""Tests for auth configuration factory."""

import pytest

from fastmcp.server.auth import JWTVerifier

from domo_mcp.auth_config import create_auth, _detect_algorithm
from domo_mcp.token_verifier import ConstantTimeTokenVerifier


class TestCreateAuthNone:
    def test_none_mode_returns_none(self):
        assert create_auth(None) is None

    def test_empty_string_returns_none(self):
        assert create_auth("") is None

    def test_none_mode_ignores_tokens(self):
        assert create_auth(None, "token1,token2") is None

    def test_bearer_no_tokens_returns_none(self):
        assert create_auth("bearer") is None

    def test_bearer_empty_tokens_returns_none(self):
        assert create_auth("bearer", "") is None


class TestCreateAuthBearer:
    def test_plain_tokens_backward_compatible(self):
        """Plain MCP_AUTH_TOKENS=token1,token2 works as before (no PDP)."""
        result = create_auth("bearer", "token1,token2")
        assert isinstance(result, ConstantTimeTokenVerifier)

    def test_token_with_email_mapping(self):
        """Bearer tokens with :email create verifier with email claims."""
        result = create_auth("bearer", "abc:alice@example.com")
        assert isinstance(result, ConstantTimeTokenVerifier)

    def test_mixed_tokens(self):
        """Mix of token:email and plain tokens works correctly."""
        result = create_auth("bearer", "abc:alice@example.com,svc-token")
        assert isinstance(result, ConstantTimeTokenVerifier)

    def test_whitespace_handling(self):
        """Whitespace around tokens and emails is stripped."""
        result = create_auth("bearer", " token1 , token2 : bob@example.com ")
        assert isinstance(result, ConstantTimeTokenVerifier)

    def test_trailing_comma(self):
        """Trailing comma is handled gracefully."""
        result = create_auth("bearer", "token1,")
        assert isinstance(result, ConstantTimeTokenVerifier)

    def test_invalid_email_raises(self):
        """Invalid email format raises ValueError at startup."""
        with pytest.raises(ValueError, match="Invalid email format"):
            create_auth("bearer", "token1:not-an-email")

    def test_empty_email_raises(self):
        """Token with colon but empty email raises ValueError."""
        with pytest.raises(ValueError, match="Empty email"):
            create_auth("bearer", "token1:")

    def test_empty_token_raises(self):
        """Empty token before colon raises ValueError."""
        with pytest.raises(ValueError, match="Empty token"):
            create_auth("bearer", ":alice@example.com")

    def test_email_at_only_raises(self):
        """Email with only @ is invalid."""
        with pytest.raises(ValueError, match="Invalid email format"):
            create_auth("bearer", "token1:@example.com")


class TestCreateAuthJwt:
    def test_jwt_with_public_key_pem(self, monkeypatch):
        """JWT mode with PEM public key creates JWTVerifier."""
        monkeypatch.setenv("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----")
        monkeypatch.delenv("JWT_JWKS_URI", raising=False)
        monkeypatch.delenv("JWT_ISSUER", raising=False)
        result = create_auth("jwt")
        assert isinstance(result, JWTVerifier)

    def test_jwt_with_hmac_secret(self, monkeypatch):
        """JWT mode with raw string auto-detects HS256."""
        monkeypatch.setenv("JWT_PUBLIC_KEY", "my-shared-secret-key-for-testing")
        monkeypatch.delenv("JWT_JWKS_URI", raising=False)
        monkeypatch.delenv("JWT_ISSUER", raising=False)
        result = create_auth("jwt")
        assert isinstance(result, JWTVerifier)

    def test_jwt_with_jwks_uri(self, monkeypatch):
        """JWT mode with JWKS URI creates JWTVerifier."""
        monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
        monkeypatch.setenv("JWT_JWKS_URI", "https://auth.example.com/.well-known/jwks.json")
        monkeypatch.delenv("JWT_ISSUER", raising=False)
        result = create_auth("jwt")
        assert isinstance(result, JWTVerifier)

    def test_jwt_with_issuer(self, monkeypatch):
        """JWT mode with issuer passes it to JWTVerifier."""
        monkeypatch.setenv("JWT_PUBLIC_KEY", "my-secret")
        monkeypatch.delenv("JWT_JWKS_URI", raising=False)
        monkeypatch.setenv("JWT_ISSUER", "https://gateway.example.com")
        result = create_auth("jwt")
        assert isinstance(result, JWTVerifier)

    def test_jwt_both_key_and_jwks_raises(self, monkeypatch):
        """Setting both JWT_PUBLIC_KEY and JWT_JWKS_URI raises ValueError."""
        monkeypatch.setenv("JWT_PUBLIC_KEY", "my-secret")
        monkeypatch.setenv("JWT_JWKS_URI", "https://auth.example.com/.well-known/jwks.json")
        with pytest.raises(ValueError, match="JWT_PUBLIC_KEY or JWT_JWKS_URI, not both"):
            create_auth("jwt")

    def test_jwt_neither_key_nor_jwks_raises(self, monkeypatch):
        """Setting neither JWT_PUBLIC_KEY nor JWT_JWKS_URI raises ValueError."""
        monkeypatch.delenv("JWT_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("JWT_JWKS_URI", raising=False)
        with pytest.raises(ValueError, match="JWT_PUBLIC_KEY or JWT_JWKS_URI required"):
            create_auth("jwt")


class TestDetectAlgorithm:
    def test_jwks_uri_returns_rs256(self):
        assert _detect_algorithm(None, "https://example.com/jwks") == "RS256"

    def test_pem_rsa_returns_rs256(self):
        pem = "-----BEGIN PUBLIC KEY-----\nMIIB...\n-----END PUBLIC KEY-----"
        assert _detect_algorithm(pem, None) == "RS256"

    def test_pem_ec_returns_es256(self):
        pem = "-----BEGIN EC PUBLIC KEY-----\nMHQ...\n-----END EC PUBLIC KEY-----"
        assert _detect_algorithm(pem, None) == "ES256"

    def test_raw_string_returns_hs256(self):
        assert _detect_algorithm("my-shared-secret", None) == "HS256"

    def test_none_returns_hs256(self):
        assert _detect_algorithm(None, None) == "HS256"
