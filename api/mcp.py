"""Vercel serverless function endpoint for Domo MCP server."""

import os

from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.auth import AuthMiddleware
from domo_mcp.auth_config import create_auth
from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server


logger = Logger()

# ============================================================================
# Auth mode selection
# ============================================================================

AUTH_MODE = os.getenv("AUTH_MODE", "bearer")

# Create server with JWT auth if configured, otherwise no framework-level auth
auth = create_auth(AUTH_MODE) if AUTH_MODE == "jwt" else None
mcp = create_server(auth=auth)


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
    """Load and validate authentication tokens from environment."""
    tokens_str = os.getenv("MCP_AUTH_TOKENS", "")
    if not tokens_str:
        return []
    tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]
    return tokens


# Create the ASGI app
_event_store = EventStore()
app = mcp.http_app(
    path="/api/mcp",
    middleware=middleware,
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
    retry_interval=2000,
)

# Wrap with request filter middleware (strips extra fields from tool calls)
app = RequestFilterMiddleware(app)

# Wrap with Bearer token auth middleware if in bearer mode
if AUTH_MODE == "bearer":
    valid_tokens = get_valid_tokens()
    if valid_tokens:
        app = AuthMiddleware(app, valid_tokens)
        logger.info(f"Bearer auth enabled with {len(valid_tokens)} token(s)")
    else:
        logger.warning("AUTH_MODE=bearer but no MCP_AUTH_TOKENS set — auth disabled")
elif AUTH_MODE == "jwt":
    logger.info("JWT auth enabled via FastMCP JWTVerifier")
else:
    logger.warning("AUTH_MODE=none — authentication disabled")
