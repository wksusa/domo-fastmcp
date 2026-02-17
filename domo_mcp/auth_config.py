"""Auth configuration factory — selects auth strategy based on AUTH_MODE env var.

Supports three modes:
  - jwt: FastMCP JWTVerifier with auto-detected algorithm (RS256/ES256/HS256)
  - bearer: ConstantTimeTokenVerifier with optional email mapping for PDP
  - none: No auth
"""

from __future__ import annotations

import os
import re

from fastmcp.server.auth import JWTVerifier
from fastmcp.server.auth.jwt_issuer import derive_jwt_key

from .logger import Logger
from .token_verifier import ConstantTimeTokenVerifier

logger = Logger()

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def create_auth(
    mode: str | None, tokens_str: str = ""
) -> JWTVerifier | ConstantTimeTokenVerifier | None:
    """Create an auth verifier based on the specified mode.

    Args:
        mode: One of "jwt", "bearer", or None/empty for no auth.
        tokens_str: Comma-separated tokens for bearer mode.
            Format: "token1:email@example.com,token2,svc-token"
            Tokens with :email get PDP enforcement.
            Tokens without :email are service accounts (full access).

    Returns:
        JWTVerifier for jwt mode, ConstantTimeTokenVerifier for bearer mode,
        None for none mode or bearer with no tokens.
    """
    if mode == "jwt":
        return _create_jwt_verifier()
    if mode == "bearer" and tokens_str:
        return _create_bearer_verifier(tokens_str)
    return None


def _detect_algorithm(public_key: str | None, jwks_uri: str | None) -> str:
    """Auto-detect JWT algorithm from key format."""
    if jwks_uri:
        return "RS256"
    if public_key and public_key.startswith("-----BEGIN"):
        return "ES256" if "EC" in public_key else "RS256"
    return "HS256"  # Raw string = HMAC secret


def _create_jwt_verifier() -> JWTVerifier:
    public_key = os.environ.get("JWT_PUBLIC_KEY")
    jwks_uri = os.environ.get("JWT_JWKS_URI")
    issuer = os.environ.get("JWT_ISSUER")

    if public_key and jwks_uri:
        raise ValueError("Set JWT_PUBLIC_KEY or JWT_JWKS_URI, not both")
    if not public_key and not jwks_uri:
        raise ValueError(
            "JWT_PUBLIC_KEY or JWT_JWKS_URI required when AUTH_MODE=jwt"
        )

    algorithm = _detect_algorithm(public_key, jwks_uri)

    # When using HS256 (shared secret), the gateway signs JWTs using
    # derive_jwt_key() (PBKDF2). We must derive the same key here so
    # verification matches.
    if algorithm == "HS256" and public_key:
        public_key = derive_jwt_key(
            low_entropy_material=public_key,
            salt="fastmcp-jwt-signing-key",
        ).decode()

    return JWTVerifier(
        public_key=public_key,
        jwks_uri=jwks_uri,
        algorithm=algorithm,
        issuer=issuer,
        ssrf_safe=bool(jwks_uri),
    )


def _create_bearer_verifier(tokens_str: str) -> ConstantTimeTokenVerifier:
    tokens_dict: dict[str, dict] = {}
    has_service_accounts = False

    for entry in tokens_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            token, email = entry.split(":", 1)
            token = token.strip()
            email = email.strip()
            if not token:
                raise ValueError("Empty token in MCP_AUTH_TOKENS")
            if not email:
                raise ValueError("Empty email after ':' in MCP_AUTH_TOKENS")
            if not EMAIL_PATTERN.match(email):
                raise ValueError(
                    f"Invalid email format in MCP_AUTH_TOKENS: '{email}'"
                )
            tokens_dict[token] = {
                "client_id": f"bearer:{email}",
                "scopes": [],
                "email": email,
            }
        else:
            has_service_accounts = True
            tokens_dict[entry] = {
                "client_id": "bearer:service",
                "scopes": [],
            }

    if has_service_accounts:
        logger.warning(
            "Service account tokens detected (no email mapping). "
            "These tokens bypass PDP and have full dataset access."
        )

    return ConstantTimeTokenVerifier(tokens=tokens_dict)
