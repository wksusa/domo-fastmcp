---
title: "feat: Native PDP enforcement via per-user Domo access tokens"
type: feat
status: completed
date: 2026-03-28
linear: AIL-660
deepened: 2026-03-28
reviewed: 2026-03-28
---

# Native PDP Enforcement via Per-User Domo Access Tokens

## Enhancement Summary

**Deepened on:** 2026-03-28
**Reviewed on:** 2026-03-28
**Agents used:** Security Sentinel (x2), Performance Oracle, Architecture Strategist (x2), Code Simplicity Reviewer (x2), Python Code Reviewer (x2), Best Practices Researcher, PDP Brainstorm Context Researcher

### Key Improvements from Research
1. **Simplified architecture** — closures inside `create_server()`, no new class or file
2. **Fixed auth detection** — `client_id` prefix check instead of fragile JWT claim inspection
3. **Fixed credential override** — `override_token` at method level on 4 data methods, not in `make_request()`
4. **Fixed error propagation** — single `DomoRequestError(status_code, url)` exception, raised from `make_request()`
5. **Persistent httpx client** — attached to `DomoClient`, closed via FastMCP lifespan
6. **No `_with_pdp` helper** — inline 3-branch logic in each tool (all reviewers agreed)

### Critical Issues Discovered & Resolved
- `make_request()` arg order is `(url, method, data)` not `(method, path, ...)` — fixed throughout
- `make_request()` swallows all HTTP errors and returns `None` — must raise on 401/403 for retry to work
- `_get_headers()` is async — plan pseudocode was missing `await`
- `user_id` is `str` from `UserResolver`, not `int` — fixed cache dict typing + added `int()` guard
- `create_access_token()` swallows exceptions — must re-raise for `_get_user_token` to get root cause
- Risk table contradicted no-fallback decision — corrected
- `_with_pdp` returns `None` sentinel indistinguishable from empty Domo result — removed entirely
- Phase 0b (exception hierarchy) references `override_token` that doesn't exist until Phase 2 — merged
- `search_datasets` uses internal UI search API — results won't be PDP-filtered even with per-user tokens
- Path allowlist had inconsistent implementations (substring match bug) — simplified to method-level override

### Pre-Implementation Verification Needed
- [x] **Test PDP on schema/metadata GETs** — empirically tested 2026-03-28:
  - Schema GET (`/data/v2/...`): **403 Forbidden** — PDP enforced (blocks entirely)
  - Metadata GET (`/data/v3/...`): **200 OK** — PDP NOT enforced (returns metadata regardless)
  - Query POST (`/query/v1/...`): **200 OK** — PDP enforced (row-level filtering)
  - Decision: apply `override_token` to all 4 data methods for consistency.

---

## Overview

Replace the server-side PDP replication in `pdp.py` with native Domo PDP enforcement for JWT-authenticated requests. When a request arrives with JWT auth (user identity via email claim), mint a short-lived Domo access token owned by that user and use it for all dataset queries. Domo enforces PDP at the query layer — row filtering for authorized users, 403 for unauthorized. Bearer token requests continue using the service account as-is.

## Problem Statement / Motivation

The current server-side PDP (`pdp.py`) replicates Domo's permission logic by reading policy metadata and checking group membership. This has three problems:

1. **Cache lag**: Group membership is cached for 1 hour. PDP policy changes in Domo take up to 1 hour to take effect in the MCP server.
2. **Access-only, not row-filtering**: The server-side check is binary — allow or deny. It does NOT filter rows. The actual query runs with the service account token, which returns all data. A user who passes the access check sees everything, not just their PDP-filtered rows.
3. **Maintenance burden**: Custom PDP logic that must stay in sync with Domo's enforcement rules.

Per-user tokens solve all three: Domo enforces PDP natively at query time with row-level filtering, zero cache lag, and no custom logic.

**Empirically confirmed** (Mar 28, 2026): Created per-user tokens for 3 Participant-role users. Locations MASTER returned brand-filtered rows per user's PDP group. KKD Daily VFT returned 403 for users outside PDP groups. Admin tokens bypassed PDP entirely.

## Proposed Solution

**Auth-mode branching in the query path:**

| Auth Mode | Domo Credential | PDP Enforcement | `pdp.py` Used? |
|-----------|----------------|-----------------|----------------|
| JWT (non-admin) | Per-user access token | Native (Domo query layer) | No |
| JWT (admin) | Service account token | None (admin bypasses PDP) | No |
| Bearer (any) | Service account token | None (treated as admin/service) | No |
| None | Service account token | None | No |

