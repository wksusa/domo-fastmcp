---
title: "Flexible Auth & Identity for Open Source Users"
type: architecture
status: decided
date: 2026-02-16
---

# Flexible Auth & Identity for Open Source Users

## What We're Building

A redesigned auth layer that supports multiple identity sources — so PDP works for any user, not just those behind our specific JWT gateway. Service accounts (no identity) coexist with human users (PDP-enforced) in a single deployment or across separate ones.

## Why This Matters

The current auth is too rigid for an open source project:

- **JWT mode** is hard-coded to HKDF key derivation + HS256 + single issuer — only works with our specific gateway
- **Bearer mode** has no identity concept — PDP can never work
- **Custom `AuthMiddleware`** duplicates what FastMCP's `StaticTokenVerifier` already provides (with identity support)
- Users wanting PDP without a gateway have no path

FastMCP v3 already ships `JWTVerifier` (RS256, JWKS URI, multiple issuers, audience validation) and `StaticTokenVerifier` (bearer tokens with claims). We're using almost none of it.

## Key Decisions

### Decision 1: Replace custom auth with FastMCP verifiers

**Delete `auth.py` (our custom `AuthMiddleware`)** and use FastMCP's built-in verifiers instead:

| Auth Mode | FastMCP Class | Identity | PDP |
|-----------|--------------|----------|-----|
| `jwt` | `JWTVerifier` | Email from JWT claims | Enforced |
| `bearer` | `StaticTokenVerifier` | Email from token map (optional) | If email mapped |
| `none` | No verifier | None | Skipped |

All three modes flow through FastMCP's `AccessToken` → `get_access_token()` → `identity.py` pipeline. PDP continues to gate on `get_user_email()` returning non-None.

**Key assumption (verified):** Both `JWTVerifier` and `StaticTokenVerifier` extend FastMCP's `TokenVerifier` base class and populate `AccessToken.claims`. The `get_access_token()` dependency injection works identically for both — `identity.py` reads `claims["email"]` regardless of which verifier produced the token.

### Decision 2: Generalize JWT configuration

Replace the hard-coded HKDF + HS256 + single issuer with env vars that expose JWTVerifier's full capabilities:

| Env Var | Purpose | Default |
|---------|---------|---------|
| `JWT_ALGORITHM` | Signing algorithm | `RS256` |
| `JWT_PUBLIC_KEY` | PEM public key or HMAC secret | — |
| `JWT_JWKS_URI` | JWKS endpoint URL (alternative to public key) | — |
| `JWT_ISSUER` | Expected issuer(s), comma-separated | — |
| `JWT_AUDIENCE` | Expected audience | — |

Users provide either `JWT_PUBLIC_KEY` or `JWT_JWKS_URI` (not both). This supports:
- **Auth0/Okta/Azure** via JWKS URI + RS256 (most common)
- **Custom gateways** via shared secret + HS256
- **Self-signed** via PEM public key + RS256/ES256

HKDF key derivation is dropped from the MCP server. HS256 users provide the raw secret directly via `JWT_PUBLIC_KEY`. The gateway (mcp-gateway) must derive its own signing key before configuring both sides with the same raw secret.

### Decision 3: Bearer tokens with optional email mapping

Combined env var format:

```bash
# Tokens with :email get PDP enforcement
# Tokens without :email are service accounts (no PDP, full access)
MCP_AUTH_TOKENS="abc123:alice@corp.com,xyz789:bob@corp.com,svc-token-001"
```

Parsing rules:
- Split on `,` to get token entries
- If entry contains `:`, split into `token:email`
- If no `:`, token has no identity (service account)
- Backward compatible: existing `MCP_AUTH_TOKENS=token1,token2` works unchanged
- Note: `secrets.token_urlsafe()` never generates `:`, so the delimiter is safe for generated tokens. User-provided tokens containing `:` are not supported — document this constraint.

Implementation: Build a `StaticTokenVerifier` tokens dict where email-mapped tokens include an `email` claim, and unmapped tokens have no email claim.

## What Gets Deleted

- `domo_mcp/auth.py` — Custom `AuthMiddleware` replaced by `StaticTokenVerifier`
- HKDF key derivation in `auth_config.py` — dropped; raw keys only
- `fastmcp.server.auth.jwt_issuer.derive_jwt_key` import — no longer needed

## What Gets Modified

- `domo_mcp/auth_config.py` — Rewritten to build `JWTVerifier` or `StaticTokenVerifier` from env vars
- `api/mcp.py` — Simplified: no more manual middleware wrapping for bearer mode
- `README.md` — Auth docs rewritten for the new env var model
- `.claude/CLAUDE.md` — Updated project structure (auth.py removed)

## What Stays the Same

- `server_factory.py` — PDP gate logic unchanged (`if get_user_email(): enforce`)
- `identity.py` — Core logic unchanged (reads email from `AccessToken.claims`)
- `pdp.py`, `user_resolver.py` — Unchanged
- `request_filter.py` — Unchanged

## Backward Compatibility

- `AUTH_MODE=bearer` + `MCP_AUTH_TOKENS=token1,token2` (no emails) → identical to v0.1.x behavior
- `AUTH_MODE=jwt` requires new env vars (`JWT_PUBLIC_KEY` or `JWT_JWKS_URI` instead of `JWT_SIGNING_KEY`) — **breaking change** for JWT users, but JWT was introduced in v0.2.0 (unreleased), so no real-world breakage

## Open Questions

None — all key decisions resolved through brainstorming.
