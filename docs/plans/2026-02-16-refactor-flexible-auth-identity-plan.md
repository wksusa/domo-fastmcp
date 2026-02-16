---
title: "refactor: Flexible auth & identity for open source users"
type: refactor
status: completed
date: 2026-02-16
deepened: 2026-02-16
---

# Flexible Auth & Identity for Open Source Users

Redesign the auth layer to support multiple identity sources (BYO JWT, bearer+email, header passthrough) so PDP works for any user — not just those behind our specific gateway. Replace custom `AuthMiddleware` with a `ConstantTimeTokenVerifier` that extends FastMCP's `TokenVerifier`, and use FastMCP's `JWTVerifier` for JWT mode.

**Brainstorm:** [docs/brainstorms/2026-02-16-service-account-pdp-bypass-brainstorm.md](../brainstorms/2026-02-16-service-account-pdp-bypass-brainstorm.md)
**Security Audit:** [docs/security-audit-auth-redesign-2026-02-16.md](../security-audit-auth-redesign-2026-02-16.md)

## Enhancement Summary

**Deepened on:** 2026-02-16
**Research agents used:** kieran-python-reviewer, security-sentinel, performance-oracle, architecture-strategist, code-simplicity-reviewer, agent-native-reviewer, best-practices-researcher

### Key Changes from Research

1. **Use `ConstantTimeTokenVerifier` instead of `StaticTokenVerifier`** — Security audit found `StaticTokenVerifier` uses `dict.get()` (not constant-time), documented as "never use in production". Create a custom `ConstantTimeTokenVerifier` extending `TokenVerifier` with `secrets.compare_digest()`.
2. **Simplify to 3 JWT env vars** — Drop `JWT_ALGORITHM` (auto-detect from key format) and `JWT_AUDIENCE` (defer to v0.3.0). This reduces configuration burden.
3. **Enable `ssrf_safe=True`** — JWKS URI fetching must block private IPs (AWS metadata, localhost, etc.).
4. **Add input validation** — Validate email format, reject empty tokens/emails, enforce length limits on token parsing.
5. **Add startup warning for service account tokens** — Log warning when tokens without email mapping are detected (PDP bypass).

## Problem Statement

The current auth layer is too rigid for an open source project:

- JWT mode hard-codes HKDF key derivation + HS256 + single issuer (only works with our gateway)
- Bearer mode has no identity concept — PDP can never work in bearer mode
- Custom `AuthMiddleware` in `auth.py` duplicates what FastMCP's `StaticTokenVerifier` provides (with identity)
- Users wanting PDP with Auth0/Okta/Azure have no path — must use our specific gateway

FastMCP v3 ships `JWTVerifier` (RS256, ES256, JWKS URI, multiple issuers, audience) and `StaticTokenVerifier` (bearer tokens with claims). We use almost none of it.

## Proposed Solution

Replace custom auth code with FastMCP's built-in verifiers. All three modes flow through FastMCP's `AccessToken` → `get_access_token()` → `identity.py` pipeline. PDP gate in `server_factory.py` is unchanged.

| Auth Mode | FastMCP Class | Identity Source | PDP |
|-----------|--------------|----------------|-----|
| `jwt` | `JWTVerifier` | Email from JWT claims | Enforced |
| `bearer` | `StaticTokenVerifier` | Email from token map (optional) | If email mapped |
| `none` | No verifier | None | Skipped |

## Technical Approach

### Phase 1: Rewrite `auth_config.py`

**File:** `domo_mcp/auth_config.py`

Replace the hard-coded HKDF + HS256 factory with a general-purpose factory that exposes FastMCP's full capabilities.

**New env var model for JWT mode (simplified from original 5 to 3):**

