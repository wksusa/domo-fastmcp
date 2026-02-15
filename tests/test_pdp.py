"""Tests for PDP authorization checks."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import domo_mcp.pdp as pdp_module
from domo_mcp.pdp import check_dataset_access, filter_accessible_datasets


@pytest.fixture(autouse=True)
def clear_pdp_caches():
    """Clear module-level group caches between tests."""
    pdp_module._group_cache.clear()
    pdp_module._group_cache_time.clear()
    yield
    pdp_module._group_cache.clear()
    pdp_module._group_cache_time.clear()


@pytest.fixture
def mock_domo_client():
    client = MagicMock()
    client.list_group_users = AsyncMock(return_value=[])
    client.get_dataset_details = AsyncMock(return_value=None)
    return client


class TestCheckDatasetAccess:
    @pytest.mark.asyncio
    async def test_pdp_disabled_allows_access(self, mock_domo_client):
        details = {"pdpEnabled": False}
        assert await check_dataset_access("123", details, mock_domo_client) is True

    @pytest.mark.asyncio
    async def test_pdp_enabled_no_policies_denies(self, mock_domo_client):
        details = {"pdpEnabled": True, "policies": []}
        assert await check_dataset_access("123", details, mock_domo_client) is False

    @pytest.mark.asyncio
    async def test_pdp_user_in_policy_allows(self, mock_domo_client):
        details = {
            "pdpEnabled": True,
            "policies": [
                {"users": [123, 456], "groups": []},
            ],
        }
        assert await check_dataset_access("123", details, mock_domo_client) is True

    @pytest.mark.asyncio
    async def test_pdp_user_not_in_policy_denies(self, mock_domo_client):
        details = {
            "pdpEnabled": True,
            "policies": [
                {"users": [456, 789], "groups": []},
            ],
        }
        assert await check_dataset_access("123", details, mock_domo_client) is False

    @pytest.mark.asyncio
    async def test_pdp_user_in_group_allows(self, mock_domo_client):
        mock_domo_client.list_group_users.return_value = [
            {"id": 123},
            {"id": 456},
        ]
        details = {
            "pdpEnabled": True,
            "policies": [
                {"users": [], "groups": [99]},
            ],
        }
        assert await check_dataset_access("123", details, mock_domo_client) is True

    @pytest.mark.asyncio
    async def test_pdp_user_not_in_group_denies(self, mock_domo_client):
        mock_domo_client.list_group_users.return_value = [
            {"id": 456},
        ]
        details = {
            "pdpEnabled": True,
            "policies": [
                {"users": [], "groups": [99]},
            ],
        }
        assert await check_dataset_access("123", details, mock_domo_client) is False

    @pytest.mark.asyncio
    async def test_pdp_multiple_policies_second_matches(self, mock_domo_client):
        details = {
            "pdpEnabled": True,
            "policies": [
                {"users": [999], "groups": []},
                {"users": [123], "groups": []},
            ],
        }
        assert await check_dataset_access("123", details, mock_domo_client) is True


class TestFilterAccessibleDatasets:
    @pytest.mark.asyncio
    async def test_filters_inaccessible_datasets(self, mock_domo_client):
        datasets = [
            {"id": "ds1", "name": "Dataset 1"},
            {"id": "ds2", "name": "Dataset 2"},
        ]
        # ds1: no PDP, ds2: PDP enabled, user not authorized
        mock_domo_client.get_dataset_details.side_effect = [
            {"pdpEnabled": False},
            {"pdpEnabled": True, "policies": [{"users": [999], "groups": []}]},
        ]
        result = await filter_accessible_datasets("123", datasets, mock_domo_client)
        assert len(result) == 1
        assert result[0]["id"] == "ds1"

    @pytest.mark.asyncio
    async def test_includes_datasets_with_no_details(self, mock_domo_client):
        datasets = [{"id": "ds1", "name": "Dataset 1"}]
        mock_domo_client.get_dataset_details.return_value = None
        result = await filter_accessible_datasets("123", datasets, mock_domo_client)
        assert len(result) == 1
