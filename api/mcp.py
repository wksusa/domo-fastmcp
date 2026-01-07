"""Vercel serverless function endpoint for Domo MCP server."""

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

# Import the FastMCP server instance
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from domo_mcp.server import mcp

# Configure CORS middleware for browser/remote clients
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version",
            "mcp-session-id",
            "Authorization",
            "Content-Type",
        ],
    )
]

# Create the ASGI app for Vercel
# stateless_http=True enables serverless deployment (no session affinity required)
app = mcp.http_app(path="/mcp", middleware=middleware, stateless_http=True)

# Vercel expects an 'app' or 'handler' export
handler = app
