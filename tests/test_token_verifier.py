"""Tests for ConstantTimeTokenVerifier."""

import pytest

from domo_mcp.token_verifier import ConstantTimeTokenVerifier


@pytest.fixture
def verifier():
    """Create a verifier with mixed tokens."""
    tokens = {
        "token-abc": {
            "client_id": "bearer:alice@example.com",
            "scopes": [],
            "email": "alice@example.com",
        },
        "svc-token": {
            "client_id": "bearer:service",
            "scopes": [],
        },
    }
    return ConstantTimeTokenVerifier(tokens=tokens)


@pytest.mark.asyncio
async def test_valid_token_returns_access_token(verifier):
    """Valid token returns AccessToken with correct claims."""
    result = await verifier.verify_token("token-abc")
    assert result is not None
    assert result.client_id == "bearer:alice@example.com"
    assert result.claims["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_service_account_token(verifier):
    """Service account token returns AccessToken without email."""
    result = await verifier.verify_token("svc-token")
    assert result is not None
    assert result.client_id == "bearer:service"
    assert "email" not in result.claims


@pytest.mark.asyncio
async def test_invalid_token_returns_none(verifier):
    """Invalid token returns None."""
    result = await verifier.verify_token("bad-token")
    assert result is None


@pytest.mark.asyncio
async def test_empty_token_returns_none(verifier):
    """Empty string token returns None."""
    result = await verifier.verify_token("")
    assert result is None


@pytest.mark.asyncio
async def test_similar_token_rejected(verifier):
    """Token that is close but not exact is rejected."""
    result = await verifier.verify_token("token-abd")
    assert result is None


@pytest.mark.asyncio
async def test_case_sensitive(verifier):
    """Token comparison is case-sensitive."""
    result = await verifier.verify_token("TOKEN-ABC")
    assert result is None


@pytest.mark.asyncio
async def test_scopes_propagated():
    """Scopes from token data are propagated to AccessToken."""
    tokens = {
        "scoped-token": {
            "client_id": "bearer:bob@example.com",
            "scopes": ["read", "write"],
            "email": "bob@example.com",
        },
    }
    verifier = ConstantTimeTokenVerifier(tokens=tokens)
    result = await verifier.verify_token("scoped-token")
    assert result is not None
    assert result.scopes == ["read", "write"]


@pytest.mark.asyncio
async def test_empty_tokens_dict():
    """Verifier with no tokens rejects everything."""
    verifier = ConstantTimeTokenVerifier(tokens={})
    result = await verifier.verify_token("any-token")
    assert result is None
