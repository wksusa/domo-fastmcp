"""Shared logger for MCP server compatibility.

MCP servers communicate via stdio, so logging must go to stderr
to avoid interfering with the protocol. For HTTP/Vercel mode,
we use Python's logging module which Vercel captures.
"""

import logging
import sys

# Python logging for Vercel (captured in runtime logs)
_logger = logging.getLogger("domo_mcp")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    _logger.addHandler(handler)


class Logger:
    """Logger that writes to both stderr (MCP stdio compat) and Python logging (Vercel)."""

    def info(self, message: str) -> None:
        print(f"[INFO] {message}", file=sys.stderr)
        _logger.info(message)

    def warning(self, message: str) -> None:
        print(f"[WARNING] {message}", file=sys.stderr)
        _logger.warning(message)

    def debug(self, message: str) -> None:
        print(f"[DEBUG] {message}", file=sys.stderr)
        _logger.debug(message)

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}", file=sys.stderr)
        _logger.error(message)
