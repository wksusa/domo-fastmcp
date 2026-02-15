"""Domo MCP Server — stdio mode (for local use with VS Code, Claude Desktop)."""

from .server_factory import create_server

mcp = create_server(auth=None)
