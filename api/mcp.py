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

class DomoClient:
    def __init__(self):
        self.client_id = os.getenv("DOMO_CLIENT_ID")
        self.client_secret = os.getenv("DOMO_CLIENT_SECRET")
        self.api_host = os.getenv("DOMO_API_HOST", "api.domo.com")
        self.DOMO_API_BASE = f"https://{self.api_host}"
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self) -> str:
        """Get OAuth access token, refreshing if expired."""
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise ValueError(
                f"Missing Domo credentials. DOMO_CLIENT_ID={'set' if self.client_id else 'missing'}, "
                f"DOMO_CLIENT_SECRET={'set' if self.client_secret else 'missing'}"
            )

        # OAuth always uses api.domo.com regardless of instance host
        auth_url = "https://api.domo.com/oauth/token"

        # Domo OAuth requires POST with params in query string
        response = requests.post(
            auth_url,
            params={"grant_type": "client_credentials", "scope": "data"},
            auth=(self.client_id, self.client_secret)
        )

        if not response.ok:
            raise ValueError(
                f"Domo OAuth failed: {response.status_code} - {response.text[:500]}"
            )

        try:
            token_data = response.json()
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Domo OAuth returned invalid JSON: {response.text[:500]}"
            ) from e

        self._access_token = token_data["access_token"]
        self._token_expires_at = time.time() + token_data.get("expires_in", 3600)
        return self._access_token

    async def make_request(self, url: str, method: str, data: dict = None) -> dict[str, Any] | None:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
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
        payload = {
            "entities": ["DATASET"],
            "filters": [{"field": "name_sort", "filterType": "wildcard", "query": f"*{query}*"}],
            "combineResults": True,
            "query": "*",
            "count": 10,
            "offset": 0,
            "sort": {"isRelevance": False, "fieldSorts": [{"field": "create_date", "sortOrder": "DESC"}]},
        }
        data = await self.make_request("/data/ui/v3/datasources/search", "POST", data=payload)
        if data:
            return [{"id": ds["id"], "name": ds["name"]} for ds in data.get("dataSources", [])]
        return []

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
# Vercel mounts this file at /api/mcp, so use "/" as the path
# The MCP endpoint will be at /api/mcp (handled by Vercel routing)
app = mcp.http_app(path="/", middleware=middleware, stateless_http=True)
