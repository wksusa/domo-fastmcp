"""Extract user identity from access token (JWT or bearer with email mapping)."""

from fastmcp.server.dependencies import get_access_token


def get_user_email() -> str | None:
    """Get the authenticated user's email from the access token.

    Works with both JWTVerifier (email in JWT claims) and
    ConstantTimeTokenVerifier (email mapped from bearer token).

    Checks upstream_claims first (for gateway-forwarded tokens),
    then falls back to top-level claims.

    Returns:
        Email address string, or None if not authenticated or no email claim.
    """
    token = get_access_token()
    if not token:
        return None
    claims = token.claims or {}
    upstream = claims.get("upstream_claims", {})
    email = upstream.get("email") or claims.get("email")
    if email is not None and not isinstance(email, str):
        return None
    return email
