# Dual Auth Endpoints: No-Auth + JWT on Same Deployment

**Date:** 2026-02-16
**Status:** Decided

## What We're Building

Two separate Vercel serverless endpoints sharing the same server factory:
- `/mcp` — JWT-authenticated, with PDP enforcement
- `/mcp-open` — No authentication, full dataset access (no PDP)

This supports gradual migration from no-auth to JWT auth. Both endpoints are available in all environments, controlled by env vars.

## Why This Approach

FastMCP applies auth globally per server instance — you can't mix auth and no-auth on a single endpoint without fighting the framework. Two thin serverless entry points is the simplest solution:

- `api/mcp.py` — existing file, creates server with `auth=JWTVerifier`
- `api/mcp_open.py` — new file, creates server with `auth=None`
- Both call `create_server()` from `server_factory.py`

**Rejected alternatives:**
- *Optional auth middleware* — fights FastMCP's auth model, fragile across upgrades
- *Edge middleware router* — over-engineered for this use case

## Key Decisions

1. **Separate URLs, not optional auth on one URL** — cleaner separation, easier to reason about security
2. **Both endpoints available in all environments** — not restricted to dev/staging
3. **Shared server factory** — tools defined once, auth is the only difference
4. **No-auth endpoint has no PDP** — without identity, PDP can't be enforced (this is expected)

## Implementation Notes

- Add `api/mcp_open.py` (thin wrapper, ~30 lines)
- Add Vercel rewrite rules for `/mcp-open` → `/api/mcp_open`
- When migration is complete, delete `api/mcp_open.py` and its rewrite rules
