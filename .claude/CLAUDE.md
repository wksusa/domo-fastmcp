# Agent Instructions

## Project Overview

**Domo MCP Server** - A Model Context Protocol server that connects AI assistants to Domo's data platform. Fork of DomoApps/domo-mcp-server with OAuth, JWT auth, PDP authorization, and Vercel deployment via FastMCP v3.

### Key Capabilities
- Query Domo datasets with SQL
- Search datasets by name
- Get dataset metadata and schema
- Manage roles and authorities

## Project Structure

```
domo_mcp/               # Main package
├── __init__.py         # Package version (__version__)
├── __main__.py         # Entry point for `python -m domo_mcp`
├── server.py           # Thin wrapper for stdio mode
├── server_factory.py   # Shared server factory - all 7 tools defined here
├── domo.py             # DomoClient - Domo API interactions
├── auth.py             # Bearer token ASGI middleware
├── auth_config.py      # Auth mode factory (jwt/bearer/none)
├── identity.py         # JWT email extraction from access token
├── user_resolver.py    # Email → Domo user ID resolution (cached)
├── pdp.py              # PDP authorization checks on datasets
├── request_filter.py   # Middleware to strip extra fields (n8n compat)
├── validation.py       # Pydantic input validation
└── logger.py           # Logging utilities

api/
└── mcp.py              # Vercel serverless endpoint (HTTP mode)

tests/                  # pytest tests
```

### Two Server Modes
Both modes use `server_factory.py` to define tools once:
1. **stdio** (`domo_mcp/server.py`) - For local use with VS Code, Claude Desktop
2. **HTTP** (`api/mcp.py`) - For Vercel deployment, supports Bearer/JWT auth

## Development

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables
Create `.env` or `.env.local`:
```bash
# Domo API (choose one):
DOMO_DEVELOPER_TOKEN=xxx    # Recommended - full API access
DOMO_HOST=instance.domo.com

# Or OAuth:
DOMO_CLIENT_ID=xxx
DOMO_CLIENT_SECRET=xxx

# MCP server auth (choose one):
AUTH_MODE=bearer               # jwt, bearer (default), or none
MCP_AUTH_TOKENS=token1,token2  # For bearer mode (comma-separated)

# For JWT mode (gateway integration):
JWT_SIGNING_KEY=your-shared-secret-32chars-min
GATEWAY_BASE_URL=https://gateway.example.com
```

### Running Locally
```bash
# stdio mode (for MCP inspector/clients)
python -m domo_mcp

# Test with MCP inspector
npx @modelcontextprotocol/inspector python3 -m domo_mcp
```

### Testing
```bash
pytest                    # Run all tests
pytest tests/test_auth.py # Run specific test file
python test_connection.py # Test Domo API connection
```

## Deployment (Vercel)

```bash
npm run build -- --vercel     # Build for Vercel
vercel deploy --prod --prebuilt
```

Set environment variables in Vercel dashboard or CLI:
```bash
vercel env add DOMO_HOST production
vercel env add DOMO_DEVELOPER_TOKEN production
vercel env add MCP_AUTH_TOKENS production
```

## Issue Tracking (Beads)

This project uses **bd** (beads) for issue tracking.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Releasing New Versions

This project uses semantic versioning (v0.1.0, v0.2.0, v1.0.0, etc.).

**Version location:** `domo_mcp/__init__.py` contains `__version__`

**Release workflow:**

1. Update version in `domo_mcp/__init__.py`
2. Commit and push the version change
3. Create the GitHub release:
   ```bash
   gh release create v0.2.0 --repo wksusa/domo-fastmcp --title "v0.2.0" --notes "Release notes here"
   ```

**Important:** The `--repo wksusa/domo-fastmcp` flag is required because this repo has an `upstream` remote pointing to DomoApps/domo-mcp-server.

## Session Completion Checklist

**When ending a work session**, complete ALL steps. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** - Create beads issues for follow-up
2. **Run quality gates** (if code changed) - `pytest`
3. **Update issue status** - Close finished work
4. **Push to remote**:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Verify** - All changes committed AND pushed

**Rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- If push fails, resolve and retry until it succeeds