| Env Var | Purpose | Default | Required |
|---------|---------|---------|----------|
| `JWT_PUBLIC_KEY` | PEM public key or HMAC shared secret | — | One of key/JWKS |
| `JWT_JWKS_URI` | JWKS endpoint URL (Auth0, Okta, Azure) | — | One of key/JWKS |
| `JWT_ISSUER` | Expected issuer | — | No |

> **Simplification rationale:** `JWT_ALGORITHM` dropped — auto-detect from key format (PEM → RS256, raw string → HS256, JWKS → RS256). `JWT_AUDIENCE` deferred to v0.3.0 — most deployments don't need it and it adds configuration burden.

Validation rules (fail at startup with `ValueError`):
- `JWT_PUBLIC_KEY` and `JWT_JWKS_URI` are mutually exclusive (error if both set)
- At least one must be provided when `AUTH_MODE=jwt`
- `JWT_ALGORITHM=none` explicitly rejected

```python
# domo_mcp/auth_config.py - pseudocode
from __future__ import annotations
import os
import re
from fastmcp.server.auth import JWTVerifier
from domo_mcp.token_verifier import ConstantTimeTokenVerifier
from domo_mcp.logger import logger

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

def create_auth(mode: str | None, tokens_str: str = "") -> JWTVerifier | ConstantTimeTokenVerifier | None:
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
    public_key = os.getenv("JWT_PUBLIC_KEY")
    jwks_uri = os.getenv("JWT_JWKS_URI")
    issuer = os.getenv("JWT_ISSUER")

    if public_key and jwks_uri:
        raise ValueError("Set JWT_PUBLIC_KEY or JWT_JWKS_URI, not both")
    if not public_key and not jwks_uri:
        raise ValueError("JWT_PUBLIC_KEY or JWT_JWKS_URI required when AUTH_MODE=jwt")

    algorithm = _detect_algorithm(public_key, jwks_uri)

    return JWTVerifier(
        public_key=public_key,
        jwks_uri=jwks_uri,
        algorithm=algorithm,
        issuer=issuer,
        ssrf_safe=bool(jwks_uri),  # SSRF protection for JWKS fetching
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
                raise ValueError(f"Empty email after ':' in MCP_AUTH_TOKENS")
            if not EMAIL_PATTERN.match(email):
                raise ValueError(f"Invalid email format in MCP_AUTH_TOKENS: '{email}'")
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
```

**Key design decisions embedded:**
- Split `token:email` on first colon only (emails never contain unescaped colons)
- Whitespace stripped from tokens and emails
- Empty entries skipped (handles trailing commas)
- Tokens without `:` = service account (no email claim, no PDP) — logged with warning
- Email format validated at startup (fail fast)
- Algorithm auto-detected from key format (no `JWT_ALGORITHM` env var needed)
- `ssrf_safe=True` when using JWKS URI (blocks private IP fetching)

### Phase 1.5: Create `ConstantTimeTokenVerifier`

**File:** `domo_mcp/token_verifier.py` — NEW

The security audit found that `StaticTokenVerifier` uses `dict.get()` (not constant-time) and is documented as "never use in production". Create a custom verifier extending FastMCP's `TokenVerifier` base class with `secrets.compare_digest()`.

```python
# domo_mcp/token_verifier.py
from __future__ import annotations
import secrets
from typing import Any
from fastmcp.server.auth import TokenVerifier, AccessToken

class ConstantTimeTokenVerifier(TokenVerifier):
    """Bearer token verifier with constant-time comparison.

    Unlike FastMCP's StaticTokenVerifier (which uses dict.get()),
    this uses secrets.compare_digest() to prevent timing attacks.
    """

    def __init__(self, tokens: dict[str, dict[str, Any]], **kwargs):
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
```

> **Why not keep `auth.py`?** The existing `AuthMiddleware` is ASGI middleware — it wraps the app and handles HTTP concerns (header extraction, 401 responses). `ConstantTimeTokenVerifier` extends `TokenVerifier`, letting FastMCP handle HTTP concerns while we provide the secure comparison. This is cleaner separation.

