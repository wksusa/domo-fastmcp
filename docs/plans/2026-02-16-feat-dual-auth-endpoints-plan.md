---
title: "feat: Add no-auth endpoint alongside JWT endpoint"
type: feat
status: completed
date: 2026-02-16
---

# feat: Add no-auth endpoint alongside JWT endpoint

## Overview

Add a second Vercel serverless endpoint (`api/mcp_open.py`) that serves the same MCP tools without authentication, alongside the existing JWT-protected `api/mcp.py`. This supports gradual migration from no-auth to JWT auth.

## Proposed Solution

Create a thin wrapper file `api/mcp_open.py` that calls `create_server(auth=None)` and wire it up in `vercel.json`. Both endpoints share `server_factory.py` — the only difference is auth.

## Implementation

### 1. Create `api/mcp_open.py`

New file (~30 lines), modeled after `api/mcp.py` but with `auth=None`:

```python
# api/mcp_open.py
"""Vercel serverless endpoint — no authentication (migration aid)."""

import os
from fastmcp.server.event_store import EventStore
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from domo_mcp.logger import Logger
from domo_mcp.request_filter import RequestFilterMiddleware
from domo_mcp.server_factory import create_server

logger = Logger()
logger.warning("No-auth MCP endpoint active — no authentication or PDP enforcement")

mcp = create_server(auth=None)

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["mcp-protocol-version", "mcp-session-id", "Content-Type"],
    )
]

_event_store = EventStore()
app = mcp.http_app(
    path="/api/mcp_open",
    middleware=middleware,
    stateless_http=True,
    json_response=True,
    event_store=_event_store,
    retry_interval=2000,
)

app = RequestFilterMiddleware(app)
```

Note: `Authorization` header removed from CORS `allow_headers` since auth isn't used.

### 2. Update `vercel.json`

Add rewrite rules and function config for the new endpoint:

```json
{
  "rewrites": [
    { "source": "/mcp/:path*", "destination": "/api/mcp" },
    { "source": "/mcp", "destination": "/api/mcp" },
    { "source": "/mcp-open/:path*", "destination": "/api/mcp_open" },
    { "source": "/mcp-open", "destination": "/api/mcp_open" }
  ],
  "functions": {
    "api/mcp.py": { "maxDuration": 120 },
    "api/mcp_open.py": { "maxDuration": 120 }
  }
}
```

### 3. Update docs

- Update `README.md` to document both endpoints
- Update `CLAUDE.md` project structure to include `api/mcp_open.py`

## Acceptance Criteria

- [x] `api/mcp_open.py` created and serves tools without auth
- [ ] `/mcp-open` route works on Vercel deployment
- [x] `/mcp` route continues to require JWT auth (no regression)
- [x] Startup log warns that no-auth endpoint is active
- [x] `vercel.json` has rewrite rules for both endpoints
- [x] Docs updated

## Cleanup

When JWT migration is complete, delete `api/mcp_open.py` and remove its entries from `vercel.json`.

## References

- Brainstorm: `docs/brainstorms/2026-02-16-dual-auth-endpoints-brainstorm.md`
- Existing endpoint: `api/mcp.py`
- Shared factory: `domo_mcp/server_factory.py`
