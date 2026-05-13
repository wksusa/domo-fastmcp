"""Shared server factory — defines all tools once, used by both stdio and HTTP modes."""

import json
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.utilities.types import Image
from mcp.types import Icon
from pydantic import Field, ValidationError

from .code_executor import _error_result, execute as _execute_code
from .domo import DomoClient, DomoRequestError
from .identity import get_user_email, is_jwt_auth
from .logger import Logger
from .resources import python_env as _python_env_resource
from .user_resolver import UserResolver
from .validation import (
    CreateRoleInput,
    DatasetId,
    RoleId,
    SearchQuery,
    SqlQuery,
)

logger = Logger()
_structured_logger = logging.getLogger("domo_mcp")


class _ToolNameLoggingMiddleware(StructuredLoggingMiddleware):
    """Adds tool_name and call_id fields to structured logs."""

    @staticmethod
    def _get_call_id() -> str:
        try:
            from fastmcp.server.dependencies import get_http_headers
            return get_http_headers(include={"x-call-id"}).get("x-call-id", "")
        except Exception:
            return ""

    def _enrich(self, msg: dict, context: MiddlewareContext[Any]) -> dict:
        if context.method == "tools/call" and hasattr(context.message, "name"):
            msg["tool_name"] = context.message.name
        call_id = self._get_call_id()
        if call_id:
            msg["call_id"] = call_id
        return msg

    def _create_before_message(self, context: MiddlewareContext[Any]) -> dict:
        return self._enrich(super()._create_before_message(context), context)

    def _create_error_message(self, context: MiddlewareContext[Any], start_time: float, error: Exception) -> dict:
        return self._enrich(super()._create_error_message(context, start_time, error), context)

    def _create_after_message(self, context: MiddlewareContext[Any], start_time: float) -> dict:
        return self._enrich(super()._create_after_message(context, start_time), context)


_ASSETS_DIR = Path(__file__).parent / "assets"