### Phase 2: Delete `auth.py`

**File:** `domo_mcp/auth.py` — DELETE

The custom `AuthMiddleware` is replaced by `ConstantTimeTokenVerifier` (Phase 1.5). FastMCP handles:
- Bearer token extraction from `Authorization` header
- Token validation (via `verify_token()` — our constant-time implementation)
- Populating `AccessToken` with claims (including email)
- Returning 401 for invalid tokens

### Phase 3: Simplify `api/mcp.py`

**File:** `api/mcp.py`

Remove all manual middleware wrapping. Auth is now passed to `create_server()` for all modes.

```python
# api/mcp.py - pseudocode
AUTH_MODE = os.getenv("AUTH_MODE", "bearer")
tokens_str = os.getenv("MCP_AUTH_TOKENS", "")

auth = create_auth(AUTH_MODE, tokens_str)
mcp = create_server(auth=auth)

# ASGI app — no more AuthMiddleware wrapping
app = mcp.http_app(
    path="/api/mcp",
    middleware=middleware,  # CORS only
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
)
app = RequestFilterMiddleware(app)  # n8n compat stays
```

Lines deleted: `get_valid_tokens()`, `AuthMiddleware` import, bearer-mode `if` block (~15 lines).

### Phase 4: Verify `identity.py` compatibility

**File:** `domo_mcp/identity.py` — likely NO changes needed

`ConstantTimeTokenVerifier` populates `AccessToken.claims` with whatever dict we pass in `_create_bearer_verifier()`. Since we set `claims["email"]` for mapped tokens, `identity.py` will find it via `claims.get("email")`.

**Verified:** Both `ConstantTimeTokenVerifier` and `JWTVerifier` extend `TokenVerifier`. `get_access_token()` returns `AccessToken` for both. Confirmed by reading FastMCP source: `StaticTokenVerifier` uses `claims=token_data` at line 544, and our `ConstantTimeTokenVerifier` follows the same pattern.

**Optional hardening:** Add type validation for the email claim in `identity.py`:

```python
email = upstream.get("email") or claims.get("email")
if email is not None and not isinstance(email, str):
    return None  # Reject non-string email claims
```

### Phase 5: Update tests

**Files to update:**

| Test File | Changes |
|-----------|---------|
| `tests/test_auth.py` | **Rewrite** — test `ConstantTimeTokenVerifier` directly. Test constant-time comparison, token:email mapping, service account tokens, PDP activation. |
| `tests/test_auth_config.py` | **Rewrite** — test new env var combinations: JWT with JWKS URI, JWT with public key, bearer with emails, bearer without emails, validation errors, algorithm auto-detection. |
| `tests/test_identity.py` | **Add test** — verify email extraction works with `ConstantTimeTokenVerifier` claims format. |

**New file:** `tests/test_token_verifier.py` — unit tests for `ConstantTimeTokenVerifier`

**Files unchanged:** `test_pdp.py`, `test_user_resolver.py`, `test_validation.py`, `test_request_filter.py`, `test_domo_client.py`

**New test cases to add:**

