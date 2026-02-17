"""Vercel serverless endpoint — JWT authentication."""

from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.auth_config import create_auth
from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server

logger = Logger()

try:
    auth = create_auth("jwt")
    logger.info("JWT auth enabled on /mcp-jwt endpoint")
except ValueError as e:
    logger.warning(f"JWT auth not configured ({e}) — /mcp-jwt endpoint disabled")
    auth = None

mcp = create_server(auth=auth)

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
    path="/mcp-jwt",
    middleware=middleware,
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
    retry_interval=2000,
)

app = RequestFilterMiddleware(app)
