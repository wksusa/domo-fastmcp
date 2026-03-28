"""Re-export native FastMCP token verifiers for backward compat.

Tests and other modules import from this path. With FastMCP 3.1,
the custom ConstantTimeTokenVerifier is replaced by StaticTokenVerifier.
"""

from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# Backward compat alias — tests import ConstantTimeTokenVerifier
ConstantTimeTokenVerifier = StaticTokenVerifier

__all__ = ["ConstantTimeTokenVerifier", "StaticTokenVerifier"]
