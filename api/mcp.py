"""Vercel serverless function endpoint for Domo MCP server."""

import json
import os
from typing import Optional

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.auth import AuthMiddleware
from domo_mcp.domo import DomoClient
from domo_mcp.logger import Logger


logger = Logger()
domo_client = DomoClient(logger)


# ============================================================================
# FastMCP Server
# ============================================================================

mcp = FastMCP(
    name="domo-mcp",
    instructions="""You are connected to a Domo instance. You can query datasets,
    search for datasets, get schema information, and manage roles."""
)


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


def get_valid_tokens() -> list[str]:
    """Load and validate authentication tokens from environment.

    Returns:
        List of valid Bearer tokens for authentication.
        Empty list if MCP_AUTH_TOKENS is not set (authentication disabled).
    """
    tokens_str = os.getenv("MCP_AUTH_TOKENS", "")
    if not tokens_str:
        logger.warning("No MCP_AUTH_TOKENS set - authentication disabled!")
        return []

    tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]
    if not tokens:
        logger.warning("MCP_AUTH_TOKENS is empty - authentication disabled!")
        return []

    return tokens


# Parse valid tokens from environment
valid_tokens = get_valid_tokens()

# Create the ASGI app at module level
# Use path that matches Vercel routing
app = mcp.http_app(path="/api/mcp", middleware=middleware, stateless_http=True)

# Wrap with authentication middleware if tokens are configured
if valid_tokens:
    app = AuthMiddleware(app, valid_tokens)
    logger.info(f"Authentication enabled with {len(valid_tokens)} valid token(s)")
else:
    logger.warning("Authentication is DISABLED - all requests will be accepted")
