"""Authentication middleware for Domo MCP server."""

import secrets
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse


class AuthMiddleware:
    """ASGI middleware for Bearer token authentication.

    Validates Authorization header with Bearer token format against a list
    of valid tokens. Uses constant-time comparison to prevent timing attacks.
    """

    def __init__(self, app: Callable, valid_tokens: list[str]):
        """Initialize authentication middleware.

        Args:
            app: ASGI application to wrap
            valid_tokens: List of valid Bearer tokens for authentication
        """
        self.app = app
        # Use set for O(1) lookup, but still iterate for constant-time comparison
        self.valid_tokens = valid_tokens

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI middleware entry point.

        Args:
            scope: ASGI scope dictionary
            receive: ASGI receive channel
            send: ASGI send channel
        """
        # Only process HTTP requests, pass through other connection types
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Build request object to access headers
        request = Request(scope, receive)

        # Allow CORS preflight requests without authentication
        if request.method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # Extract Authorization header
        auth_header = request.headers.get("Authorization", "")

        # Check for Bearer token format
        if not auth_header.startswith("Bearer "):
            await self._send_error(
                scope, receive, send,
                status=401,
                message="Missing or invalid Authorization header"
            )
            return

        # Extract token (remove "Bearer " prefix)
        provided_token = auth_header[7:]

        # Validate token using constant-time comparison to prevent timing attacks
        is_valid = any(
            secrets.compare_digest(provided_token, valid_token)
            for valid_token in self.valid_tokens
        )

        if not is_valid:
            await self._send_error(
                scope, receive, send,
                status=403,
                message="Invalid authentication token"
            )
            return

        # Token is valid, pass request through to the app
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_error(
        scope: dict,
        receive: Callable,
        send: Callable,
        status: int,
        message: str
    ) -> None:
        """Send JSON error response.

        Args:
            scope: ASGI scope dictionary
            receive: ASGI receive channel
            send: ASGI send channel
            status: HTTP status code
            message: Error message to return
        """
        response = JSONResponse(
            {"error": message},
            status_code=status
        )
        await response(scope, receive, send)
