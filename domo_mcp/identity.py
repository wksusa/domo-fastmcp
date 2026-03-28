"""Extract user identity from access token (JWT or bearer with email mapping)."""

from fastmcp.server.dependencies import get_access_token

from .logger import Logger

logger = Logger()


def is_jwt_auth() -> bool:
    """Return True if the current request was authenticated via JWT (not a static bearer token).

    Detection: bearer tokens always get client_id starting with "bearer:" (set by
    _parse_domo_bearer_tokens and _parse_named_api_keys in auth_config.py).
    JWT tokens have a different client_id structure.
    """
    token = get_access_token()
    if not token or not token.claims:
        return False
    client_id = token.claims.get("client_id", "")
    return not client_id.startswith("bearer:")


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
        logger.debug("get_user_email: no access token present")
        return None
    claims = token.claims or {}
    claim_keys = list(claims.keys())
    logger.info(f"get_user_email: JWT claim keys: {claim_keys}")
    upstream = claims.get("upstream_claims", {})
    if not isinstance(upstream, dict):
        logger.warning(f"get_user_email: upstream_claims is {type(upstream).__name__}, not dict: {upstream!r}")
        upstream = {}
    if upstream:
        logger.info(f"get_user_email: upstream_claims keys: {list(upstream.keys())}")
    email = upstream.get("email") or claims.get("email")
    if email is not None and not isinstance(email, str):
        logger.warning(f"get_user_email: email claim is not a string: {type(email)}")
        return None
    logger.info(f"get_user_email: resolved email={email}")
    return email
