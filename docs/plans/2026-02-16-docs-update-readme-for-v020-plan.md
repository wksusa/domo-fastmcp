---
title: "docs: Update README for v0.2.0"
type: docs
status: completed
date: 2026-02-16
---

# Update README for v0.2.0

Update README.md and CLAUDE.md to reflect FastMCP v3 upgrade, multi-mode auth (JWT/bearer/none), and PDP authorization.

## What Changed in Code (Context)

- FastMCP v2 → v3.0.0rc2
- Tools consolidated into `server_factory.py` (no more duplication)
- `AUTH_MODE` env var: `jwt` | `bearer` (default) | `none`
- JWT auth via FastMCP `JWTVerifier` (HS256, for gateway integration)
- PDP enforcement on dataset tools when JWT provides user identity
- New env vars: `AUTH_MODE`, `JWT_SIGNING_KEY`, `GATEWAY_BASE_URL`
- Version bumped to 0.2.0

## Sections to Update

### 1. Fix factual errors

- **Line 76** — Deploy command: `vercel deploy --prod` → `npm run build -- --vercel && vercel deploy --prod --prebuilt`
- **Lines 339-347** — Architecture section says "local stdio uses original MCP implementation" → both modes now use FastMCP v3 via `server_factory.py`
- **Line 3** — Description: add mention of JWT auth and PDP

### 2. Update Authentication Modes section

Add a new **"MCP Server Authentication Modes"** section (after the Domo API auth table, before Setup). This replaces the implicit bearer-only model:

| Mode | `AUTH_MODE` | Required Env Vars | Use Case |
|------|-------------|-------------------|----------|
| Bearer Token | `bearer` (default) | `MCP_AUTH_TOKENS` | Direct client access, existing setups |
| JWT | `jwt` | `JWT_SIGNING_KEY`, `GATEWAY_BASE_URL` | Gateway integration with per-user identity |
| None | `none` | — | Local development, stdio mode |

Key points to document:
- `bearer` is the default → **zero-config upgrade** from v0.1.x
- `jwt` enables PDP (per-user dataset access)
- `none` disables all MCP-level auth (Domo API auth still applies)

### 3. Add PDP section

New section **"Personalized Data Permissions (PDP)"** after Available MCP Tools table:

- What: Domo's row-level security enforced at the MCP layer
- When: Only active in `AUTH_MODE=jwt` (user identity required)
- How: JWT email → Domo user ID resolution → policy check on each dataset tool
- Which tools: `query_dataset`, `get_dataset_schema`, `get_dataset_metadata` (access check), `search_datasets` (result filtering)
- Role tools (`list_roles`, `create_role`, `list_role_authorities`): unaffected
- Error messages: "Access denied", "Your account is not linked to a Domo account"

### 4. Update Vercel Deployment section

Add JWT mode env vars alongside existing bearer setup:

```bash
# Auth mode (choose one):
# Option A: Bearer token (default, backward compatible)
vercel env add AUTH_MODE production  # set to "bearer"
vercel env add MCP_AUTH_TOKENS production

# Option B: JWT (for gateway integration with per-user PDP)
vercel env add AUTH_MODE production  # set to "jwt"
vercel env add JWT_SIGNING_KEY production
vercel env add GATEWAY_BASE_URL production
```

Fix the deploy command:
```bash
npm run build -- --vercel
vercel deploy --prod --prebuilt
```

### 5. Update Security & Authentication section

- Rename/restructure to cover both bearer and JWT modes
- Add JWT subsection explaining: HS256 signing, key derivation from `JWT_SIGNING_KEY`, issuer validation against `GATEWAY_BASE_URL`
- Add PDP security model: how user identity flows from JWT → email → Domo user ID → policy check
- Keep existing bearer token rotation documentation

### 6. Add Troubleshooting entries for JWT/PDP

- "Invalid JWT signature" — check `JWT_SIGNING_KEY` matches gateway, verify HS256
- "JWT issuer mismatch" — check `GATEWAY_BASE_URL` matches gateway's `iss` claim exactly
- "Your account is not linked to a Domo account" — JWT email doesn't match any Domo user email
- "Access denied" on dataset — PDP policy doesn't include user or their groups

### 7. Update CLAUDE.md

- Add `server_factory.py`, `auth_config.py`, `identity.py`, `user_resolver.py`, `pdp.py` to project structure
- Add new env vars (`AUTH_MODE`, `JWT_SIGNING_KEY`, `GATEWAY_BASE_URL`) to env vars section
- Update "Two Server Modes" to note both use FastMCP via `server_factory.py`

## Backward Compatibility Note

Existing `AUTH_MODE=bearer` (or unset) deployments with `MCP_AUTH_TOKENS` require **zero changes** to upgrade. The default `AUTH_MODE` is `bearer`, which preserves the exact v0.1.x behavior.

## Out of Scope

- No new `.env.example` file (project doesn't use one)
- No changelog file (use git log / GitHub releases)
- No separate docs pages (project uses flat README)

## Acceptance Criteria

- [x] All factual errors fixed (deploy command, architecture section)
- [x] Auth modes table with jwt/bearer/none documented
- [x] PDP section explains what/when/how
- [x] Vercel setup shows both bearer and JWT env var options
- [x] Security section covers JWT alongside bearer
- [x] Troubleshooting includes JWT and PDP errors
- [x] CLAUDE.md project structure and env vars updated
- [x] Existing bearer token documentation preserved (backward compat)
