import json
import logging
import sys
from typing import Optional
from .domo import DomoClient
import mcp
from mcp.server import NotificationOptions, Server
import mcp.types as types
from pydantic import BaseModel, Field


def setup_logger():
    class Logger:
        def info(self, message):
            print(f"[INFO] {message}", file=sys.stderr)

        def warning(self, message):
            print(f"[WARNING] {message}", file=sys.stderr)

        def error(self, message):
            print(f"[ERROR] {message}", file=sys.stderr)

    return Logger()

logger = setup_logger()
domo_client = DomoClient(logger)
server = Server("domo-mcp")

# options =
class ToolModel(BaseModel):
    @classmethod
    def as_tool(cls):
        return types.Tool(
            name="Domo" + cls.__name__,
            description=cls.__doc__,
            inputSchema=cls.model_json_schema()
        )

class GetDatasetSchema(ToolModel):
    """Get a Domo dataset schema."""
    dataset_id: str = Field(description="The ID of the dataset to get the schema for.")

class GetDatasetMetadata(ToolModel):
    """Get metadata for a Domo dataset."""
    dataset_id: str = Field(description="The ID of the dataset to get metadata for.")

class QueryDataset(ToolModel):
    """Query a Domo dataset using SQL."""
    dataset_id: str = Field(description="The ID of the dataset to query.")
    sql: str = Field(description="The SQL query to execute on the dataset.")

class SearchDatasets(ToolModel):
    """Search for datasets in a Domo instance by name."""
    query: str = Field(description="The search query to find datasets by name.")

class ListRoles(ToolModel):
    """List all roles in the Domo instance."""
    pass

class RoleData(BaseModel):
    """Model for role data as expected by the API."""
    name: str = Field(description="The name of the role.")
    description: Optional[str] = Field(default=None, description="A description of the role.")
    fromRoleId: int = Field(description="The role ID to copy from.")

class CreateRole(ToolModel):
    """Create a new role in the Domo instance."""
    role_data: RoleData = Field(description="The data for the role to create.")

class ListRoleAuthorities(ToolModel):
    """List authorities for a specific role in the Domo instance."""
    role_id: int = Field(description="The ID of the role to list authorities for.")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return []

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    return []

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    logger.info("Listing available tools")
    tools = [
        GetDatasetSchema.as_tool(),
        GetDatasetMetadata.as_tool(),
        QueryDataset.as_tool(),
        SearchDatasets.as_tool(),
        ListRoles.as_tool(),
        CreateRole.as_tool(),
        ListRoleAuthorities.as_tool(),  # New tool added here
    ]
    logger.info(f"Available tools: {[tool.name for tool in tools]}")
    return tools

@server.call_tool()
async def handle_call_tool(
        name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    assert name[:4] == "Domo", f"Unknown tool: {name}"
    try:
        match name[4:]:
            case "GetDatasetSchema": 
                logger.info(f"Performing search with arguments: {arguments}")
                search_results = await domo_client.get_dataset_schema(
                    dataset_id=arguments["dataset_id"]
                )
                logger.info("Schema fetched successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(search_results, indent=2)
                )]
            case "GetDatasetMetadata":
                logger.info(f"Fetching metadata with arguments: {arguments}")
                metadata = await domo_client.get_dataset_metadata(
                    dataset_id=arguments["dataset_id"]
                )
                logger.info("Metadata fetched successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(metadata, indent=2)
                )]
            case "QueryDataset":
                logger.info(f"Executing query with arguments: {arguments}")
                query_results = await domo_client.query_dataset(
                    dataset_id=arguments["dataset_id"],
                    sql=arguments["sql"]
                )
                logger.info("Query executed successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(query_results, indent=2)
                )]
            case "SearchDatasets":
                logger.info(f"Searching datasets with arguments: {arguments}")
                search_results = await domo_client.search_datasets(
                    query=arguments["query"]
                )
                logger.info("Datasets searched successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(search_results, indent=2)
                )]
            case "ListRoles":
                logger.info(f"Listing roles with arguments: {arguments}")
                roles = await domo_client.list_roles()
                logger.info("Roles listed successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(roles, indent=2)
                )]
            case "CreateRole":
                logger.info(f"Creating role with arguments: {arguments}")
                created_role = await domo_client.create_role(
                    role_data=arguments["role_data"]
                )
                logger.info("Role created successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(created_role, indent=2)
                )]
            case "ListRoleAuthorities":
                logger.info(f"Listing authorities for role with arguments: {arguments}")
                result = await domo_client.list_role_authorities(
                    role_id=arguments["role_id"]
                )
                logger.info("Authorities listed successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            case _:
                error_msg = f"Unknown tool: {name}"
                logger.error(error_msg)
                return [types.TextContent(
                    type="text",
                    text=error_msg
                )]
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return [types.TextContent(
            type="text",
            text=error_msg
        )]

async def main():
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error occurred: {str(e)}")
        raise