**Design change (2026-03-28):** Bearer tokens are always treated as admin/service — no server-side PDP. `pdp.py` is removed entirely. All PDP enforcement happens natively in Domo via per-user tokens (JWT non-admin only).

## Technical Considerations

### Token Lifecycle

- **Creation**: `POST /data/v1/accesstokens` with `ownerId` = resolved Domo user ID
- **TTL**: 1 day expiry on Domo side. Cache locally with 4h TTL to allow rotation.
- **Cleanup**: Delete tokens on cache eviction via `DELETE /data/v1/accesstokens/{id}`. Best-effort — if delete fails, token expires naturally.
- **Cold start budget**: First request for a user pays: user list pagination (~400ms) + token creation (~200-500ms) + actual query (~200-2000ms). Total cold start: 800ms–2.9s. Subsequent requests on warm instances use cache.

#### Research Insights
- Use `time.monotonic()` for cache expiry checks — immune to wall-clock adjustments. Note: existing `_get_headers()` OAuth cache uses `time.time()` — two different clocks in the same process, but the 60s pre-expiry buffer absorbs any skew.
- Add a 60-second pre-expiry buffer: treat tokens as expired 60s before actual expiry to prevent serving a token that expires mid-request.

### Credential Override in DomoClient

**Approach: `override_token` at method level, not in `make_request()`**

All 4 reviewers agreed: instead of adding `override_token` to `make_request()` with a path allowlist, add it directly to the 4 data methods (`query_dataset`, `get_dataset_schema`, `get_dataset_metadata`, `search_datasets`). Each method constructs its own headers and injects the override token. This eliminates the `_PDP_QUERY_PATHS` allowlist entirely — the design prevents misuse by construction rather than by runtime guard.

**Critical: `make_request()` has a dual-branch for `/v1/` paths.** Lines 148-159 route `/v1/` paths to `api.domo.com` with OAuth headers. The `else` branch (lines 161+) uses `X-DOMO-Developer-Token`. The override must only apply in the `else` branch. By keeping `override_token` at the method level (not `make_request()`), each method knows which path it uses and applies the override correctly.

**Critical: `_get_headers()` is async** — all calls must use `await`.

**Constraint: native PDP via per-user tokens only works in `developer_token` auth mode.** In `oauth` mode, headers use `Authorization: Bearer <oauth_token>` and there is no `X-DOMO-Developer-Token` to override. Add a guard or document this constraint.

#### Research Insights
- **Persistent httpx client**: Current code creates a new `httpx.AsyncClient` per `make_request()` call (line 166). Replace with a client attached to `DomoClient.__init__()`, closed via FastMCP lifespan `__aexit__`. Saves 50-120ms per API call. Also fix `_get_public_api_headers()` which has its own per-call client for OAuth token refresh.

### Race Conditions

Drop per-user locks entirely. On Vercel serverless, per-instance concurrency for the *same user* is essentially zero (Fluid Compute routes requests to warm instances, but same-user overlap is rare). Even if a duplicate token is created, the orphan auto-expires in 1 day.

### Admin Users

Skip per-user token minting for admin users — use the service account directly. Check admin BEFORE attempting token mint.

**Known limitation**: `UserResolver.is_admin()` uses a 1-hour cache. If a user is demoted Admin → Participant, they get service-account access (no PDP) for up to 1 hour. Pre-existing limitation; accepted risk.

**Note**: `is_admin()` has an undocumented pre-condition: `resolve()` must have been called first to populate `_role_cache`. Safe in current `_resolve_user()` call order. Add a docstring to prevent future callers from using `is_admin()` directly.

### Vercel Serverless Context

Caches are per-function-instance (cold start resets). With Vercel Fluid Compute (enabled by default since April 2025), warm instances handle 250+ concurrent requests, making module-level in-memory caching effective. The `_token_cache` is defined inside `create_server()` as a closure variable — intentionally per-call for test isolation. Add a comment noting this is deliberate.

### Security

