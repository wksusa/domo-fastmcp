"""Domo API client for interacting with Domo's REST API."""

import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class DomoClient:
    def __init__(self, logger: logging.Logger):
        """Initialize the DomoClient with environment variables and constants."""
        self.client_id = os.getenv("DOMO_CLIENT_ID")
        self.client_secret = os.getenv("DOMO_CLIENT_SECRET")
        self.api_host = os.getenv("DOMO_API_HOST", "api.domo.com")
        self.DOMO_API_BASE = f"https://{self.api_host}"
        self.logger = logger
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self) -> str:
        """Get OAuth access token, refreshing if expired."""
        # Return cached token if still valid (with 60s buffer)
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        # Fetch new token
        auth_url = f"{self.DOMO_API_BASE}/oauth/token"
        params = {"grant_type": "client_credentials", "scope": "data"}

        try:
            response = requests.get(
                auth_url,
                params=params,
                auth=(self.client_id, self.client_secret)
            )
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data["access_token"]
            # Token typically expires in 3600 seconds
            self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
            self.logger.info("OAuth token refreshed successfully")
            return self._access_token
        except Exception as e:
            self.logger.error(f"Failed to get OAuth token: {e}")
            raise

    async def make_request(
        self, url: str, method: str, data: dict = None
    ) -> dict[str, Any] | None:
        """Make a request to the Domo API with proper error handling."""
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

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
            url = "/data/ui/v3/datasources/search"
            payload = {
                "entities": ["DATASET"],
                "filters": [
                    {
                        "field": "name_sort",
                        "filterType": "wildcard",
                        "query": f"*{query}*",
                    }
                ],
                "combineResults": True,
                "query": "*",
                "count": 1,
                "offset": 0,
                "sort": {
                    "isRelevance": False,
                    "fieldSorts": [{"field": "create_date", "sortOrder": "DESC"}],
                },
            }
            data = await self.make_request(url, "POST", data=payload)

            if not data:
                self.logger.warning("No data returned for dataset search.")
                return "Unable to search datasets."

            datasets = [
                {"id": ds["id"], "name": ds["name"]}
                for ds in data.get("dataSources", [])
            ]
            return datasets
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