```python
# test_auth_config.py
def test_jwt_with_jwks_uri():
    """JWT mode with JWKS URI creates JWTVerifier with jwks_uri and ssrf_safe=True."""

def test_jwt_with_public_key_rs256():
    """JWT mode with PEM public key auto-detects RS256."""

def test_jwt_with_hmac_secret():
    """JWT mode with raw string auto-detects HS256."""

def test_jwt_both_key_and_jwks_raises():
    """Setting both JWT_PUBLIC_KEY and JWT_JWKS_URI raises ValueError."""

def test_jwt_neither_key_nor_jwks_raises():
    """Setting neither JWT_PUBLIC_KEY nor JWT_JWKS_URI raises ValueError."""

def test_bearer_with_email_mapping():
    """Bearer tokens with :email create ConstantTimeTokenVerifier with email claims."""

def test_bearer_without_email():
    """Bearer tokens without :email create ConstantTimeTokenVerifier without email claims."""

def test_bearer_mixed_tokens():
    """Mix of token:email and plain tokens works correctly."""

def test_bearer_backward_compatible():
    """Plain MCP_AUTH_TOKENS=token1,token2 works as before (no PDP)."""

def test_bearer_empty_tokens():
    """Empty MCP_AUTH_TOKENS returns None (no auth)."""

def test_bearer_invalid_email_raises():
    """Invalid email format raises ValueError at startup."""

def test_bearer_empty_email_raises():
    """Token with colon but empty email raises ValueError."""

# test_token_verifier.py
async def test_constant_time_verify_valid_token():
    """Valid token returns AccessToken with claims."""

async def test_constant_time_verify_invalid_token():
    """Invalid token returns None."""

async def test_email_in_claims():
    """Email mapped tokens include email in AccessToken.claims."""

async def test_service_account_no_email():
    """Service account tokens have no email in claims."""
```

### Phase 6: Update documentation

**README.md changes:**
- Replace "MCP Server Authentication Modes" section with new env var model
- Add JWKS URI examples for Auth0, Okta, Azure
- Update "JWT Authentication (Gateway Integration)" section — remove HKDF mention
- Add migration note: `JWT_SIGNING_KEY` → `JWT_PUBLIC_KEY`
- Add warning about service account tokens bypassing PDP
- Update Architecture section

**CLAUDE.md changes:**
- Remove `auth.py` from project structure
- Update `auth_config.py` description
- Update env vars section with new JWT vars
- Remove `JWT_SIGNING_KEY` and `GATEWAY_BASE_URL` references

## Acceptance Criteria

- [x] `AUTH_MODE=jwt` with `JWT_JWKS_URI` works (Auth0/Okta/Azure path)
- [x] `AUTH_MODE=jwt` with `JWT_PUBLIC_KEY` + PEM auto-detects RS256
- [x] `AUTH_MODE=jwt` with `JWT_PUBLIC_KEY` + raw string auto-detects HS256 (gateway path)
- [x] `AUTH_MODE=jwt` with `JWT_JWKS_URI` enables `ssrf_safe=True`
- [x] `AUTH_MODE=bearer` with `MCP_AUTH_TOKENS=token:email` triggers PDP
- [x] `AUTH_MODE=bearer` with `MCP_AUTH_TOKENS=token` (no email) bypasses PDP + logs warning
- [x] `AUTH_MODE=bearer` with `MCP_AUTH_TOKENS=token1,token2` (v0.1.x format) works unchanged
- [x] `AUTH_MODE=bearer` uses `ConstantTimeTokenVerifier` (not `StaticTokenVerifier`)
- [x] `AUTH_MODE=none` works (no auth)
- [x] `auth.py` deleted, replaced by `token_verifier.py`
- [x] `auth_config.py` uses `JWTVerifier` + `ConstantTimeTokenVerifier`
- [x] `api/mcp.py` has no manual middleware wrapping for bearer
- [x] `identity.py` works with both `JWTVerifier` and `ConstantTimeTokenVerifier` claims
- [x] Bearer token parsing validates email format at startup
- [x] All existing tests pass (rewritten where needed)
- [x] New tests cover JWKS URI, RS256, email mapping, mixed tokens, input validation
- [x] README documents all auth modes with examples
- [x] Startup fails with clear error for invalid auth config

## Spec Analysis: Addressed Gaps

The spec-flow analyzer raised 26 gaps. Most are already handled by existing code or have obvious defaults:

