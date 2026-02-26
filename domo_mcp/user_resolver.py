"""Resolve email addresses to Domo user IDs with caching."""

import asyncio
import time

from .logger import Logger

logger = Logger()


class UserResolver:
    """Maps email addresses to Domo user IDs.

    Paginates through all Domo users and caches the mapping for 1 hour.
    Thread-safe via asyncio.Lock.
    """

    CACHE_TTL = 3600  # 1 hour

    # Domo roles that bypass PDP natively
    ADMIN_ROLES = {"Admin", "Privileged"}

    def __init__(self, domo_client):
        self._domo_client = domo_client
        self._cache: dict[str, str] = {}       # email -> user_id
        self._role_cache: dict[str, str] = {}  # email -> role name
        self._cache_time: float = 0
        self._lock = asyncio.Lock()

    async def resolve(self, email: str) -> str | None:
        """Resolve an email address to a Domo user ID.

        Args:
            email: The email address to look up.

        Returns:
            Domo user ID string, or None if not found.
        """
        if time.time() - self._cache_time > self.CACHE_TTL:
            await self._refresh_cache()
        normalized = email.lower()
        user_id = self._cache.get(normalized)
        role = self._role_cache.get(normalized, "")
        if user_id:
            logger.info(f"UserResolver: resolved {normalized} -> user_id={user_id} role={role}")
        else:
            logger.warning(
                f"UserResolver: no Domo user found for '{normalized}' "
                f"(cache has {len(self._cache)} users)"
            )
        return user_id

    def is_admin(self, email: str) -> bool:
        """Return True if the user has a Domo role that bypasses PDP (Admin or Privileged)."""
        role = self._role_cache.get(email.lower(), "")
        return role in self.ADMIN_ROLES

    async def _refresh_cache(self):
        async with self._lock:
            # Double-check after acquiring lock
            if time.time() - self._cache_time <= self.CACHE_TTL:
                return

            new_cache: dict[str, str] = {}
            new_role_cache: dict[str, str] = {}
            offset = 0
            limit = 500

            while True:
                users = await self._domo_client.list_users(limit=limit, offset=offset)
                if not users:
                    break
                for user in users:
                    if not isinstance(user, dict):
                        continue
                    email = user.get("email", "").lower()
                    user_id = str(user.get("id", ""))
                    role = user.get("role", "")
                    if email and user_id:
                        new_cache[email] = user_id
                        if role:
                            new_role_cache[email] = role
                if len(users) < limit:
                    break
                offset += limit

            self._cache = new_cache
            self._role_cache = new_role_cache
            self._cache_time = time.time()
            logger.info(
                f"UserResolver: refreshed cache — {len(new_cache)} users loaded, "
                f"{sum(1 for r in new_role_cache.values() if r in self.ADMIN_ROLES)} admins"
            )
            if new_cache:
                sample = list(new_cache.keys())[:3]
                logger.debug(f"UserResolver: sample emails: {sample}")
