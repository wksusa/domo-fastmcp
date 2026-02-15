"""PDP (Personalized Data Permission) authorization checks."""

import asyncio
import time


# Cache for group membership: group_id -> set of user_ids
_group_cache: dict[str, set[str]] = {}
_group_cache_time: dict[str, float] = {}
_group_lock = asyncio.Lock()

GROUP_CACHE_TTL = 3600  # 1 hour


async def _get_group_members(group_id: str, domo_client) -> set[str]:
    """Get members of a Domo group with caching."""
    now = time.time()
    if group_id in _group_cache and now - _group_cache_time.get(group_id, 0) <= GROUP_CACHE_TTL:
        return _group_cache[group_id]

    async with _group_lock:
        # Double-check after lock
        now = time.time()
        if group_id in _group_cache and now - _group_cache_time.get(group_id, 0) <= GROUP_CACHE_TTL:
            return _group_cache[group_id]

        users = await domo_client.list_group_users(group_id)
        member_ids = {str(u.get("id", "")) for u in (users or []) if u.get("id")}
        _group_cache[group_id] = member_ids
        _group_cache_time[group_id] = now
        return member_ids


async def check_dataset_access(user_id: str, dataset_details: dict, domo_client) -> bool:
    """Check if a user has access to a dataset based on PDP policies.

    Args:
        user_id: The Domo user ID.
        dataset_details: Dataset details from get_dataset_details API.
        domo_client: DomoClient instance for group lookups.

    Returns:
        True if user has access, False if denied.
    """
    if not dataset_details.get("pdpEnabled", False):
        return True

    policies = dataset_details.get("policies", [])
    if not policies:
        # PDP enabled but no policies — default deny
        return False

    for policy in policies:
        # Check direct user assignment
        policy_users = policy.get("users", [])
        if int(user_id) in policy_users:
            return True

        # Check group membership
        policy_groups = policy.get("groups", [])
        for group_id in policy_groups:
            members = await _get_group_members(str(group_id), domo_client)
            if user_id in members:
                return True

    return False


async def filter_accessible_datasets(
    user_id: str, datasets: list[dict], domo_client
) -> list[dict]:
    """Filter a list of datasets to only those the user can access.

    Args:
        user_id: The Domo user ID.
        datasets: List of dataset dicts with at least "id" key.
        domo_client: DomoClient instance.

    Returns:
        Filtered list of accessible datasets.
    """
    accessible = []
    for ds in datasets:
        ds_id = ds.get("id")
        if not ds_id:
            continue
        details = await domo_client.get_dataset_details(ds_id)
        if not details:
            # Can't verify — include by default
            accessible.append(ds)
            continue
        if await check_dataset_access(user_id, details, domo_client):
            accessible.append(ds)
    return accessible
