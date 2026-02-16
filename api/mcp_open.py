"""Vercel serverless endpoint — no authentication (migration aid)."""

from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server

logger = Logger()
logger.warning("No-auth MCP endpoint active — no authentication or PDP enforcement")

mcp = create_server(auth=None)

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["mcp-protocol-version", "mcp-session-id", "Content-Type"],
    )
]

_event_store = EventStore()
app = mcp.http_app(
    path="/api/mcp_open",
    middleware=middleware,
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
    retry_interval=2000,
)

app = RequestFilterMiddleware(app)
