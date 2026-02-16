"""Vercel serverless function endpoint for Domo MCP server."""

import os

from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.auth_config import create_auth
from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server


logger = Logger()

# ============================================================================
# Auth mode selection
# ============================================================================

AUTH_MODE = os.getenv("AUTH_MODE", "bearer")
tokens_str = os.getenv("MCP_AUTH_TOKENS", "")

auth = create_auth(AUTH_MODE, tokens_str)
mcp = create_server(auth=auth)

# Log auth mode
if AUTH_MODE == "jwt":
    logger.info("JWT auth enabled via FastMCP JWTVerifier")
elif AUTH_MODE == "bearer":
    if auth:
        logger.info("Bearer auth enabled via ConstantTimeTokenVerifier")
    else:
        logger.warning("AUTH_MODE=bearer but no MCP_AUTH_TOKENS set — auth disabled")
else:
    logger.warning("AUTH_MODE=none — authentication disabled")


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
