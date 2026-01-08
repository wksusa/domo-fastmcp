"""Tests for DomoClient with mocked HTTP responses."""

import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from domo_mcp.domo import DomoClient


@pytest.fixture
def dev_token_env(monkeypatch):
    """Set up environment for developer token auth."""
    monkeypatch.setenv("DOMO_DEVELOPER_TOKEN", "test-token")
    monkeypatch.setenv("DOMO_HOST", "test.domo.com")
    monkeypatch.delenv("DOMO_CLIENT_ID", raising=False)
    monkeypatch.delenv("DOMO_CLIENT_SECRET", raising=False)


@pytest.fixture
def oauth_env(monkeypatch):
    """Set up environment for OAuth auth."""
    monkeypatch.delenv("DOMO_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("DOMO_HOST", raising=False)
    monkeypatch.setenv("DOMO_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DOMO_CLIENT_SECRET", "test-client-secret")


class TestDomoClientInit:
    """Tests for DomoClient initialization."""

    def test_init_with_developer_token(self, dev_token_env, mock_logger):
        """Client should initialize with developer token auth."""
        client = DomoClient(mock_logger)
        assert client.auth_mode == "developer_token"
        assert client.DOMO_API_BASE == "https://test.domo.com/api"

    def test_init_with_oauth(self, oauth_env, mock_logger):
        """Client should initialize with OAuth auth."""
        client = DomoClient(mock_logger)
        assert client.auth_mode == "oauth"
        assert client.DOMO_API_BASE == "https://api.domo.com"

    def test_init_without_credentials(self, monkeypatch, mock_logger):
        """Client should raise error without credentials."""
        monkeypatch.delenv("DOMO_DEVELOPER_TOKEN", raising=False)
        monkeypatch.delenv("DOMO_HOST", raising=False)
        monkeypatch.delenv("DOMO_CLIENT_ID", raising=False)
        monkeypatch.delenv("DOMO_CLIENT_SECRET", raising=False)

        with pytest.raises(ValueError) as exc_info:
            DomoClient(mock_logger)
        assert "Missing Domo credentials" in str(exc_info.value)


class TestDomoClientHeaders:
    """Tests for header generation."""

    @pytest.mark.asyncio
    async def test_developer_token_headers(self, dev_token_env, mock_logger):
        """Developer token auth should use X-DOMO-Developer-Token header."""
        client = DomoClient(mock_logger)
        headers = await client._get_headers()
        assert headers["X-DOMO-Developer-Token"] == "test-token"
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_oauth_headers(self, oauth_env, mock_logger):
        """OAuth auth should fetch and use bearer token."""
        client = DomoClient(mock_logger)

        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "access_token": "mock-access-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            headers = await client._get_headers()

        assert headers["Authorization"] == "Bearer mock-access-token"
        assert headers["Accept"] == "application/json"


class TestDomoClientRequests:
    """Tests for API request methods."""

    @pytest.mark.asyncio
    async def test_make_request_get(
        self, dev_token_env, mock_logger, sample_dataset_response
    ):
        """GET request should return parsed JSON."""
        client = DomoClient(mock_logger)

        mock_response = AsyncMock()
        mock_response.json.return_value = sample_dataset_response
        mock_response.content = b'{"id": "abc123"}'
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.make_request("/test", "GET")

        assert result == sample_dataset_response

    @pytest.mark.asyncio
    async def test_make_request_post(self, dev_token_env, mock_logger):
        """POST request should send JSON data."""
        client = DomoClient(mock_logger)

        mock_response = AsyncMock()
        mock_response.json.return_value = {"success": True}
        mock_response.content = b'{"success": true}'
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.make_request("/test", "POST", data={"key": "value"})

        assert result == {"success": True}
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_http_error(self, dev_token_env, mock_logger):
        """HTTP errors should be logged and return None."""
        client = DomoClient(mock_logger)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=AsyncMock(),
                response=AsyncMock(status_code=404),
            )
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.make_request("/test", "GET")

        assert result is None
        assert len(mock_logger.messages["error"]) > 0

    @pytest.mark.asyncio
    async def test_make_request_empty_response(self, dev_token_env, mock_logger):
        """Empty response should return None."""
        client = DomoClient(mock_logger)

        mock_response = AsyncMock()
        mock_response.content = b""
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.make_request("/test", "GET")

        assert result is None


class TestDomoClientMethods:
    """Tests for high-level client methods."""

    @pytest.mark.asyncio
    async def test_get_dataset_metadata(
        self, dev_token_env, mock_logger, sample_dataset_response
    ):
        """get_dataset_metadata should call correct endpoint."""
        client = DomoClient(mock_logger)

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_dataset_response

            result = await client.get_dataset_metadata("test-id")

        mock_request.assert_called_once_with(
            "/data/v3/datasources/test-id?part=core", "GET"
        )
        assert result == sample_dataset_response

    @pytest.mark.asyncio
    async def test_get_dataset_schema(
        self, dev_token_env, mock_logger, sample_schema_response
    ):
        """get_dataset_schema should call correct endpoint."""
        client = DomoClient(mock_logger)

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_schema_response

            result = await client.get_dataset_schema("test-id")

        mock_request.assert_called_once_with(
            "/data/v2/datasources/test-id/schemas/latest", "GET"
        )
        assert result == sample_schema_response

    @pytest.mark.asyncio
    async def test_query_dataset(
        self, dev_token_env, mock_logger, sample_query_response
    ):
        """query_dataset should POST SQL to correct endpoint."""
        client = DomoClient(mock_logger)

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_query_response

            result = await client.query_dataset("test-id", "SELECT * FROM table")

        mock_request.assert_called_once_with(
            "/query/v1/execute/test-id", "POST", data={"sql": "SELECT * FROM table"}
        )
        assert result == sample_query_response

    @pytest.mark.asyncio
    async def test_search_datasets_dev_token(self, dev_token_env, mock_logger):
        """search_datasets with dev token should use internal API."""
        client = DomoClient(mock_logger)

        mock_response = {
            "dataSources": [
                {"id": "ds1", "name": "Dataset 1"},
                {"id": "ds2", "name": "Dataset 2"},
            ]
        }

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = mock_response

            result = await client.search_datasets("test")

        assert result == [
            {"id": "ds1", "name": "Dataset 1"},
            {"id": "ds2", "name": "Dataset 2"},
        ]
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert "/data/ui/v3/datasources/search" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_roles(self, dev_token_env, mock_logger, sample_roles_response):
        """list_roles should call correct endpoint."""
        client = DomoClient(mock_logger)

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_roles_response

            result = await client.list_roles()

        mock_request.assert_called_once_with("/authorization/v1/roles", "GET")
        assert result == sample_roles_response

    @pytest.mark.asyncio
    async def test_create_role(self, dev_token_env, mock_logger):
        """create_role should POST role data to correct endpoint."""
        client = DomoClient(mock_logger)
        role_data = {"name": "Test Role", "fromRoleId": 1}

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"id": 123, **role_data}

            result = await client.create_role(role_data)

        mock_request.assert_called_once_with(
            "/authorization/v1/roles", "POST", data=role_data
        )
        assert result["name"] == "Test Role"

    @pytest.mark.asyncio
    async def test_list_role_authorities(self, dev_token_env, mock_logger):
        """list_role_authorities should call correct endpoint."""
        client = DomoClient(mock_logger)

        with patch.object(
            client, "make_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = ["READ", "WRITE"]

            result = await client.list_role_authorities("123")

        mock_request.assert_called_once_with(
            "/authorization/v1/roles/123/authorities", "GET"
        )
        assert result == ["READ", "WRITE"]
