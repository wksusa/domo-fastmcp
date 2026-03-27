"""Auth configuration factory using native FastMCP 3.1 auth.

Replaces the vendored mcp_auth dependency with:
- MultiAuth for composite JWT + bearer
- JWTVerifier for gateway-issued tokens
- StaticTokenVerifier for named bearer tokens
"""

from __future__ import annotations

import logging
import os
import re

from fastmcp.server.auth import MultiAuth
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.jwt import JWTVerifier, StaticTokenVerifier

logger = logging.getLogger("domo_mcp.auth")

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def detect_jwt_algorithm(public_key: str | None, jwks_uri: str | None) -> str:
    """Auto-detect JWT algorithm from key format."""
    if jwks_uri:
        return "RS256"
    if public_key and public_key.startswith("-----BEGIN"):
        return "ES256" if "EC" in public_key else "RS256"
    return "HS256"


# Backward compat alias
_detect_algorithm = detect_jwt_algorithm


def _parse_named_api_keys(raw: str) -> dict[str, dict]:
    """Parse MCP_API_KEYS format: 'name:token,name2:token2,plaintoken'."""
    tokens: dict[str, dict] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, _, secret = entry.partition(":")
            tokens[secret.strip()] = {"client_id": f"bearer:{name.strip()}", "scopes": []}
        else:
            tokens[entry] = {"client_id": "bearer:unnamed", "scopes": []}
    return tokens


def _parse_domo_bearer_tokens(tokens_str: str) -> dict[str, dict]:
    """Parse Domo-style bearer format: 'token:email,token2:email2,plaintoken'."""
    tokens: dict[str, dict] = {}
    for entry in tokens_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            token, email = entry.split(":", 1)
            token, email = token.strip(), email.strip()
            if not token:
                raise ValueError("Empty token in MCP_AUTH_TOKENS")
            if not email:
                raise ValueError("Empty email after ':' in MCP_AUTH_TOKENS")
            if not EMAIL_PATTERN.match(email):
                raise ValueError(f"Invalid email format in MCP_AUTH_TOKENS: '{email}'")
            tokens[token] = {"client_id": f"bearer:{email}", "scopes": [], "email": email}
        else:
            tokens[entry] = {"client_id": "bearer:service", "scopes": []}
    return tokens


def _build_jwt_verifier() -> JWTVerifier:
    """Build JWTVerifier from env vars."""
    public_key = (os.environ.get("JWT_PUBLIC_KEY") or "").strip()
    jwks_uri = (os.environ.get("JWT_JWKS_URI") or "").strip() or None
    if not public_key and not jwks_uri:
        raise ValueError("JWT_PUBLIC_KEY or JWT_JWKS_URI required when AUTH_MODE=jwt")
    if public_key and jwks_uri:
        raise ValueError("Set JWT_PUBLIC_KEY or JWT_JWKS_URI, not both")

    algorithm = detect_jwt_algorithm(public_key or None, jwks_uri)

    if algorithm == "HS256" and public_key:
        public_key = derive_jwt_key(
            low_entropy_material=public_key, salt="fastmcp-jwt-signing-key"
        ).decode()

    issuer_raw = (os.environ.get("JWT_ISSUER") or "").strip()
    issuer = None
    if issuer_raw:
        parts = [p.strip() for p in issuer_raw.split(",") if p.strip()]
        variants = []
        for p in parts:
            s = p.rstrip("/")
            variants.extend(dict.fromkeys([p, s, s + "/"]))
        issuer = list(dict.fromkeys(variants))
        if len(issuer) == 1:
            issuer = issuer[0]

    return JWTVerifier(
        public_key=public_key or None,
        jwks_uri=jwks_uri,
        issuer=issuer,
        algorithm=algorithm,
        ssrf_safe=bool(jwks_uri),
    )


def create_auth(
    mode: str | None,
    tokens_str: str = "",
    *,
    mcp_api_keys: str = "",
) -> JWTVerifier | StaticTokenVerifier | MultiAuth | None:
    """Create an auth verifier based on the specified mode.

    Args:
        mode: One of "jwt", "bearer", or None/empty for no auth.
        tokens_str: Domo-style bearer tokens (token:email or plain).
        mcp_api_keys: Named API keys (name:token pairs).
    """
    normalized = (mode or "").strip().lower() or None

    if normalized == "jwt":
        jwt_verifier = _build_jwt_verifier()
        extra_verifiers = []
        if tokens_str.strip():
            extra_verifiers.append(
                StaticTokenVerifier(tokens=_parse_domo_bearer_tokens(tokens_str))
            )
        if mcp_api_keys.strip():
            extra_verifiers.append(
                StaticTokenVerifier(tokens=_parse_named_api_keys(mcp_api_keys))
            )
        if not extra_verifiers:
            return jwt_verifier
        return MultiAuth(verifiers=[jwt_verifier, *extra_verifiers])

    if normalized == "bearer":
        if mcp_api_keys.strip():
            return StaticTokenVerifier(tokens=_parse_named_api_keys(mcp_api_keys))
        if tokens_str.strip():
            return StaticTokenVerifier(tokens=_parse_domo_bearer_tokens(tokens_str))
        return None

    return None
