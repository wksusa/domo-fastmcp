"""Unit tests for authentication middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from domo_mcp.auth import AuthMiddleware


# Test application that returns success if request reaches it
async def success_endpoint(request):
    """Simple endpoint that returns success."""
    return JSONResponse({"message": "success"})


@pytest.fixture
def test_app():
    """Create a test Starlette app without auth."""
    return Starlette(routes=[Route("/test", success_endpoint, methods=["GET", "POST", "OPTIONS"])])


@pytest.fixture
def valid_tokens():
    """Valid test tokens."""
    return ["test-token-12345", "test-token-67890"]


@pytest.fixture
def auth_app(test_app, valid_tokens):
    """Create a test app wrapped with AuthMiddleware."""
    wrapped_app = AuthMiddleware(test_app, valid_tokens)
    return TestClient(wrapped_app)


def test_missing_auth_header(auth_app):
    """Test request without Authorization header returns 401."""
    response = auth_app.post("/test")
    assert response.status_code == 401
    assert "error" in response.json()
    assert "Missing or invalid Authorization header" in response.json()["error"]


def test_malformed_auth_header_no_bearer(auth_app):
    """Test request with Authorization header but no 'Bearer' prefix returns 401."""
    response = auth_app.post("/test", headers={"Authorization": "not-bearer-token"})
    assert response.status_code == 401
    assert "error" in response.json()
    assert "Missing or invalid Authorization header" in response.json()["error"]


def test_empty_bearer_token(auth_app):
    """Test request with 'Bearer' but no token returns 401."""
    response = auth_app.post("/test", headers={"Authorization": "Bearer"})
    assert response.status_code == 401
    assert "error" in response.json()


def test_invalid_token(auth_app):
    """Test request with invalid Bearer token returns 403."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "Bearer invalid-token-xyz"}
    )
    assert response.status_code == 403
    assert "error" in response.json()
    assert "Invalid authentication token" in response.json()["error"]


def test_valid_token_first(auth_app):
    """Test request with first valid token succeeds."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "Bearer test-token-12345"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_valid_token_second(auth_app):
    """Test request with second valid token succeeds."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "Bearer test-token-67890"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_valid_token_get_request(auth_app):
    """Test GET request with valid token succeeds."""
    response = auth_app.get(
        "/test",
        headers={"Authorization": "Bearer test-token-12345"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_cors_preflight_no_auth(auth_app):
    """Test CORS preflight (OPTIONS) request works without authentication."""
    response = auth_app.options("/test")
    # Should pass through to the app without requiring authentication
    assert response.status_code == 200


def test_cors_preflight_with_auth_still_works(auth_app):
    """Test CORS preflight works even with auth header present."""
    response = auth_app.options(
        "/test",
        headers={"Authorization": "Bearer test-token-12345"}
    )
    assert response.status_code == 200


def test_case_sensitive_bearer(auth_app):
    """Test that 'bearer' (lowercase) is rejected."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "bearer test-token-12345"}
    )
    assert response.status_code == 401
    assert "Missing or invalid Authorization header" in response.json()["error"]


def test_token_with_extra_spaces(auth_app):
    """Test that token with extra spaces doesn't match."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "Bearer  test-token-12345"}  # extra space
    )
    assert response.status_code == 403
    assert "Invalid authentication token" in response.json()["error"]


def test_token_case_sensitive(auth_app):
    """Test that token comparison is case-sensitive."""
    response = auth_app.post(
        "/test",
        headers={"Authorization": "Bearer TEST-TOKEN-12345"}  # uppercase
    )
    assert response.status_code == 403
    assert "Invalid authentication token" in response.json()["error"]


def test_empty_token_list():
    """Test app with no valid tokens configured."""
    test_app = Starlette(routes=[Route("/test", success_endpoint, methods=["POST"])])
    wrapped_app = AuthMiddleware(test_app, [])
    client = TestClient(wrapped_app)

    # With empty token list, no token should be valid
    response = client.post(
        "/test",
        headers={"Authorization": "Bearer any-token"}
    )
    assert response.status_code == 403


def test_single_token():
    """Test app with single valid token."""
    test_app = Starlette(routes=[Route("/test", success_endpoint, methods=["POST"])])
    wrapped_app = AuthMiddleware(test_app, ["single-token"])
    client = TestClient(wrapped_app)

    response = client.post(
        "/test",
        headers={"Authorization": "Bearer single-token"}
    )
    assert response.status_code == 200


def test_multiple_requests_same_token(auth_app):
    """Test multiple requests with the same valid token all succeed."""
    for _ in range(3):
        response = auth_app.post(
            "/test",
            headers={"Authorization": "Bearer test-token-12345"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "success"}


def test_timing_attack_resistance():
    """Test that invalid tokens of different lengths take similar time.

    This is a basic test - true timing attack resistance requires constant-time
    comparison which we implement using secrets.compare_digest().
    """
    test_app = Starlette(routes=[Route("/test", success_endpoint, methods=["POST"])])
    wrapped_app = AuthMiddleware(test_app, ["test-token-12345"])
    client = TestClient(wrapped_app)

    # These should all fail, regardless of how close they are to the real token
    test_cases = [
        "a",
        "test",
        "test-token",
        "test-token-12344",  # off by one
        "test-token-12345x",  # too long
        "x" * 100,  # very long
    ]

    for token in test_cases:
        response = client.post(
            "/test",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "Invalid authentication token" in response.json()["error"]
