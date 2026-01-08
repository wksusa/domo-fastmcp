"""Vercel serverless function endpoint for Domo MCP server."""

import json
import os
import time
from typing import Any, Optional

import requests
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware


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
    def __init__(self):
        # Developer Token auth (preferred - gives access to internal APIs)
        self.developer_token = os.getenv("DOMO_DEVELOPER_TOKEN")
        self.domo_host = os.getenv("DOMO_HOST", "").rstrip("/")

        # OAuth auth (fallback - public API only)
        self.client_id = os.getenv("DOMO_CLIENT_ID")
        self.client_secret = os.getenv("DOMO_CLIENT_SECRET")

        # Determine auth mode and API base
        if self.developer_token and self.domo_host:
            self.auth_mode = "developer_token"
            self.DOMO_API_BASE = f"https://{self.domo_host}"
        elif self.client_id and self.client_secret:
            self.auth_mode = "oauth"
            self.DOMO_API_BASE = "https://api.domo.com"
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

            return {
                "Authorization": f"Bearer {self._oauth_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

    async def make_request(self, url: str, method: str, data: dict = None) -> dict[str, Any] | None:
        headers = self._get_headers()
        full_url = f"{self.DOMO_API_BASE}{url}"

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

        # Try to parse JSON, return raw text if it fails
        try:
            return response.json()
        except ValueError:
            return {"raw_response": response.text}

    async def get_dataset_metadata(self, dataset_id: str):
        return await self.make_request(f"/data/v3/datasources/{dataset_id}?part=core", "GET")

    async def get_dataset_schema(self, dataset_id: str):
        return await self.make_request(f"/data/v2/datasources/{dataset_id}/schemas/latest", "GET")

    async def query_dataset(self, dataset_id: str, sql: str):
        return await self.make_request(f"/query/v1/execute/{dataset_id}", "POST", data={"sql": sql})

    async def search_datasets(self, query: str):
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

    async def list_roles(self):
        return await self.make_request("/authorization/v1/roles", "GET")

    async def create_role(self, role_data: dict):
        return await self.make_request("/authorization/v1/roles", "POST", data=role_data)

    async def list_role_authorities(self, role_id: int):
        return await self.make_request(f"/authorization/v1/roles/{role_id}/authorities", "GET")


# ============================================================================
# FastMCP Server
# ============================================================================

mcp = FastMCP(
    name="domo-mcp",
    instructions="""You are connected to a Domo instance. You can query datasets,
    search for datasets, get schema information, and manage roles."""
)

domo_client = DomoClient()


@mcp.tool()
async def get_dataset_schema(dataset_id: str) -> str:
    """Get the schema of a Domo dataset."""
    result = await domo_client.get_dataset_schema(dataset_id=dataset_id)
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def get_dataset_metadata(dataset_id: str) -> str:
    """Get metadata for a Domo dataset."""
    result = await domo_client.get_dataset_metadata(dataset_id=dataset_id)
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def query_dataset(dataset_id: str, sql: str) -> str:
    """Query a Domo dataset using SQL."""
    result = await domo_client.query_dataset(dataset_id=dataset_id, sql=sql)
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def search_datasets(query: str) -> str:
    """Search for datasets in a Domo instance by name."""
    result = await domo_client.search_datasets(query=query)
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)


@mcp.tool()
async def list_roles() -> str:
    """List all roles in the Domo instance."""
    result = await domo_client.list_roles()
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)


@mcp.tool()
async def create_role(name: str, from_role_id: int, description: Optional[str] = None) -> str:
    """Create a new role in the Domo instance."""
    role_data = {"name": name, "fromRoleId": from_role_id}
    if description:
        role_data["description"] = description
    result = await domo_client.create_role(role_data=role_data)
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def list_role_authorities(role_id: int) -> str:
    """List authorities (permissions) for a specific role."""
    result = await domo_client.list_role_authorities(role_id=role_id)
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)


# ============================================================================
# ASGI App for Vercel
# ============================================================================

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["mcp-protocol-version", "mcp-session-id", "Authorization", "Content-Type"],
    )
]

# Create the ASGI app at module level
# Use path that matches Vercel routing
app = mcp.http_app(path="/api/mcp", middleware=middleware, stateless_http=True)