- Per-user tokens have the same permissions as the user in Domo — no privilege escalation possible.
- Tokens are short-lived (1 day) and cached in-memory only (no persistence).
- Service account credentials remain required for token management API calls.
- The `create_access_token` API requires admin-level Domo credentials.
- **Token naming**: Use `mcp-pdp:{user_id}` (not email) to avoid PII leakage in Domo admin console. Note: `user_id` is still a stable Domo integer that maps 1:1 to a user. If SOX compliance requires full opacity, use `mcp-pdp:{hmac(user_id, server_secret)[:12]}` instead.
- **Admin tool gating**: `list_access_tokens`, `create_access_token`, `delete_access_token` should be restricted to `is_admin()` callers (using full `_resolve_user()` to warm the cache first). Any authenticated user can currently enumerate/revoke other users' tokens.
- **Log scrubbing**: Per-user token values must never appear in error logs. When `override_token` is active, log only `status_code` + URL path in error handlers — not `str(e)` which may include response body fragments. Never log the `override_token` value itself.
- **Rate-limit token creation**: Track `_last_mint_time[user_id]` and reject mints within a 10-second window to prevent token enumeration via repeated auth failures.
- **Retry pattern**: Wrap the second attempt in `try/except` to catch `DomoRequestError` and convert to a clean `ToolError` — prevents raw exception leaking to MCP client.

