"""Bearer token verifier with constant-time comparison.

Replaces FastMCP's StaticTokenVerifier (which uses dict.get() and is
documented as "never use in production") with secrets.compare_digest()
to prevent timing attacks.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier


class ConstantTimeTokenVerifier(TokenVerifier):
    """Bearer token verifier with constant-time comparison.

    Unlike FastMCP's StaticTokenVerifier (which uses dict.get()),
    this uses secrets.compare_digest() to prevent timing attacks.
    """

    def __init__(self, tokens: dict[str, dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tokens = list(tokens.items())

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using constant-time comparison."""
        matched_data = None
        for valid_token, data in self._tokens:
            if secrets.compare_digest(token, valid_token):
                matched_data = data
                break

        if matched_data is None:
            return None

        return AccessToken(
            token=token,
            client_id=matched_data["client_id"],
            scopes=matched_data.get("scopes", []),
            claims=matched_data,
        )
