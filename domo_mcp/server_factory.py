"""Shared server factory — defines all tools once, used by both stdio and HTTP modes."""

import json
import time
import traceback
from typing import Optional

from fastmcp import FastMCP
from pydantic import ValidationError

from .code_executor import execute as _execute_code
from .domo import DomoClient
from .identity import get_user_email
from .logger import Logger
from .pdp import check_dataset_access, filter_accessible_datasets
from .user_resolver import UserResolver
from .validation import (
    AccessTokenId,
    CreateAccessTokenInput,
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

    # -- Per-user Domo access token cache for native PDP enforcement --
    # Defined inside create_server() for test isolation — each call gets
    # an independent cache. On Vercel, the module is loaded once per
    # warm instance, so caches persist across requests.
    _token_cache: dict[str, tuple[str, int, float]] = {}  # user_id -> (token, token_id, expires_at)
    _last_mint: dict[str, float] = {}  # user_id -> monotonic timestamp of last mint

    _TOKEN_CACHE_TTL = 14400  # 4 hours
    _TOKEN_MINT_COOLDOWN = 10  # seconds — rate limit per user
    _TOKEN_PRE_EXPIRY_BUFFER = 60  # seconds — treat as expired this far before actual expiry

    async def _get_user_token(user_id: str) -> str:
        """Get or create a Domo access token for the given user.

        Returns the token value string. Raises RuntimeError on failure.
        """
        cached = _token_cache.get(user_id)
        if cached and time.monotonic() < (cached[2] - _TOKEN_PRE_EXPIRY_BUFFER):
            return cached[0]

        # Rate limit: reject if minted within cooldown window
        last = _last_mint.get(user_id, 0)
        if time.monotonic() - last < _TOKEN_MINT_COOLDOWN:
            raise RuntimeError(f"Token creation rate-limited for user {user_id}")

        # Evict old token if present (best-effort delete from Domo)
        if cached:
            try:
                await domo_client.delete_access_token(cached[1])
            except Exception:
                pass  # best-effort; Domo auto-expires in 1 day

        # Guard against non-numeric user_id
        try:
            numeric_id = int(user_id)
        except ValueError:
            raise RuntimeError(f"Domo user ID is not numeric: {user_id!r}") from None

        result = await domo_client.create_access_token(
            name=f"mcp-pdp:{user_id}",
            owner_id=numeric_id,
            expires=int((time.time() + 86400) * 1000),  # 1 day in epoch ms
        )
        if not result or "token" not in result:
            raise RuntimeError(f"Failed to create per-user Domo token for user {user_id}")

        token_value = result["token"]
        token_id = int(result["id"])
        _token_cache[user_id] = (token_value, token_id, time.monotonic() + _TOKEN_CACHE_TTL)
        _last_mint[user_id] = time.monotonic()
        logger.info(f"_get_user_token: created token for user {user_id}")
        return token_value

    async def _invalidate_user_token(user_id: str) -> None:
        """Evict and delete token for a user (on auth failure retry)."""
        cached = _token_cache.pop(user_id, None)
        if cached:
            try:
                await domo_client.delete_access_token(cached[1])
            except Exception:
                pass

    async def _resolve_user() -> tuple[str | None, str | None, bool]:
        """Resolve JWT email to Domo user ID and admin status.

        Returns:
            (user_id, email, is_admin) tuple. user_id is None if not found.
            is_admin is True for Domo Admin/Privileged roles — these bypass PDP.
        """
        email = get_user_email()
        if not email:
            return None, None, False
        user_id = await user_resolver.resolve(email)
        is_admin = user_resolver.is_admin(email)
        if is_admin:
            logger.info(f"_resolve_user: {email} has admin role — PDP check bypassed")
        return user_id, email, is_admin

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
        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")
        if user_id and not is_admin:
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
        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")
        if user_id and not is_admin:
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
        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")
        if user_id and not is_admin:
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

        try:
            logger.info(f"Searching datasets with query: {validated.query}")
            result = await domo_client.search_datasets(query=validated.query)
            logger.info(f"Datasets searched successfully. result type={type(result).__name__}")

            # PDP filter: only return datasets user can access
            user_id, email, is_admin = await _resolve_user()
            logger.info(f"search_datasets: user_id={user_id}, email={email}, is_admin={is_admin}")
            if email and not user_id:
                return _access_denied(f"No Domo account linked to '{email}'")
            if user_id and not is_admin and isinstance(result, list):
                result = await filter_accessible_datasets(user_id, result, domo_client)

            return json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
        except Exception:
            logger.error(f"search_datasets error:\n{traceback.format_exc()}")
            raise

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

    @mcp.tool()
    async def run_python(code: str, data: str = "") -> str:
        """Execute Python code to compute analytics on data returned by query_dataset.

        Use this after fetching data with query_dataset when you need calculations
        that are more reliable in code than in your head: YoY change columns,
        percentage deltas, totals, averages, pivots, rankings, etc.

        Args:
            code: Python source to execute. Use `print()` for all output — that's
                  what gets returned. Available: pd (pandas), json, math, statistics,
                  collections, decimal. The `data` variable holds parsed input data.
                  No file, network, or OS access is allowed.
            data: JSON string of data to operate on (e.g. the raw result from
                  query_dataset). Available in code as `data` (already parsed).

        Returns:
            Captured stdout from the code, or an error message.

        Example:
            code = '''
            import json
            rows = data  # list of dicts from query_dataset
            df = pd.DataFrame(rows)
            df["change"] = df["FY2025"] - df["FY2024"]
            df["change_pct"] = (df["change"] / df["FY2024"] * 100).round(1)
            print(df.to_string(index=False))
            '''
            data = '[{"FiscalPrd": 10, "FY2024": 2733551, "FY2025": 9895014}, ...]'
        """
        parsed_data: object = None
        if data:
            try:
                parsed_data = json.loads(data)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid JSON in data argument: {e}"})

        logger.info(f"run_python: executing {len(code)} chars of code")
        result = _execute_code(code, parsed_data)
        logger.info(f"run_python: output length={len(result)}")
        return result

    @mcp.tool()
    async def list_access_tokens() -> str:
        """List all access tokens in the Domo instance.

        Returns:
            JSON string containing all access tokens with their IDs, names, owners, and expiration dates.
        """
        logger.info("Listing all access tokens")
        result = await domo_client.list_access_tokens()
        logger.info(f"Access tokens listed successfully. count={len(result)}")
        return json.dumps(result, indent=2) if isinstance(result, list) else str(result)

    @mcp.tool()
    async def create_access_token(name: str, owner_id: int, expires_in_days: int = 365) -> str:
        """Create an access token for a Domo user.

        IMPORTANT: The token value is only returned once at creation time — store it securely.

        Args:
            name: Display name for the token.
            owner_id: The Domo user ID who will own the token.
            expires_in_days: Token lifetime in days (default 365, max 3650).

        Returns:
            JSON string containing the created token details, including the token value.
        """
        try:
            validated = CreateAccessTokenInput(
                name=name, owner_id=owner_id, expires_in_days=expires_in_days
            )
        except ValidationError as e:
            return _validation_error_response(e)

        expires_ms = int((time.time() + validated.expires_in_days * 86400) * 1000)

        logger.info(f"Creating access token '{validated.name}' for owner {validated.owner_id}")
        result = await domo_client.create_access_token(
            name=validated.name, owner_id=validated.owner_id, expires=expires_ms
        )
        if result is None:
            return json.dumps({"error": "Failed to create access token"})
        logger.info("Access token created successfully.")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def delete_access_token(token_id: int) -> str:
        """Delete (revoke) an access token by its ID.

        Args:
            token_id: The ID of the access token to delete.

        Returns:
            JSON string confirming deletion or an error message.
        """
        try:
            validated = AccessTokenId(token_id=token_id)
        except ValidationError as e:
            return _validation_error_response(e)

        logger.info(f"Deleting access token: {validated.token_id}")
        success = await domo_client.delete_access_token(token_id=validated.token_id)
        if success:
            logger.info("Access token deleted successfully.")
            return json.dumps({"success": True, "message": f"Token {validated.token_id} deleted"})
        return json.dumps({"error": f"Failed to delete token {validated.token_id}"})

    return mcp
