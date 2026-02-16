"""Shared logger for MCP server compatibility.

MCP servers communicate via stdio, so logging must go to stderr
to avoid interfering with the protocol.
"""

import sys


class Logger:
    """Simple logger that writes to stderr for MCP compatibility."""

    def info(self, message: str) -> None:
        print(f"[INFO] {message}", file=sys.stderr)

    def warning(self, message: str) -> None:
        print(f"[WARNING] {message}", file=sys.stderr)

    def debug(self, message: str) -> None:
        print(f"[DEBUG] {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}", file=sys.stderr)