def _build_icons() -> list[Icon]:
    """Embed icons as data URIs so clients don't need to fetch external URLs."""
    icons: list[Icon] = []
    png_path = _ASSETS_DIR / "domo_logo.png"
    if png_path.exists():
        icons.append(Icon(
            src=Image(path=str(png_path)).to_data_uri(),
            mimeType="image/png",
            sizes=["256x256"],
        ))
    svg_path = _ASSETS_DIR / "domo_logo.svg"
    if svg_path.exists():
        icons.append(Icon(
            src=Image(path=str(svg_path)).to_data_uri(),
            mimeType="image/svg+xml",
            sizes=["any"],
        ))
    return icons


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
    domo_client = DomoClient(logger)
    user_resolver = UserResolver(domo_client)

    @asynccontextmanager
    async def lifespan(server):
        yield
        await domo_client.close()

    mcp = FastMCP(
        name="domo-mcp",
        instructions="""You are connected to a Domo instance. You can query datasets,
        search for datasets, get schema information, and manage roles. Always use the
        appropriate tool based on what the user is asking for.""",
        auth=auth,
        lifespan=lifespan,
        website_url="https://www.domo.com",
        icons=_build_icons(),
    )

    # -- Per-user Domo access token cache for native PDP enforcement --
    # Defined inside create_server() for test isolation — each call gets
    # an independent cache. On Vercel, the module is loaded once per
    # warm instance, so caches persist across requests.
    _token_cache: dict[str, tuple[str, int, float]] = {}  # user_id -> (token, token_id, expires_at)
    _last_mint: dict[str, float] = {}  # user_id -> monotonic timestamp of last mint

    _TOKEN_CACHE_TTL = 14400  # 4 hours
    _TOKEN_MINT_COOLDOWN = 10  # seconds — rate limit per user
    _TOKEN_PRE_EXPIRY_BUFFER = 60  # seconds — treat as expired this far before actual expiry
    _MAX_CACHE_SIZE = 500

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

        if len(_token_cache) > _MAX_CACHE_SIZE:
            oldest_key = min(_token_cache, key=lambda k: _token_cache[k][2])
            evicted = _token_cache.pop(oldest_key)
            _last_mint.pop(oldest_key, None)
            try:
                await domo_client.delete_access_token(evicted[1])
            except Exception:
                pass

        logger.info(f"_get_user_token: created token for user {user_id}")
        return token_value

    async def _invalidate_user_token(user_id: str) -> None:
        """Evict and delete token for a user (on auth failure retry)."""
        cached = _token_cache.pop(user_id, None)
        _last_mint.pop(user_id, None)
        if cached:
            try:
                await domo_client.delete_access_token(cached[1])
            except Exception:
                pass

    async def _resolve_user() -> tuple[str | None, str | None, bool]:
        """Resolve JWT email to Domo user ID and admin status.

        Returns:
            (user_id, email, is_admin) tuple. user_id is None if not found.
            is_admin is True for Domo Admin/Privileged roles.
        """
        email = get_user_email()
        if not email:
            return None, None, False
        user_id = await user_resolver.resolve(email)
        is_admin = user_resolver.is_admin(email)
        if is_admin:
            logger.info(f"_resolve_user: {email} has admin role")
        return user_id, email, is_admin

    async def _call_with_pdp_retry(
        user_id: str,
        override_token: str,
        call: Callable[..., Awaitable],
        error_context: str,
    ) -> Any:
        """Execute a Domo data call with per-user token and one retry on 401."""
        try:
            return await call(override_token=override_token)
        except DomoRequestError as e:
            if e.status_code == 401:
                await _invalidate_user_token(user_id)
                try:
                    fresh_token = await _get_user_token(user_id)
                    return await call(override_token=fresh_token)
                except (DomoRequestError, RuntimeError):
                    return _access_denied("Authentication failed after token refresh")
            elif e.status_code == 403:
                return _access_denied(f"You don't have permission to {error_context}")
            else:
                return _access_denied(f"Domo API error ({e.status_code}) {error_context}")

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

        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")

        # Native PDP: JWT → per-user token (all users, including admins for audit); bearer → service account
        override_token = None
        if user_id and is_jwt_auth():
            try:
                override_token = await _get_user_token(user_id)
            except RuntimeError as e:
                return _access_denied(str(e))

        logger.info(f"Getting schema for dataset: {validated.dataset_id}")
        if override_token:
            result = await _call_with_pdp_retry(
                user_id, override_token,
                lambda override_token: domo_client.get_dataset_schema(
                    dataset_id=validated.dataset_id, override_token=override_token,
                ),
                "view this dataset's schema",
            )
        else:
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

        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")

        # Native PDP: JWT → per-user token (all users, including admins for audit); bearer → service account
        override_token = None
        if user_id and is_jwt_auth():
            try:
                override_token = await _get_user_token(user_id)
            except RuntimeError as e:
                return _access_denied(str(e))

        logger.info(f"Getting metadata for dataset: {validated.dataset_id}")
        if override_token:
            result = await _call_with_pdp_retry(
                user_id, override_token,
                lambda override_token: domo_client.get_dataset_metadata(
                    dataset_id=validated.dataset_id, override_token=override_token,
                ),
                "access this dataset's metadata",
            )
        else:
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

        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")

        # Native PDP: JWT → per-user token (all users, including admins for audit); bearer → service account
        override_token = None
        if user_id and is_jwt_auth():
            try:
                override_token = await _get_user_token(user_id)
            except RuntimeError as e:
                return _access_denied(str(e))

        logger.info(f"Querying dataset {validated_id.dataset_id} with SQL: {validated_sql.sql}")
        if override_token:
            result = await _call_with_pdp_retry(
                user_id, override_token,
                lambda override_token: domo_client.query_dataset(
                    dataset_id=validated_id.dataset_id, sql=validated_sql.sql,
                    override_token=override_token,
                ),
                "query this dataset",
            )
        else:
            result = await domo_client.query_dataset(
                dataset_id=validated_id.dataset_id, sql=validated_sql.sql
            )

        logger.info("Query executed successfully.")
        return json.dumps(result, indent=2) if isinstance(result, dict) else str(result)

    @mcp.tool()
    async def search_datasets(query: str) -> str:
        """Search for datasets in a Domo instance by name.

        Note: Domo's search API does not PDP-filter results. JWT users see all
        datasets in search but get 403 or filtered rows when actually querying.

        Args:
            query: The search query to find datasets by name.

        Returns:
            JSON string containing matching datasets with their IDs and names.
        """
        try:
            validated = SearchQuery(query=query)
        except ValidationError as e:
            return _validation_error_response(e)

        user_id, email, is_admin = await _resolve_user()
        if email and not user_id:
            return _access_denied(f"No Domo account linked to '{email}'")

        # Native PDP: JWT → per-user token (all users, including admins for audit); bearer → service account
        override_token = None
        if user_id and is_jwt_auth():
            try:
                override_token = await _get_user_token(user_id)
            except RuntimeError as e:
                return _access_denied(str(e))

        try:
            logger.info(f"Searching datasets with query: {validated.query}")
            if override_token:
                result = await _call_with_pdp_retry(
                    user_id, override_token,
                    lambda override_token: domo_client.search_datasets(
                        query=validated.query, override_token=override_token,
                    ),
                    "search datasets",
                )
            else:
                result = await domo_client.search_datasets(query=validated.query)

            logger.info(f"Datasets searched successfully. result type={type(result).__name__}")
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
    async def create_role(name: str, from_role_id: int, description: str | None = None) -> str:
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
    async def run_python(
        code: str,
        data: Annotated[
            list | dict | str | None,
            Field(
                description=(
                    "Input data, available in `code` as the `data` variable. "
                    "Preferred: pass a native list or dict (no JSON round-trip). "
                    "Also accepted: a JSON string (parsed before execution) or null."
                ),
            ),
        ] = None,
    ) -> str:
        """Execute Python code to compute analytics on data returned by query_dataset.

        Use this after fetching data with query_dataset when you need calculations
        that are more reliable in code than in your head: YoY change columns,
        percentage deltas, totals, averages, pivots, rankings, etc.

        Args:
            code: Python source to execute. Either `print()` values, or end with
                  a bare expression — its repr() is auto-printed REPL-style.
                  The following names are pre-bound and ready to use directly
                  (re-importing them is allowed but redundant):
                    - pd (pandas), np (numpy)
                    - json, math, statistics, collections, decimal, datetime, re
                  The `data` variable holds the parsed input. Imports of any
                  other module are blocked; no file, network, or OS access.
            data: Input data, available in code as `data`. Accepts a native
                  list/dict, or a JSON string (which will be parsed). Pass
                  nothing if `code` doesn't need input data.

        Returns:
            A JSON string with the same key set on success and error:
              ok, stdout, stderr, truncated, original_length, execution_ms,
              data_summary, plus error_type / error_message / line (null on
              success). Branch on `ok` before reading the rest.

        Note: `query_dataset` returns column-oriented data
        (`{columns, rows, ...}`). Convert to a list of dicts before treating
        `data` as a list of rows — see the "Reshape from query_dataset"
        section of the `python://env` resource for the snippet.

        Example 1 (pandas, with rows already shaped as list of dicts):
            code = '''
            df = pd.DataFrame(data)
            df["change"] = df["FY2025"] - df["FY2024"]
            df["change_pct"] = (df["change"] / df["FY2024"] * 100).round(1)
            print(df.to_string(index=False))
            '''
            data = [{"FiscalPrd": 10, "FY2024": 2733551, "FY2025": 9895014}, ...]

        Example 2 (plain Python, no pandas):
            code = '''
            counts = collections.Counter(row["category"] for row in data)
            for category, n in counts.most_common(5):
                print(f"{category}: {n}")
            '''
            data = [{"category": "A"}, {"category": "B"}, {"category": "A"}, ...]
        """
        # Pydantic validates `data` against `list | dict | str | None` before
        # we get here, so we only need to handle the JSON-string parse step.
        parsed_data: object
        if data is None or data == "":
            parsed_data = None
        elif isinstance(data, str):
            try:
                parsed_data = json.loads(data)
            except json.JSONDecodeError as e:
                return json.dumps(_error_result(
                    "JSONDecodeError",
                    f"Invalid JSON in data argument: {e}",
                ))
        else:
            # list or dict — already validated by Pydantic
            parsed_data = data

        logger.info(f"run_python: executing {len(code)} chars of code")
        result = _execute_code(code, parsed_data)
        logger.info(f"run_python: output length={result.get('original_length', 0)}")
        try:
            return json.dumps(result)
        except (TypeError, ValueError) as e:
            # Result contained a value json.dumps can't serialize (e.g.
            # surrogate-escaped bytes leaked through stdout/stderr). Return
            # a structured error rather than letting the exception reach
            # the MCP layer as an unhandled tool failure.
            return json.dumps(_error_result(
                "SerializationError",
                f"result could not be serialized: {e}",
                execution_ms=result.get("execution_ms", 0),
            ))

    # Token management (list/create/delete access tokens) is NOT exposed as MCP tools.
    # DomoClient methods are used internally by _get_user_token / _invalidate_user_token
    # for per-user PDP token lifecycle. No external caller should mint or revoke tokens directly.

    _python_env_resource.register(mcp)

    mcp.add_middleware(_ToolNameLoggingMiddleware(
        include_payloads=True,
        logger=_structured_logger,
    ))

    return mcp
