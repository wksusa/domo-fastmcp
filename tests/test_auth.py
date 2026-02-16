"""Integration tests for ConstantTimeTokenVerifier with email mapping."""

import pytest

from domo_mcp.token_verifier import ConstantTimeTokenVerifier


@pytest.fixture
def email_mapped_verifier():
    """Verifier with email-mapped tokens (PDP-enabled)."""
    tokens = {
        "user-token-abc": {
            "client_id": "bearer:alice@corp.com",
            "scopes": [],
            "email": "alice@corp.com",
        },
        "user-token-xyz": {
            "client_id": "bearer:bob@corp.com",
            "scopes": [],
            "email": "bob@corp.com",
        },
    }
    return ConstantTimeTokenVerifier(tokens=tokens)


@pytest.fixture
def mixed_verifier():
    """Verifier with both email-mapped and service account tokens."""
    tokens = {
        "user-token": {
            "client_id": "bearer:alice@corp.com",
            "scopes": [],
            "email": "alice@corp.com",
        },
        "svc-token": {
            "client_id": "bearer:service",
            "scopes": [],
        },
    }
    return ConstantTimeTokenVerifier(tokens=tokens)


@pytest.mark.asyncio
async def test_email_mapped_token_has_email(email_mapped_verifier):
    """Email-mapped token includes email in claims for PDP."""
    result = await email_mapped_verifier.verify_token("user-token-abc")
    assert result is not None
    assert result.claims["email"] == "alice@corp.com"
    assert result.client_id == "bearer:alice@corp.com"


@pytest.mark.asyncio
async def test_second_email_mapped_token(email_mapped_verifier):
    """Second email-mapped token also works."""
    result = await email_mapped_verifier.verify_token("user-token-xyz")
    assert result is not None
    assert result.claims["email"] == "bob@corp.com"


@pytest.mark.asyncio
async def test_service_account_no_email_claim(mixed_verifier):
    """Service account token has no email in claims (PDP bypassed)."""
    result = await mixed_verifier.verify_token("svc-token")
    assert result is not None
    assert "email" not in result.claims
    assert result.client_id == "bearer:service"


@pytest.mark.asyncio
async def test_invalid_token_rejected(mixed_verifier):
    """Invalid token returns None."""
    result = await mixed_verifier.verify_token("wrong-token")
    assert result is None


@pytest.mark.asyncio
async def test_timing_attack_resistance():
    """Various invalid tokens of different lengths all return None.

    True timing attack resistance is provided by secrets.compare_digest().
    This test verifies all invalid tokens are rejected regardless of similarity.
    """
    tokens = {
        "test-token-12345": {
            "client_id": "bearer:test@example.com",
            "scopes": [],
            "email": "test@example.com",
        },
    }
    verifier = ConstantTimeTokenVerifier(tokens=tokens)

    test_cases = [
        "a",
        "test",
        "test-token",
        "test-token-12344",  # off by one
        "test-token-12345x",  # too long
        "x" * 100,
    ]

    for token in test_cases:
        result = await verifier.verify_token(token)
        assert result is None, f"Token '{token}' should have been rejected"


@pytest.mark.asyncio
async def test_multiple_requests_same_token(email_mapped_verifier):
    """Multiple verifications with same token all succeed."""
    for _ in range(3):
        result = await email_mapped_verifier.verify_token("user-token-abc")
        assert result is not None
        assert result.claims["email"] == "alice@corp.com"
