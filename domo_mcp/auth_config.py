"""Auth configuration factory — selects auth strategy based on AUTH_MODE env var."""

import os

from fastmcp.server.auth import JWTVerifier
from fastmcp.server.auth.jwt_issuer import derive_jwt_key


def create_auth(mode: str | None):
    """Create an auth verifier based on the specified mode.

    Args:
        mode: One of "jwt", "bearer", or None/empty for no auth.

    Returns:
        JWTVerifier for jwt mode, None for bearer/none modes.
        Bearer mode uses external ASGI middleware instead.
    """
    if mode == "jwt":
        jwt_signing_key = os.environ.get("JWT_SIGNING_KEY")
        if not jwt_signing_key:
            raise ValueError("JWT_SIGNING_KEY environment variable is required when AUTH_MODE=jwt")

        gateway_base_url = os.environ.get("GATEWAY_BASE_URL")
        if not gateway_base_url:
            raise ValueError("GATEWAY_BASE_URL environment variable is required when AUTH_MODE=jwt")

        derived_key = derive_jwt_key(
            low_entropy_material=jwt_signing_key,
            salt="fastmcp-jwt-signing-key",
        )

        return JWTVerifier(
            public_key=derived_key.decode(),
            algorithm="HS256",
            issuer=gateway_base_url,
        )

    # bearer mode: auth handled by ASGI AuthMiddleware wrapper
    # none mode: no auth at all
    return None
