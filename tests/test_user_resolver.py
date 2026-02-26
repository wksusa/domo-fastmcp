"""Tests for user resolver."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from domo_mcp.user_resolver import UserResolver


@pytest.fixture
def mock_domo_client():
    client = MagicMock()
    client.list_users = AsyncMock()
    return client


class TestUserResolver:
    @pytest.mark.asyncio
    async def test_resolve_existing_user(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 123, "email": "alice@example.com"},
            {"id": 456, "email": "bob@example.com"},
        ]
        resolver = UserResolver(mock_domo_client)
        result = await resolver.resolve("alice@example.com")
        assert result == "123"

    @pytest.mark.asyncio
    async def test_resolve_missing_user(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 123, "email": "alice@example.com"},
        ]
        resolver = UserResolver(mock_domo_client)
        result = await resolver.resolve("nobody@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_case_insensitive(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 123, "email": "Alice@Example.com"},
        ]
        resolver = UserResolver(mock_domo_client)
        result = await resolver.resolve("alice@example.com")
        assert result == "123"

    @pytest.mark.asyncio
    async def test_paginates_through_users(self, mock_domo_client):
        page1 = [{"id": i, "email": f"user{i}@example.com"} for i in range(500)]
        page2 = [{"id": 500, "email": "target@example.com"}]
        mock_domo_client.list_users.side_effect = [page1, page2]

        resolver = UserResolver(mock_domo_client)
        result = await resolver.resolve("target@example.com")
        assert result == "500"
        assert mock_domo_client.list_users.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_reused(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 1, "email": "user@example.com"},
        ]
        resolver = UserResolver(mock_domo_client)

        await resolver.resolve("user@example.com")
        await resolver.resolve("user@example.com")

        # Should only call list_users once (cached)
        assert mock_domo_client.list_users.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_domo_client):
        mock_domo_client.list_users.return_value = []
        resolver = UserResolver(mock_domo_client)
        result = await resolver.resolve("user@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_is_admin_for_admin_role(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 1, "email": "admin@example.com", "role": "Admin"},
            {"id": 2, "email": "editor@example.com", "role": "Editor"},
        ]
        resolver = UserResolver(mock_domo_client)
        await resolver.resolve("admin@example.com")
        assert resolver.is_admin("admin@example.com") is True
        assert resolver.is_admin("editor@example.com") is False

    @pytest.mark.asyncio
    async def test_is_admin_for_privileged_role(self, mock_domo_client):
        mock_domo_client.list_users.return_value = [
            {"id": 1, "email": "priv@example.com", "role": "Privileged"},
        ]
        resolver = UserResolver(mock_domo_client)
        await resolver.resolve("priv@example.com")
        assert resolver.is_admin("priv@example.com") is True

    @pytest.mark.asyncio
    async def test_is_admin_unknown_email_returns_false(self, mock_domo_client):
        mock_domo_client.list_users.return_value = []
        resolver = UserResolver(mock_domo_client)
        assert resolver.is_admin("nobody@example.com") is False
