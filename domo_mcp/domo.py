"""Domo API client for interacting with Domo's REST API."""

import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# ============================================================================
# Domo API Client
# ============================================================================
#
# Supports two authentication methods:
#
# 1. Developer Token (preferred for full API access):
#    - Set DOMO_DEVELOPER_TOKEN and DOMO_HOST
#    - Uses org-specific domain (e.g., wksusa.domo.com)
#    - Access to internal UI APIs (search, etc.)
#
# 2. OAuth Client Credentials (fallback):
#    - Set DOMO_CLIENT_ID and DOMO_CLIENT_SECRET
#    - Uses api.domo.com for all calls
#    - Limited to public API endpoints only
# ============================================================================

# Configuration constants
DEFAULT_TIMEOUT = 60.0  # seconds
CONNECT_TIMEOUT = 10.0  # seconds
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB
SLOW_REQUEST_THRESHOLD = 5.0  # seconds

class DomoClient:
    def __init__(self, logger: logging.Logger):
        """Initialize the DomoClient with environment variables and constants."""
        self.logger = logger

        # Configure timeouts
        self.timeout = httpx.Timeout(
            timeout=DEFAULT_TIMEOUT,
            connect=CONNECT_TIMEOUT
        )

        # Developer Token auth (preferred - gives access to internal APIs)
        self.developer_token = os.getenv("DOMO_DEVELOPER_TOKEN")
        self.domo_host = os.getenv("DOMO_HOST", "").rstrip("/")

        # OAuth auth (fallback - public API only)
        self.client_id = os.getenv("DOMO_CLIENT_ID")
        self.client_secret = os.getenv("DOMO_CLIENT_SECRET")

        # Determine auth mode and API base
        if self.developer_token and self.domo_host:
            self.auth_mode = "developer_token"
            self.DOMO_API_BASE = f"https://{self.domo_host}/api"
            self.logger.info(f"Using Developer Token auth with host: {self.domo_host}")
        elif self.client_id and self.client_secret:
            self.auth_mode = "oauth"
            self.DOMO_API_BASE = "https://api.domo.com"
            self.logger.info("Using OAuth auth with api.domo.com")
        else:
            raise ValueError(
                "Missing Domo credentials. Set either:\n"
                "  - DOMO_DEVELOPER_TOKEN + DOMO_HOST (for full API access), or\n"
                "  - DOMO_CLIENT_ID + DOMO_CLIENT_SECRET (for public API only)"
            )

        self._oauth_token = None
        self._token_expires_at = 0

        # For Developer Token mode, also check for OAuth credentials
        # needed for public API calls (/v1/users, /v1/datasets, etc.)
        # that only work via api.domo.com with OAuth
        self._public_api_client_id = self.client_id or os.getenv("DOMO_CLIENT_ID")
        self._public_api_client_secret = self.client_secret or os.getenv("DOMO_CLIENT_SECRET")
        self._public_api_token = None
        self._public_api_token_expires_at = 0
        if self.auth_mode == "developer_token" and self._public_api_client_id:
            self.logger.info("OAuth credentials available for public API calls (/v1/...)")

    async def _get_headers(self) -> dict:
        """Get request headers based on auth mode."""
        if self.auth_mode == "developer_token":
            return {
                "X-DOMO-Developer-Token": self.developer_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        else:
            # OAuth mode - get/refresh token
            if not self._oauth_token or time.time() >= (self._token_expires_at - 60):
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        "https://api.domo.com/oauth/token",
                        params={"grant_type": "client_credentials", "scope": "data"},
                        auth=(self.client_id, self.client_secret)
                    )
                    response.raise_for_status()
                    token_data = response.json()
                    self._oauth_token = token_data["access_token"]
                    self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
                    self.logger.info("OAuth token refreshed successfully")

            return {
                "Authorization": f"Bearer {self._oauth_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

    async def _get_public_api_headers(self) -> dict | None:
        """Get OAuth headers for public API calls (api.domo.com/v1/...).

        Returns None if OAuth credentials are not available.
        """
        if not self._public_api_client_id or not self._public_api_client_secret:
            return None

        if not self._public_api_token or time.time() >= (self._public_api_token_expires_at - 60):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    "https://api.domo.com/oauth/token",
                    params={"grant_type": "client_credentials", "scope": "data user"},
                    auth=(self._public_api_client_id, self._public_api_client_secret)
                )
                response.raise_for_status()
                token_data = response.json()
                self._public_api_token = token_data["access_token"]
                self._public_api_token_expires_at = time.time() + token_data.get("expires_in", 3600)
                self.logger.info("Public API OAuth token refreshed")

        return {
            "Authorization": f"Bearer {self._public_api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def make_request(
        self, url: str, method: str, data: dict = None
    ) -> dict[str, Any] | None:
        """Make a request to the Domo API with proper error handling, timeout tracking, and response size limits."""
        # Public API endpoints (/v1/...) require OAuth via api.domo.com.
        # Developer Tokens only work with instance-domain internal APIs.
        if url.startswith("/v1/") and self.auth_mode == "developer_token":
            public_headers = await self._get_public_api_headers()
            if public_headers:
                headers = public_headers
                full_url = f"https://api.domo.com{url}"
            else:
                self.logger.warning(
                    f"Public API call {url} requires OAuth credentials "
                    "(DOMO_CLIENT_ID + DOMO_CLIENT_SECRET) — Developer Token won't work with api.domo.com"
                )
                headers = await self._get_headers()
                full_url = f"{self.DOMO_API_BASE}{url}"
        else:
            headers = await self._get_headers()
            full_url = f"{self.DOMO_API_BASE}{url}"
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(full_url, headers=headers)
                elif method.upper() == "POST":
                    response = await client.post(full_url, headers=headers, json=data)
                elif method.upper() == "DELETE":
                    response = await client.delete(full_url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Calculate request duration
                duration = time.time() - start_time

                # Log slow requests
                if duration > SLOW_REQUEST_THRESHOLD:
                    self.logger.warning(
                        f"Slow request detected: {method} {url} took {duration:.2f}s"
                    )
                else:
                    self.logger.info(f"{method} {url} completed in {duration:.2f}s")

                response.raise_for_status()

                # Handle empty responses
                if not response.content:
                    return None

                # Check response size
                response_size = len(response.content)
                if response_size > MAX_RESPONSE_SIZE:
                    self.logger.error(
                        f"Response too large: {response_size} bytes exceeds limit of {MAX_RESPONSE_SIZE} bytes"
                    )
                    return None
                elif response_size > MAX_RESPONSE_SIZE / 2:
                    self.logger.warning(
                        f"Large response: {response_size} bytes ({response_size / (1024*1024):.2f}MB)"
                    )

                return response.json()
        except httpx.TimeoutException as e:
            duration = time.time() - start_time
            self.logger.error(
                f"Request timeout after {duration:.2f}s: {method} {url} - {str(e)}"
            )
            return None
        except httpx.HTTPStatusError as e:
            duration = time.time() - start_time
            self.logger.error(
                f"HTTP request failed after {duration:.2f}s: {method} {url} - {str(e)}"
            )
            return None
        except httpx.RequestError as e:
            duration = time.time() - start_time
            self.logger.error(
                f"Request error after {duration:.2f}s: {method} {url} - {str(e)}"
            )
            return None
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(
                f"Unexpected error after {duration:.2f}s: {method} {url} - {str(e)}"
            )
            return None

    async def get_dataset_metadata(self, dataset_id: str) -> str:
        """Get metadata for a Domo dataset."""
        try:
            url = f"/data/v3/datasources/{dataset_id}?part=core"
            data = await self.make_request(url, "GET")

            if not data:
                self.logger.warning("No data returned for dataset metadata.")
                return "Unable to fetch dataset metadata."

            return data
        except Exception as e:
            self.logger.error(f"Error fetching dataset metadata: {str(e)}")
            return f"Error fetching dataset metadata: {str(e)}"

    async def get_dataset_schema(self, dataset_id: str) -> str:
        """Get the schema of a Domo dataset."""
        try:
            url = f"/data/v2/datasources/{dataset_id}/schemas/latest"
            data = await self.make_request(url, "GET")

            if not data:
                self.logger.warning("No data returned for dataset schema.")
                return "Unable to fetch dataset schema."

            return data
        except Exception as e:
            self.logger.error(f"Error fetching dataset schema: {str(e)}")
            return f"Error fetching dataset schema: {str(e)}"

    async def query_dataset(self, dataset_id: str, sql: str) -> str:
        """Query a Domo dataset using SQL."""
        try:
            url = f"/query/v1/execute/{dataset_id}"
            data = await self.make_request(url, "POST", data={"sql": sql})

            if not data:
                self.logger.warning("No data returned for dataset query.")
                return "Unable to execute query on the dataset."

            return data
        except Exception as e:
            self.logger.error(f"Error executing query on dataset: {str(e)}")
            return f"Error executing query on dataset: {str(e)}"

    async def search_datasets(self, query: str) -> str:
        """Search for datasets in a Domo instance by name."""
        try:
            if self.auth_mode == "developer_token":
                # Developer Token mode: use internal UI search API (efficient, server-side)
                payload = {
                    "entities": ["DATASET"],
                    "filters": [{"field": "name_sort", "filterType": "wildcard", "query": f"*{query}*"}],
                    "combineResults": True,
                    "query": "*",
                    "count": 50,
                    "offset": 0,
                    "sort": {"isRelevance": False, "fieldSorts": [{"field": "create_date", "sortOrder": "DESC"}]},
                }
                data = await self.make_request("/data/ui/v3/datasources/search", "POST", data=payload)
                if not data:
                    return []
                if not isinstance(data, dict):
                    self.logger.error(
                        f"Unexpected search response type: {type(data).__name__}, value: {str(data)[:200]}"
                    )
                    return []
                return [
                    {"id": ds["id"], "name": ds["name"]}
                    for ds in data.get("dataSources", [])
                    if isinstance(ds, dict)
                ]
            else:
                # OAuth mode: public API doesn't have search, so list and filter client-side
                all_datasets = []
                query_lower = query.lower()

                for offset in range(0, 500, 50):
                    url = f"/v1/datasets?limit=50&offset={offset}&sort=name"
                    data = await self.make_request(url, "GET")
                    if not data:
                        break
                    if not isinstance(data, list):
                        self.logger.error(
                            f"Unexpected datasets response type: {type(data).__name__}"
                        )
                        break

                    for ds in data:
                        if not isinstance(ds, dict):
                            continue
                        name = ds.get("name", "")
                        if query_lower in name.lower():
                            all_datasets.append({"id": ds.get("id"), "name": name})

                    if len(data) < 50:
                        break

                return all_datasets
        except Exception as e:
            self.logger.error(f"Error searching datasets: {str(e)}")
            return f"Error searching datasets: {str(e)}"

    async def list_roles(self) -> str:
        """List all roles in the Domo instance."""
        try:
            url = "/authorization/v1/roles"
            data = await self.make_request(url, "GET")

            if not data:
                self.logger.warning("No data returned for role list.")
                return "Unable to fetch role list."

            return data
        except Exception as e:
            self.logger.error(f"Error fetching role list: {str(e)}")
            return f"Error fetching role list: {str(e)}"

    async def create_role(self, role_data: dict) -> str:
        """Create a new role in the Domo instance."""
        try:
            url = "/authorization/v1/roles"
            data = await self.make_request(url, "POST", data=role_data)

            if not data:
                self.logger.warning("No data returned for role creation.")
                return "Unable to create role."

            return data
        except Exception as e:
            self.logger.error(f"Error creating role: {str(e)}")
            return f"Error creating role: {str(e)}"

    async def list_role_authorities(self, role_id: str) -> str:
        """List all authorities for a given role."""
        try:
            url = f"/authorization/v1/roles/{role_id}/authorities"
            data = await self.make_request(url, "GET")

            if not data:
                self.logger.warning("No data returned for role authorities.")
                return "Unable to fetch role authorities."

            return data
        except Exception as e:
            self.logger.error(f"Error fetching role authorities: {str(e)}")
            return f"Error fetching role authorities: {str(e)}"

    async def list_users(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """List Domo users with pagination.

        Args:
            limit: Maximum number of users to return per page.
            offset: Starting offset for pagination.

        Returns:
            List of user dicts with id, email, etc.
        """
        try:
            url = f"/v1/users?limit={limit}&offset={offset}"
            data = await self.make_request(url, "GET")
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"Error listing users: {str(e)}")
            return []

    async def get_dataset_details(self, dataset_id: str) -> dict | None:
        """Get dataset details including PDP policies.

        Args:
            dataset_id: The dataset ID.

        Returns:
            Dict with pdpEnabled, policies, etc. or None on error.
        """
        try:
            url = f"/v1/datasets/{dataset_id}"
            data = await self.make_request(url, "GET")
            return data if isinstance(data, dict) else None
        except Exception as e:
            self.logger.error(f"Error fetching dataset details: {str(e)}")
            return None

    async def list_group_users(self, group_id: str) -> list[dict]:
        """List users in a Domo group.

        Args:
            group_id: The group ID.

        Returns:
            List of user dicts.
        """
        try:
            url = f"/v1/groups/{group_id}/users"
            data = await self.make_request(url, "GET")
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"Error listing group users: {str(e)}")
            return []

    async def list_access_tokens(self) -> list[dict]:
        """List all access tokens in the Domo instance."""
        try:
            url = "/data/v1/accesstokens"
            data = await self.make_request(url, "GET")
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"Error listing access tokens: {str(e)}")
            return []

    async def create_access_token(self, name: str, owner_id: int, expires: int) -> dict | None:
        """Create an access token for a Domo user.

        Args:
            name: Display name for the token.
            owner_id: Domo user ID who will own the token.
            expires: Expiration timestamp in epoch milliseconds.

        Returns:
            Dict with token details (including the token value), or None on error.
        """
        try:
            url = "/data/v1/accesstokens"
            payload = {"name": name, "ownerId": owner_id, "expires": expires}
            data = await self.make_request(url, "POST", data=payload)
            return data if isinstance(data, dict) else None
        except Exception as e:
            self.logger.error(f"Error creating access token: {str(e)}")
            return None

    async def delete_access_token(self, token_id: int) -> bool:
        """Delete (revoke) an access token.

        Args:
            token_id: The ID of the access token to delete.

        Returns:
            True if deleted successfully, False on error.
        """
        try:
            url = f"/data/v1/accesstokens/{token_id}"
            await self.make_request(url, "DELETE")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting access token: {str(e)}")
            return False