#### Research Insights
- `StaticTokenVerifier` uses `dict.get()` which is not constant-time — timing attacks possible on bearer tokens. The security audit (2026-02-16) recommended a custom `ConstantTimeTokenVerifier` with `secrets.compare_digest()`. Per-user tokens increase this surface area. Address before shipping.
- `filter_accessible_datasets` in `pdp.py` fails open on API error (includes datasets when details can't be fetched). Fix to fail closed for bearer mode.
- `is_jwt_auth()` `client_id` check could theoretically be bypassed if a gateway issues a JWT with `client_id: "bearer:..."`. Add a secondary guard (check for `sub` or `iat` claim presence) if this is a concern.
- `create_access_token()` in `domo.py` swallows all exceptions and returns `None`. Must re-raise so `_get_user_token` gets the root cause. Either remove the `try/except` wrapper or add `raise` after logging.

### Domo Rate Limits

Unknown rate limits on `/data/v1/accesstokens`. If Domo throttles token creation, **return an error to the MCP client** (do NOT fall back to service account). Log a warning.

### Bearer-with-Email Tokens

`MCP_AUTH_TOKENS` supports `token:email@domain.com` format. **Decision: branch on auth type (JWT vs bearer), not email presence.** Bearer-with-email continues using server-side PDP.

#### Dissent (Simplicity Reviewer)
The simplicity reviewer argued for unifying JWT + bearer-with-email under native PDP, since native PDP is *more* restrictive (row filtering vs binary allow/deny). This would eliminate `is_jwt_auth()` entirely. **Counter-argument**: bearer-with-email is used by service integrations that expect stable behavior — changing their PDP enforcement mode is a breaking change. Keep the split; revisit if bearer-with-email users report issues.

### Non-Query Tools (Schema, Metadata, Search)

All data-access tools (`query_dataset`, `get_dataset_schema`, `get_dataset_metadata`, `search_datasets`) use per-user tokens for JWT auth.

**Pre-implementation requirement**: Verify empirically that Domo enforces PDP on schema/metadata GET endpoints with per-user tokens — only `query_dataset` (POST) was tested. If Domo does NOT enforce PDP on those GETs, applying `override_token` to `get_dataset_schema` and `get_dataset_metadata` has no effect and creates a false sense of security.

**Known behavioral difference for `search_datasets`**: The internal Domo search API (`/data/ui/v3/datasources/search`) returns results using the service account's permissions regardless of the per-user token — Domo does not PDP-filter search results, only query execution. JWT users will see all datasets in search results but get 403 or filtered rows when actually querying. This is correct behavior (no data leakage) but a UX difference from bearer mode where `filter_accessible_datasets()` hides inaccessible datasets.

### Token Creation Failure

If `create_access_token()` fails, return an error to the MCP client. Do NOT fall back to service account + server-side PDP — that would silently change the user's data access scope.

**Critical fix needed**: `DomoClient.create_access_token()` currently wraps its `make_request()` call in a bare `except Exception` and returns `None`. This swallows the root cause. Must either remove the `try/except` or re-raise after logging so `_get_user_token` can surface a meaningful error.

### Exception Handling

**Single exception class** (from simplicity review — 3 classes → 1):

```python
# In domo_mcp/domo.py (inline, no new file)
class DomoRequestError(Exception):
    """Raised when Domo API returns an error with override_token active."""
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        super().__init__(f"Domo API {status_code}: {url}")
```

In `make_request()`, when `override_token` is active:

```python
except httpx.HTTPStatusError as e:
    if override_token:
        # Log only status code + URL path, not str(e) which may contain response body
        self.logger.warning(f"Per-user token request failed: {e.response.status_code} {url}")
        raise DomoRequestError(e.response.status_code, url) from e
    self.logger.error(...)
    return None  # existing behavior for service account errors
```

Callers branch on `error.status_code`:
- `401` → retry with fresh token
- `403` → surface as `ToolError("Access denied: ...")`
- Other → surface as generic `ToolError`

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Branching condition | Auth type (JWT vs bearer) | Bearer-with-email is a service account with identity, not a user session |
| Admin users | Skip per-user tokens, check admin FIRST | Same outcome (PDP bypassed), fewer tokens, no wasted API calls |
| Non-query tools | All data tools use per-user tokens | PDP consistency across schema/query; search has known limitation (documented) |
| Token creation failure | Error, no fallback | Fallback silently escalates data access |
| Token TTL (Domo-side) | 1 day | Auto-cleanup, short enough to limit exposure |
| Cache TTL (in-memory) | 4 hours | Shorter than Domo TTL, with 60s pre-expiry buffer |
| Token cleanup | Best-effort delete on eviction | Domo auto-expires, no cleanup job needed |
| Token reuse on cold start | No | `list_access_tokens()` cost likely exceeds creating a new one |
| Per-user locks | No | Vercel serverless makes same-user concurrency near-zero; orphans auto-expire |
| Token naming | `mcp-pdp:{user_id}` | Avoids PII (email) in Domo admin console |
| Implementation pattern | Closures in `create_server()` | Matches existing codebase pattern; no new file or class needed |
| Auth detection | `client_id` prefix check | Stable — tied to our own auth_config.py invariants, not FastMCP internals |
| `override_token` location | Method-level (4 data methods) | Prevents misuse by construction; eliminates path allowlist |
| Helper abstraction | No `_with_pdp` helper — inline branching | All reviewers agreed: helper had broken sentinel return, inline is clearer |
| Exception hierarchy | Single `DomoRequestError(status_code, url)` | Branch on `status_code` at call site; no need for separate classes |

## Acceptance Criteria

- [x] JWT-authenticated requests use per-user Domo tokens for dataset queries
- [x] Per-user queries return PDP-filtered rows (not all rows)
- [x] Bearer-authenticated requests continue using service account (no behavior change)
- [x] Per-user tokens are cached in-memory with 4h TTL
- [x] Expired/invalid tokens are retried once with a fresh token (second failure → clean `ToolError`)
- [x] Admin users skip token minting, use service account directly
- [x] Users not in any PDP group for a dataset get a clear error (not raw 403)
- [x] Token cleanup: deleted from Domo on cache eviction (best-effort)
- [x] No regression in bearer-mode behavior
- [x] `make_request()` raises `DomoRequestError` for HTTP errors when `override_token` is set
- [x] `create_access_token()` re-raises exceptions instead of swallowing them
- [x] `search_datasets` behavioral difference documented (JWT users see all datasets, PDP enforced at query time only)
- [x] `is_admin()` docstring documents `resolve()` pre-condition
- [x] Log scrubbing: no token values in error logs
- [x] Per-user token creation rate-limited (10s per user)

## Implementation

### Phase 0: Persistent httpx client (standalone, ship first)

**`domo.py`** — Replace per-call `httpx.AsyncClient` with a persistent client:

```python
class DomoClient:
    def __init__(self, logger):
        ...
        self._http_client = httpx.AsyncClient(timeout=self.timeout)

    async def close(self):
        """Close the persistent HTTP client. Call from FastMCP lifespan teardown."""
        await self._http_client.aclose()

    async def make_request(self, url, method, data=None):
        ...
        response = await self._http_client.request(method, full_url, headers=headers, json=data)
        ...
```

Also fix `_get_public_api_headers()` which has its own per-call `httpx.AsyncClient` for OAuth token refresh — use the same persistent client.

Register `domo_client.close()` in FastMCP lifespan teardown so connections drain cleanly on shutdown.

### Phase 1: Token cache (closures in `create_server()`)

Inside `create_server()` in `server_factory.py`, after `domo_client` and `user_resolver`:

```python
import time

# Per-user Domo access token cache for native PDP enforcement.
# Defined inside create_server() for test isolation — each call gets an independent cache.
_token_cache: dict[str, tuple[str, int, float]] = {}  # user_id -> (token_value, token_id, expires_at)
_last_mint: dict[str, float] = {}  # user_id -> monotonic timestamp of last mint (rate limit)

async def _get_user_token(user_id: str) -> str:
    """Get or create a Domo access token for the given user. Returns token value."""
    cached = _token_cache.get(user_id)
    if cached and time.monotonic() < (cached[2] - 60):
        return cached[0]

    # Rate limit: reject if minted within last 10 seconds
    last = _last_mint.get(user_id, 0)
    if time.monotonic() - last < 10:
        raise RuntimeError(f"Token creation rate-limited for user {user_id}")

    # Evict old token if present (best-effort delete from Domo)
    if cached:
        try:
            await domo_client.delete_access_token(cached[1])
        except Exception:
            pass  # best-effort; Domo auto-expires in 1 day

    # Create new token — guard against non-numeric user_id
    try:
        numeric_id = int(user_id)
    except ValueError:
        raise RuntimeError(f"Domo user ID is not numeric: {user_id!r}") from None

    result = await domo_client.create_access_token(
        name=f"mcp-pdp:{user_id}",
        owner_id=numeric_id,
        expires=int((time.time() + 86400) * 1000),  # 1 day in epoch ms
    )
    if not result or "token" not in result:
        raise RuntimeError(f"Failed to create per-user Domo token for user {user_id}")

    token_value = result["token"]
    token_id = int(result["id"])  # defensive cast
    _token_cache[user_id] = (token_value, token_id, time.monotonic() + 14400)  # 4h cache TTL
    _last_mint[user_id] = time.monotonic()
    return token_value

async def _invalidate_user_token(user_id: str) -> None:
    """Evict and delete token for a user (on auth failure retry)."""
    cached = _token_cache.pop(user_id, None)
    if cached:
        try:
            await domo_client.delete_access_token(cached[1])
        except Exception:
            pass
```

**Also in this phase**: Fix `create_access_token()` in `domo.py` to re-raise exceptions instead of swallowing:

```python
async def create_access_token(self, name, owner_id, expires):
    try:
        result = await self.make_request(...)
        return result
    except Exception as e:
        self.logger.error(f"Error creating access token: {e}")
        raise  # re-raise — caller needs to know why
```

### Phase 2: DomoClient method-level `override_token` + exception

**`domo_mcp/domo.py`** — Add `DomoRequestError` inline and `override_token` to each data method:

```python
class DomoRequestError(Exception):
    """Raised when Domo API returns an error with override_token active."""
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        super().__init__(f"Domo API {status_code}: {url}")
```

Each data method handles the override in its own header construction:

```python
async def query_dataset(self, dataset_id: str, sql: str, *, override_token: str | None = None) -> dict | None:
    url = f"/query/v1/execute/{dataset_id}"
    headers = await self._get_headers()  # NOTE: async!
    if override_token:
        headers["X-DOMO-Developer-Token"] = override_token
    try:
        # ... execute request with headers ...
    except httpx.HTTPStatusError as e:
        if override_token:
            self.logger.warning(f"Per-user token request failed: {e.response.status_code} {url}")
            raise DomoRequestError(e.response.status_code, url) from e
        self.logger.error(...)
        return None

# Similarly for get_dataset_schema(), get_dataset_metadata(), search_datasets()
```

This approach:
- Eliminates `_PDP_QUERY_PATHS` allowlist entirely — override only exists on methods that need it
- No changes to `make_request()` signature
- No risk of `override_token` being applied to admin paths
- Each method handles its own header construction (already the case for the `/v1/` branch)

### Phase 3: Auth mode detection

**`domo_mcp/identity.py`** — `client_id` prefix check:

```python
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
```

### Phase 4: Server factory branching (inline, no helper)

Keep `_resolve_user()` as a 3-tuple (unchanged). Inline the 3-branch PDP logic in each of 4 data tools:

```python
# In each data tool (query_dataset, get_dataset_schema, get_dataset_metadata, search_datasets):
user_id, email, is_admin = await _resolve_user()

# Determine PDP mode
override_token = None
if email and user_id and not is_admin and is_jwt_auth():
    override_token = await _get_user_token(user_id)

if override_token:
    # Native PDP path — Domo enforces at query layer
    try:
        result = await domo_client.query_dataset(dataset_id, sql, override_token=override_token)
    except DomoRequestError as e:
        if e.status_code == 401:
            # Token revoked externally — retry once with fresh token
            await _invalidate_user_token(user_id)
            try:
                override_token = await _get_user_token(user_id)
                result = await domo_client.query_dataset(dataset_id, sql, override_token=override_token)
            except (DomoRequestError, RuntimeError):
                raise ToolError("Authentication failed after token refresh — check Domo account status")
        elif e.status_code == 403:
            raise ToolError("Access denied: you don't have permission to query this dataset")
        else:
            raise ToolError(f"Domo API error ({e.status_code}) querying dataset")
elif email and user_id and not is_admin:
    # Bearer mode — server-side PDP
    details = await domo_client.get_dataset_details(dataset_id)
    if not check_dataset_access(user_id, details, domo_client):
        raise ToolError(f"Access denied: PDP policy blocks access to dataset {dataset_id}")
    result = await domo_client.query_dataset(dataset_id, sql)
else:
    # No identity or admin — service account, no PDP
    result = await domo_client.query_dataset(dataset_id, sql)
```

~15 lines per tool, 4 tools. The branching is explicit and readable. Each tool's error messages can be specific to what it does (query vs schema vs search).

### Phase 5: Admin tool gating + cleanup

- Add `is_admin()` check to `list_access_tokens`, `create_access_token`, `delete_access_token` tools — use full `_resolve_user()` to warm the cache first
- Add docstring to `UserResolver.is_admin()` documenting the `resolve()` pre-condition
- Fix `filter_accessible_datasets` in `pdp.py` to fail closed (exclude datasets when details can't be fetched)

## Dependencies & Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Domo rate-limits token creation | Low | Medium | Return error to MCP client. Do NOT fall back to service account. Per-user 10s rate limit prevents abuse. |
| Token revoked externally mid-session | Low | Low | Retry once with fresh token; second failure → clean ToolError |
| Orphaned tokens accumulate on cold starts | Low | Low | 1-day Domo-side expiry; optional cleanup sweep |
| Domo changes accesstoken API behavior | Low | High | Feature flag to disable native PDP |
| Cache memory on high-user-count instance | Low | Low | Vercel cold starts reset; add LRU cap if needed |
| Admin role demotion takes 1h to take effect | Low | Medium | Pre-existing UserResolver cache limitation; accepted risk |
| `search_datasets` shows unfiltered results for JWT users | Certain | Low | By design — no data leakage, just UX inconsistency; documented |
| PDP not enforced on schema/metadata GETs | Unknown | High | Must verify empirically before Phase 2 implementation |
| `is_jwt_auth()` bypass via gateway misconfiguration | Very Low | Medium | `client_id` prefix is under our control; add secondary claim check if needed |
| `override_token` only works in `developer_token` auth mode | Certain | Low | Document constraint; `oauth` mode users continue with server-side PDP |

## References

- `domo_mcp/domo.py:86-113` — `_get_headers()` (async!) and `_get_public_api_headers()`
- `domo_mcp/domo.py:142-229` — `make_request()` (actual arg order: `url, method, data`; dual-branch for `/v1/` paths)
- `domo_mcp/domo.py:261-274` — `query_dataset()` (POST to `/query/v1/execute/{id}`)
- `domo_mcp/domo.py:441-476` — `create_access_token` / `delete_access_token` (swallows exceptions — must fix)
- `domo_mcp/server_factory.py:57-71` — `_resolve_user()` (returns 3-tuple: `user_id, email, is_admin`)
- `domo_mcp/server_factory.py:131-162` — `query_dataset` tool
- `domo_mcp/pdp.py:38-74` — server-side PDP (kept for bearer mode)
- `domo_mcp/pdp.py:91-101` — `filter_accessible_datasets` (fails open — fix to fail closed)
- `domo_mcp/identity.py:10-40` — `get_user_email()`
- `domo_mcp/auth_config.py:52-71` — `_parse_domo_bearer_tokens()` (sets `bearer:` prefix on `client_id`)
- `domo_mcp/user_resolver.py:11-57` — email → user_id resolution (`user_id` is `str`, not `int`; `is_admin()` requires prior `resolve()`)
- `docs/brainstorms/2026-02-16-service-account-pdp-bypass-brainstorm.md` — original PDP design decision
- `docs/security-audit-auth-redesign-2026-02-16.md` — security audit of auth layer
- Linear: [AIL-660](https://linear.app/wksusa/issue/AIL-660)
