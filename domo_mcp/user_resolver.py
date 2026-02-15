"""Resolve email addresses to Domo user IDs with caching."""

import asyncio
import time


class UserResolver:
    """Maps email addresses to Domo user IDs.

    Paginates through all Domo users and caches the mapping for 1 hour.
    Thread-safe via asyncio.Lock.
    """

    CACHE_TTL = 3600  # 1 hour

    def __init__(self, domo_client):
        self._domo_client = domo_client
        self._cache: dict[str, str] = {}  # email -> user_id
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
        return self._cache.get(email.lower())

    async def _refresh_cache(self):
        async with self._lock:
            # Double-check after acquiring lock
            if time.time() - self._cache_time <= self.CACHE_TTL:
                return

            new_cache: dict[str, str] = {}
            offset = 0
            limit = 500

            while True:
                users = await self._domo_client.list_users(limit=limit, offset=offset)
                if not users:
                    break
                for user in users:
                    email = user.get("email", "").lower()
                    user_id = str(user.get("id", ""))
                    if email and user_id:
                        new_cache[email] = user_id
                if len(users) < limit:
                    break
                offset += limit

            self._cache = new_cache
            self._cache_time = time.time()
