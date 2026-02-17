"""Top-level entrypoint for fastmcp run / Prefect Horizon / any MCP host.

Usage:
    fastmcp run main.py:mcp
    fastmcp inspect main.py:mcp
"""

from domo_mcp.server_factory import create_server

mcp = create_server(auth=None)

if __name__ == "__main__":
    mcp.run()
