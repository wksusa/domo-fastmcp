"""Tests for native PDP enforcement via per-user tokens.

Covers: is_jwt_auth(), DomoRequestError, override_token on data methods,
and admin tool gating.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from domo_mcp.domo import DomoRequestError
from domo_mcp.identity import is_jwt_auth


# ---------------------------------------------------------------------------
# DomoRequestError
# ---------------------------------------------------------------------------

class TestDomoRequestError:
    def test_attributes(self):
        err = DomoRequestError(403, "/query/v1/execute/abc123")
        assert err.status_code == 403
        assert "403" in str(err)
        assert "/query/v1/execute/abc123" in str(err)

    def test_inherits_from_exception(self):
        err = DomoRequestError(401, "/some/path")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# is_jwt_auth()
# ---------------------------------------------------------------------------

class TestIsJwtAuth:
    def test_no_token_returns_false(self):
        with patch("domo_mcp.identity.get_access_token", return_value=None):
            assert is_jwt_auth() is False

    def test_no_claims_returns_false(self):
        token = MagicMock()
        token.claims = None
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False

    def test_bearer_prefix_returns_false(self):
        token = MagicMock()
        token.claims = {"client_id": "bearer:alice@corp.com", "email": "alice@corp.com"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False

    def test_bearer_service_returns_false(self):
        token = MagicMock()
        token.claims = {"client_id": "bearer:service"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False

    def test_bearer_named_returns_false(self):
        token = MagicMock()
        token.claims = {"client_id": "bearer:myapp"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False

    def test_jwt_client_id_returns_true(self):
        token = MagicMock()
        token.claims = {"client_id": "gateway-abc123", "email": "user@corp.com"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is True

    def test_empty_client_id_returns_false(self):
        """Missing client_id defaults to non-JWT (safe default)."""
        token = MagicMock()
        token.claims = {"sub": "user123"}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False

    def test_empty_claims_dict_returns_false(self):
        """Empty claims dict is falsy — treated as unauthenticated."""
        token = MagicMock()
        token.claims = {}
        with patch("domo_mcp.identity.get_access_token", return_value=token):
            assert is_jwt_auth() is False


# ---------------------------------------------------------------------------
# _request_with_override (via DomoClient data methods)
# ---------------------------------------------------------------------------

class TestOverrideToken:
    """Test that override_token paths use the override and raise DomoRequestError."""

    @pytest.fixture
    def domo_client(self, mock_logger):
        """Create a DomoClient with developer token auth (no real credentials)."""
        with patch.dict("os.environ", {
            "DOMO_DEVELOPER_TOKEN": "fake-token",
            "DOMO_HOST": "test.domo.com",
        }):
            from domo_mcp.domo import DomoClient
            client = DomoClient(mock_logger)
            return client

    @pytest.mark.asyncio
    async def test_query_with_override_success(self, domo_client):
        """override_token uses _request_with_override and returns data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"rows": []}'
        mock_response.json.return_value = {"rows": []}
        mock_response.raise_for_status = MagicMock()

        domo_client._http_client = AsyncMock()
        domo_client._http_client.post = AsyncMock(return_value=mock_response)

        result = await domo_client.query_dataset("ds123", "SELECT 1", override_token="user-token")
        assert result == {"rows": []}
        # Verify the override token was used in headers
        call_kwargs = domo_client._http_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-DOMO-Developer-Token"] == "user-token"

    @pytest.mark.asyncio
    async def test_query_with_override_raises_on_403(self, domo_client):
        """override_token path raises DomoRequestError on HTTP 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=mock_response
        )

        domo_client._http_client = AsyncMock()
        domo_client._http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(DomoRequestError) as exc_info:
            await domo_client.query_dataset("ds123", "SELECT 1", override_token="user-token")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_query_without_override_uses_make_request(self, domo_client):
        """Without override_token, falls through to make_request (existing path)."""
        domo_client.make_request = AsyncMock(return_value={"rows": []})

        result = await domo_client.query_dataset("ds123", "SELECT 1")
        assert result == {"rows": []}
        domo_client.make_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_schema_with_override_raises_on_401(self, domo_client):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )

        domo_client._http_client = AsyncMock()
        domo_client._http_client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(DomoRequestError) as exc_info:
            await domo_client.get_dataset_schema("ds123", override_token="user-token")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_metadata_with_override_success(self, domo_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"name": "test"}'
        mock_response.json.return_value = {"name": "test"}
        mock_response.raise_for_status = MagicMock()

        domo_client._http_client = AsyncMock()
        domo_client._http_client.get = AsyncMock(return_value=mock_response)

        result = await domo_client.get_dataset_metadata("ds123", override_token="user-token")
        assert result == {"name": "test"}


