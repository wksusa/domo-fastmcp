"""Domo MCP Server - FastMCP implementation."""

import json
import os
from typing import Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .domo import DomoClient
from .logger import Logger


# Initialize FastMCP server
mcp = FastMCP(
    name="domo-mcp",
    instructions="""You are connected to a Domo instance. You can query datasets,
    search for datasets, get schema information, and manage roles. Always use the
    appropriate tool based on what the user is asking for."""
)


logger = Logger()
domo_client = DomoClient(logger)


# Pydantic model for role creation
class RoleData(BaseModel):
    """Data for creating a new role."""
    name: str = Field(description="The name of the role.")
    description: Optional[str] = Field(default=None, description="A description of the role.")
    fromRoleId: int = Field(description="The role ID to copy permissions from.")


@mcp.tool()
async def get_dataset_schema(dataset_id: str) -> str:
    """Get the schema of a Domo dataset.

    Args:
        dataset_id: The ID of the dataset to get the schema for.

    Returns:
        JSON string containing the dataset schema.
    """
    logger.info(f"Getting schema for dataset: {dataset_id}")
    result = await domo_client.get_dataset_schema(dataset_id=dataset_id)
    logger.info("Schema fetched successfully.")
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def get_dataset_metadata(dataset_id: str) -> str:
    """Get metadata for a Domo dataset.

    Args:
        dataset_id: The ID of the dataset to get metadata for.

    Returns:
        JSON string containing the dataset metadata.
    """
    logger.info(f"Getting metadata for dataset: {dataset_id}")
    result = await domo_client.get_dataset_metadata(dataset_id=dataset_id)
    logger.info("Metadata fetched successfully.")
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def query_dataset(dataset_id: str, sql: str) -> str:
    """Query a Domo dataset using SQL.

    Args:
        dataset_id: The ID of the dataset to query.
        sql: The SQL query to execute on the dataset.

    Returns:
        JSON string containing the query results.
    """
    logger.info(f"Querying dataset {dataset_id} with SQL: {sql}")
    result = await domo_client.query_dataset(dataset_id=dataset_id, sql=sql)
    logger.info("Query executed successfully.")
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def search_datasets(query: str) -> str:
    """Search for datasets in a Domo instance by name.

    Args:
        query: The search query to find datasets by name.

    Returns:
        JSON string containing matching datasets with their IDs and names.
    """
    logger.info(f"Searching datasets with query: {query}")
    result = await domo_client.search_datasets(query=query)
    logger.info("Datasets searched successfully.")
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)


@mcp.tool()
async def list_roles() -> str:
    """List all roles in the Domo instance.

    Returns:
        JSON string containing all roles in the Domo instance.
    """
    logger.info("Listing all roles")
    result = await domo_client.list_roles()
    logger.info("Roles listed successfully.")
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)


@mcp.tool()
async def create_role(name: str, from_role_id: int, description: Optional[str] = None) -> str:
    """Create a new role in the Domo instance.

    Args:
        name: The name of the new role.
        from_role_id: The role ID to copy permissions from.
        description: Optional description of the role.

    Returns:
        JSON string containing the created role data.
    """
    logger.info(f"Creating role: {name}")
    role_data = {
        "name": name,
        "fromRoleId": from_role_id,
    }
    if description:
        role_data["description"] = description

    result = await domo_client.create_role(role_data=role_data)
    logger.info("Role created successfully.")
    return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)


@mcp.tool()
async def list_role_authorities(role_id: int) -> str:
    """List authorities (permissions) for a specific role in the Domo instance.

    Args:
        role_id: The ID of the role to list authorities for.

    Returns:
        JSON string containing the role's authorities.
    """
    logger.info(f"Listing authorities for role: {role_id}")
    result = await domo_client.list_role_authorities(role_id=role_id)
    logger.info("Authorities listed successfully.")
    return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
