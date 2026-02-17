"""Vercel serverless endpoint — Bearer token authentication."""

import os

from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.auth_config import create_auth
from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server

logger = Logger()

tokens_str = os.getenv("MCP_AUTH_TOKENS", "")
auth = create_auth("bearer", tokens_str)
mcp = create_server(auth=auth)

if auth:
    logger.info("Bearer auth enabled via ConstantTimeTokenVerifier")
else:
    logger.warning("No MCP_AUTH_TOKENS set — bearer auth disabled (no auth)")

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["mcp-protocol-version", "mcp-session-id", "Authorization", "Content-Type"],
    )
]

_event_store = EventStore()
app = mcp.http_app(
    path="/mcp",
    middleware=middleware,
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
    retry_interval=2000,
)

app = RequestFilterMiddleware(app)
