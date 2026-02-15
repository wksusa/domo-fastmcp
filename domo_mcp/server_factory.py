"""Shared server factory — defines all tools once, used by both stdio and HTTP modes."""

import json
from typing import Optional

from fastmcp import FastMCP
from pydantic import ValidationError

from .domo import DomoClient
from .identity import get_user_email
from .logger import Logger
from .pdp import check_dataset_access, filter_accessible_datasets
from .user_resolver import UserResolver
from .validation import (
    CreateRoleInput,
    DatasetId,
    RoleId,
    SearchQuery,
    SqlQuery,
)

logger = Logger()


def _validation_error_response(e: ValidationError) -> str:
    errors = e.errors()
    messages = [f"{err['loc'][0]}: {err['msg']}" for err in errors]
    return json.dumps({"error": "Validation failed", "details": messages}, indent=2)


def _access_denied(msg: str = "Access denied") -> str:
    return json.dumps({"error": msg})


def create_server(auth=None) -> FastMCP:
    """Create a FastMCP server with all Domo tools registered.

    Args:
        auth: Optional auth verifier (e.g. JWTVerifier) to pass to FastMCP.
    """
    mcp = FastMCP(
        name="domo-mcp",
        instructions="""You are connected to a Domo instance. You can query datasets,
        search for datasets, get schema information, and manage roles. Always use the
        appropriate tool based on what the user is asking for.""",
        auth=auth,
    )

    domo_client = DomoClient(logger)
    user_resolver = UserResolver(domo_client)

    async def _resolve_user() -> str | None:
        """Resolve JWT email to Domo user ID. Returns None if no auth context."""
        email = get_user_email()
        if not email:
            return None
        return await user_resolver.resolve(email)

    @mcp.tool()
    async def get_dataset_schema(dataset_id: str) -> str:
        """Get the schema of a Domo dataset.

        Args:
            dataset_id: The ID of the dataset to get the schema for.

        Returns:
            JSON string containing the dataset schema.
        """
        try:
            validated = DatasetId(dataset_id=dataset_id)
        except ValidationError as e:
            return _validation_error_response(e)

        # PDP check
        email = get_user_email()
        if email:
            user_id = await _resolve_user()
            if not user_id:
                return _access_denied("Your account is not linked to a Domo account")
            details = await domo_client.get_dataset_details(validated.dataset_id)
            if details and not await check_dataset_access(user_id, details, domo_client):
                return _access_denied()

        logger.info(f"Getting schema for dataset: {validated.dataset_id}")
        result = await domo_client.get_dataset_schema(dataset_id=validated.dataset_id)
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
        try:
            validated = DatasetId(dataset_id=dataset_id)
        except ValidationError as e:
            return _validation_error_response(e)

        # PDP check
        email = get_user_email()
        if email:
            user_id = await _resolve_user()
            if not user_id:
                return _access_denied("Your account is not linked to a Domo account")
            details = await domo_client.get_dataset_details(validated.dataset_id)
            if details and not await check_dataset_access(user_id, details, domo_client):
                return _access_denied()

        logger.info(f"Getting metadata for dataset: {validated.dataset_id}")
        result = await domo_client.get_dataset_metadata(dataset_id=validated.dataset_id)
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
        try:
            validated_id = DatasetId(dataset_id=dataset_id)
            validated_sql = SqlQuery(sql=sql)
        except ValidationError as e:
            return _validation_error_response(e)

        # PDP check
        email = get_user_email()
        if email:
            user_id = await _resolve_user()
            if not user_id:
                return _access_denied("Your account is not linked to a Domo account")
            details = await domo_client.get_dataset_details(validated_id.dataset_id)
            if details and not await check_dataset_access(user_id, details, domo_client):
                return _access_denied()

        logger.info(f"Querying dataset {validated_id.dataset_id} with SQL: {validated_sql.sql}")
        result = await domo_client.query_dataset(
            dataset_id=validated_id.dataset_id, sql=validated_sql.sql
        )
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
        try:
            validated = SearchQuery(query=query)
        except ValidationError as e:
            return _validation_error_response(e)

        logger.info(f"Searching datasets with query: {validated.query}")
        result = await domo_client.search_datasets(query=validated.query)
        logger.info("Datasets searched successfully.")

        # PDP filter: only return datasets user can access
        email = get_user_email()
        if email and isinstance(result, list):
            user_id = await _resolve_user()
            if not user_id:
                return _access_denied("Your account is not linked to a Domo account")
            result = await filter_accessible_datasets(user_id, result, domo_client)

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
        try:
            validated = CreateRoleInput(
                name=name, from_role_id=from_role_id, description=description
            )
        except ValidationError as e:
            return _validation_error_response(e)

        logger.info(f"Creating role: {validated.name}")
        role_data = {
            "name": validated.name,
            "fromRoleId": validated.from_role_id,
        }
        if validated.description:
            role_data["description"] = validated.description

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
        try:
            validated = RoleId(role_id=role_id)
        except ValidationError as e:
            return _validation_error_response(e)

        logger.info(f"Listing authorities for role: {validated.role_id}")
        result = await domo_client.list_role_authorities(role_id=validated.role_id)
        logger.info("Authorities listed successfully.")
        return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)

    return mcp