| Gap | Resolution |
|-----|-----------|
| JWT email claim name | Already defined in `identity.py`: `upstream_claims.email` then `email`. Unchanged. |
| Colon parsing | Split on first colon. Emails don't contain unescaped colons. |
| User resolver failure | Already returns "Your account is not linked to a Domo account". Unchanged. |
| Service account scope | Uses `DOMO_DEVELOPER_TOKEN` permissions. By design. Document warning. |
| Algorithm enforcement | FastMCP's JWTVerifier enforces strict algorithm matching already. |
| Multiple issuers | Comma-separated `JWT_ISSUER`, passed as list to FastMCP. |
| Startup validation | Keep existing pattern: `ValueError` for missing/invalid env vars. |
| JWKS refresh | FastMCP caches JWKS for 1 hour. Documented. |
| Token logging | Current code logs counts, not values. Keep. |
| Backward compatibility | `AUTH_MODE=bearer` default unchanged. `JWT_SIGNING_KEY` was never released. |

## Dependencies & Risks

**Dependencies:**
- FastMCP v3 `TokenVerifier` base class must be extensible — verified by reading source, `ConstantTimeTokenVerifier` extends it
- `get_access_token()` dependency injection must work with `ConstantTimeTokenVerifier` — both `JWTVerifier` and `StaticTokenVerifier` extend `TokenVerifier`, so our custom class will too
- `ssrf_safe=True` requires no additional dependencies (FastMCP handles it internally)

**Risks:**
- **JWKS URI cold start latency** on Vercel (~150-500ms extra on first request). Cached for 1 hour by FastMCP. Acceptable tradeoff, document in README.
- **Timing attack residual risk**: `ConstantTimeTokenVerifier` uses `secrets.compare_digest()` per token, but iterates through all tokens sequentially. With few tokens (1-3 typical), this is negligible. If token count grows large, consider hashing approach.
- **Algorithm auto-detection edge cases**: EC keys with "RSA" in PEM comments could misdetect. Unlikely in practice — standard PEM formats use `-----BEGIN EC PRIVATE KEY-----` or `-----BEGIN PUBLIC KEY-----`.

## Security Considerations

The security audit (`docs/security-audit-auth-redesign-2026-02-16.md`) raised 20 findings. Key items addressed in this plan:

| Finding | Severity | Resolution |
|---------|----------|------------|
| StaticTokenVerifier timing attacks | CRITICAL | Use `ConstantTimeTokenVerifier` instead |
| JWKS SSRF | CRITICAL | Enable `ssrf_safe=True` |
| Token injection via colon | CRITICAL | Validate email format at startup |
| Service account PDP bypass | CRITICAL | Intentional by design — add startup warning + README documentation |
| Algorithm confusion | CRITICAL | Already protected by FastMCP's `JsonWebToken([algorithm])` — add test |
| Token logging exposure | CRITICAL | Current code already logs counts not values — keep pattern |
| No rate limiting | HIGH | Out of scope (Vercel handles at edge) |
| Cache TTLs | HIGH | Out of scope (existing behavior, not changed by refactor) |

**Deferred to future work:** Rate limiting, cache TTL reduction, timing jitter, JWKS fingerprint pinning, token expiration for bearer mode.

## References

- FastMCP `JWTVerifier`: `.venv/lib/python3.14/site-packages/fastmcp/server/auth/providers/jwt.py:141-484`
- FastMCP `TokenVerifier` base: `.venv/lib/python3.14/site-packages/fastmcp/server/auth/providers/jwt.py:1-140`
- FastMCP `StaticTokenVerifier` (reference only): `.venv/lib/python3.14/site-packages/fastmcp/server/auth/providers/jwt.py:487-550`
- Current `auth_config.py`: `domo_mcp/auth_config.py`
- Current `auth.py`: `domo_mcp/auth.py` (to be deleted)
- Current `api/mcp.py`: `api/mcp.py:22-77` (auth flow)
- Security audit: `docs/security-audit-auth-redesign-2026-02-16.md`
- Brainstorm: `docs/brainstorms/2026-02-16-service-account-pdp-bypass-brainstorm.md`
