"""Domo API client for interacting with Domo's REST API."""

import logging
import os
import time
from typing import Any

import requests
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

class DomoClient:
    def __init__(self, logger: logging.Logger):
        """Initialize the DomoClient with environment variables and constants."""
        self.logger = logger

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

    def _get_headers(self) -> dict:
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
                response = requests.post(
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

    async def make_request(
        self, url: str, method: str, data: dict = None
    ) -> dict[str, Any] | None:
        """Make a request to the Domo API with proper error handling."""
        headers = self._get_headers()
        full_url = f"{self.DOMO_API_BASE}{url}"

        try:
            if method.upper() == "GET":
                response = requests.get(full_url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(full_url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = requests.delete(full_url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()

            # Handle empty responses
            if not response.content:
                return None

            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP request failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
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
                if data:
                    return [{"id": ds["id"], "name": ds["name"]} for ds in data.get("dataSources", [])]
                return []
            else:
                # OAuth mode: public API doesn't have search, so list and filter client-side
                all_datasets = []
                query_lower = query.lower()

                for offset in range(0, 500, 50):
                    url = f"/v1/datasets?limit=50&offset={offset}&sort=name"
                    data = await self.make_request(url, "GET")
                    if not data:
                        break

                    for ds in data:
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
