"""Middleware to filter extra fields from MCP tool call requests.

Some MCP clients (like n8n) send extra metadata fields with tool calls that
cause Pydantic validation errors. This middleware strips those extra fields
before they reach FastMCP.
"""

import json
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Define expected parameters for each tool
# Only these fields will be passed to the tool functions
TOOL_PARAMETERS: dict[str, set[str]] = {
    "get_dataset_schema": {"dataset_id"},
    "get_dataset_metadata": {"dataset_id"},
    "query_dataset": {"dataset_id", "sql"},
    "search_datasets": {"query"},
    "list_roles": set(),  # No parameters
    "create_role": {"name", "from_role_id", "description"},
    "list_role_authorities": {"role_id"},
}


class RequestFilterMiddleware:
    """ASGI middleware that filters extra fields from MCP tool call requests."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reject GET: this deployment is POST-only (Streamable HTTP, no long-lived SSE).
        # GET would open an SSE stream and hit serverless timeouts; clients must use POST.
        if scope["method"] == "GET":
            body = json.dumps({
                "error": "Method Not Allowed",
                "message": "This MCP server uses POST-only Streamable HTTP for serverless. Use POST for all MCP requests.",
            }).encode()
            response = Response(
                content=body,
                status_code=405,
                media_type="application/json",
                headers={"Allow": "POST, OPTIONS"},
            )
            await response(scope, receive, send)
            return

        # Only process POST requests (OPTIONS, DELETE pass through to app)
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        # Buffer the request body so we can modify it
        body_parts: list[bytes] = []

        async def receive_wrapper() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    # All body received, process it
                    full_body = b"".join(body_parts)
                    modified_body = self._filter_request_body(full_body)
                    return {
                        "type": "http.request",
                        "body": modified_body,
                        "more_body": False,
                    }
            return message

        await self.app(scope, receive_wrapper, send)

    def _filter_request_body(self, body: bytes) -> bytes:
        """Filter extra fields from tool call requests."""
        if not body:
            return body

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body

        # Check if this is a tools/call request (MCP protocol)
        if isinstance(data, dict) and data.get("method") == "tools/call":
            params = data.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name in TOOL_PARAMETERS and isinstance(arguments, dict):
                # Filter to only expected parameters
                expected = TOOL_PARAMETERS[tool_name]
                filtered_args = {k: v for k, v in arguments.items() if k in expected}
                params["arguments"] = filtered_args
                data["params"] = params
                return json.dumps(data).encode()

        return body
