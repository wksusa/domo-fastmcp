"""Extract user identity from JWT access token."""

from fastmcp.server.dependencies import get_access_token


def get_user_email() -> str | None:
    """Get the authenticated user's email from the JWT access token.

    Checks upstream_claims first (for gateway-forwarded tokens),
    then falls back to top-level claims.

    Returns:
        Email address string, or None if not authenticated.
    """
    token = get_access_token()
    if not token:
        return None
    claims = token.claims or {}
    upstream = claims.get("upstream_claims", {})
    return upstream.get("email") or claims.get("email")
