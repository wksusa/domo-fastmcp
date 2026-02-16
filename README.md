# Domo MCP Server

A Model Context Protocol (MCP) server that connects to Domo API. This is an enhanced fork of [DomoApps/domo-mcp-server](https://github.com/DomoApps/domo-mcp-server) with OAuth authentication, JWT-based gateway integration, per-user dataset authorization (PDP), and Vercel deployment via FastMCP v3.

## Features

- Run SQL queries on Domo DataSets
- Search for DataSets by name
- Get the metadata of Domo DataSets
- Get the schema of Domo DataSets
- Manage roles and authorities

## Authentication Methods

This server supports two authentication methods:

| Method | Env Vars | API Access | Best For |
|--------|----------|------------|----------|
| **Developer Token** | `DOMO_DEVELOPER_TOKEN` + `DOMO_HOST` | Full (including internal APIs) | Personal use, full functionality |
| **OAuth Client Credentials** | `DOMO_CLIENT_ID` + `DOMO_CLIENT_SECRET` | Public API only | Server-to-server integrations |

### Developer Token (Recommended)

Developer Token authentication provides access to all Domo APIs, including internal endpoints like dataset search.

```bash
DOMO_DEVELOPER_TOKEN=<your_token>
DOMO_HOST=instance-name.domo.com  # No https:// prefix
```

[How to generate a Developer Token](https://domo-support.domo.com/s/article/360042934494?language=en_US)

### OAuth Client Credentials (Fallback)

OAuth authentication uses the public API at `api.domo.com`. Some features like search use client-side filtering instead of server-side search.

```bash
DOMO_CLIENT_ID=<your_client_id>
DOMO_CLIENT_SECRET=<your_client_secret>
```

## MCP Server Authentication Modes

The HTTP endpoint (Vercel deployment) supports three authentication modes, controlled by the `AUTH_MODE` environment variable:

| Mode | `AUTH_MODE` | Required Env Vars | Use Case |
|------|-------------|-------------------|----------|
| **Bearer Token** | `bearer` (default) | `MCP_AUTH_TOKENS` | Direct client access, existing setups |
| **JWT** | `jwt` | `JWT_SIGNING_KEY`, `GATEWAY_BASE_URL` | Gateway integration with per-user identity + PDP |
| **None** | `none` | — | Local development, testing |

**Upgrading from v0.1.x:** Existing deployments require no changes. `AUTH_MODE` defaults to `bearer`, which preserves the exact v0.1.x behavior.

**Bearer mode** validates tokens from the `Authorization: Bearer <token>` header against `MCP_AUTH_TOKENS`. This is the simplest setup for direct client access.

**JWT mode** validates JSON Web Tokens issued by an upstream gateway (e.g., [mcp-gateway](https://github.com/wksusa/mcp-gateway)). This enables per-user dataset authorization via [PDP](#personalized-data-permissions-pdp). The JWT must contain an `upstream_claims.email` or top-level `email` claim that maps to a Domo user account.

**None mode** disables MCP-level authentication entirely. Domo API authentication (Developer Token or OAuth) still applies. Suitable for local development with stdio mode.

## Prerequisites

- Python 3.11+ OR Docker
- Domo instance with developer access

## Setup

### Vercel Deployment (Remote MCP Server)

Deploy as a serverless MCP server on Vercel using FastMCP:

1. Fork/clone this repository
2. Install Vercel CLI: `npm i -g vercel`
3. Link to your Vercel project: `vercel link`
4. Set environment variables in Vercel:
   ```bash
   # Domo API Credentials (choose one):
   # Option 1: Developer Token (recommended)
   vercel env add DOMO_HOST production
   vercel env add DOMO_DEVELOPER_TOKEN production

   # Option 2: OAuth
   vercel env add DOMO_CLIENT_ID production
   vercel env add DOMO_CLIENT_SECRET production

   # MCP Server Authentication (choose one):

   # Option A: Bearer token (default, simplest)
   vercel env add MCP_AUTH_TOKENS production
   # Generate a secure token: python3 -c "import secrets; print(secrets.token_urlsafe(32))"

   # Option B: JWT (for gateway integration with per-user PDP)
   vercel env add AUTH_MODE production        # set to "jwt"
   vercel env add JWT_SIGNING_KEY production  # shared secret with gateway (32+ chars)
   vercel env add GATEWAY_BASE_URL production # gateway URL, must match JWT "iss" claim
   ```
5. Deploy:
   ```bash
   npm run build -- --vercel
   vercel deploy --prod --prebuilt
   ```

Your MCP server will be available at `https://your-project.vercel.app/api/mcp`

**Client Configuration (Claude Desktop, Cursor, etc.):**
```json
{
  "mcpServers": {
    "domo": {
      "type": "http",
      "url": "https://your-project.vercel.app/api/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-token-here"
      }
    }
  }
}
```

**Note:** If `AUTH_MODE` is not set, it defaults to `bearer`. If `MCP_AUTH_TOKENS` is also not set, authentication is disabled. See [MCP Server Authentication Modes](#mcp-server-authentication-modes) and [Security & Authentication](#security--authentication) for more details.

### Local Python Setup

1. Clone this repository
2. Navigate to the cloned directory
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file with your credentials:
   ```bash
   # Option 1: Developer Token
   DOMO_DEVELOPER_TOKEN=<your_token>
   DOMO_HOST=instance-name.domo.com

   # Option 2: OAuth
   DOMO_CLIENT_ID=<your_client_id>
   DOMO_CLIENT_SECRET=<your_client_secret>
   ```
5. Add configuration to your VS Code/Claude Desktop settings:
   ```json
   {
     "domo-mcp": {
       "type": "stdio",
       "command": "python",
       "args": ["-m", "domo_mcp"],
       "env": {
         "PYTHONPATH": "${workspaceFolder}",
         "DOMO_DEVELOPER_TOKEN": "<your_token>",
         "DOMO_HOST": "instance-name.domo.com"
       }
     }
   }
   ```

### Local Docker Setup

#### Option 1: Using Docker Compose (Recommended)

1. Clone this repository
2. Navigate to the cloned directory
3. Create a `.env` file with your Domo credentials:
   ```
   DOMO_DEVELOPER_TOKEN=<your_token>
   DOMO_HOST=instance-name.domo.com
   ```
4. Build and run with Docker Compose:
   ```bash
   docker-compose build
   docker-compose run --rm domo-mcp-server
   ```
5. For VS Code MCP configuration:
   ```json
   {
     "domo-mcp": {
       "command": "docker-compose",
       "args": ["run", "--rm", "domo-mcp-server"],
       "env": {
         "DOMO_DEVELOPER_TOKEN": "<your_token>",
         "DOMO_HOST": "instance-name.domo.com"
       }
     }
   }
   ```

#### Option 2: Using Docker directly

1. Build the Docker image:
   ```bash
   docker build -t domo-mcp-server .
   ```
2. Add configuration to your VS Code settings:
   ```json
   {
     "domo-mcp": {
       "command": "docker",
       "args": [
         "run", "-i",
         "-e", "DOMO_DEVELOPER_TOKEN",
         "-e", "DOMO_HOST",
         "domo-mcp-server"
       ],
       "env": {
         "DOMO_DEVELOPER_TOKEN": "<your_token>",
         "DOMO_HOST": "instance-name.domo.com"
       }
     }
   }
   ```

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `get_dataset_metadata(dataset_id)` | Get metadata for a DataSet |
| `get_dataset_schema(dataset_id)` | Get the schema for a DataSet |
| `query_dataset(dataset_id, sql)` | Query a DataSet with SQL |
| `search_datasets(query)` | Search for DataSets by name |
| `list_roles()` | List all roles in the Domo instance |
| `create_role(name, from_role_id, description?)` | Create a new role |
| `list_role_authorities(role_id)` | List authorities for a role |

## Personalized Data Permissions (PDP)

When using `AUTH_MODE=jwt`, the server enforces Domo's [Personalized Data Permissions](https://domo-support.domo.com/s/article/360043429693) at the MCP layer. This provides per-user dataset access control based on the authenticated user's identity.

**How it works:**

1. The JWT `email` claim is extracted from the access token
2. The email is resolved to a Domo user ID (cached for 1 hour)
3. Each dataset operation checks the user against that dataset's PDP policies
4. Users only see datasets and data they are authorized to access in Domo

**Which tools are affected:**

| Tool | PDP Behavior |
|------|-------------|
| `query_dataset` | Access check before query execution |
| `get_dataset_schema` | Access check before returning schema |
| `get_dataset_metadata` | Access check before returning metadata |
| `search_datasets` | Results filtered to accessible datasets only |
| `list_roles` | No PDP (admin operation) |
| `create_role` | No PDP (admin operation) |
| `list_role_authorities` | No PDP (admin operation) |

**When PDP is NOT enforced:**
- `AUTH_MODE=bearer` or `AUTH_MODE=none` — no user identity available, all datasets accessible
- stdio mode (local development) — no JWT context
- Datasets with PDP disabled in Domo — always accessible

**Common error messages:**
- `"Access denied"` — The user's Domo account doesn't have a PDP policy granting access to this dataset
- `"Your account is not linked to a Domo account"` — The JWT email doesn't match any Domo user

## Example Usage with LLMs

When used with LLMs that support the MCP protocol, this server enables natural language interaction with your Domo environment:

- "How many orders in my Example Sales dataset have critical priority?"
- "Who owns the Customer Invoice dataset?"
- "Show me the logs for the last 3 hours in my Activity Log dataset."
- "Search for datasets with 'sales' in the name"

## Testing

Test the MCP server using the inspector:

```bash
npx @modelcontextprotocol/inspector python3 -m domo_mcp
```

Or test the connection directly:

```bash
python test_connection.py
```

## Troubleshooting

### Authentication Errors

- **Developer Token**: Ensure `DOMO_HOST` doesn't include `https://` prefix
- **OAuth**: Verify your client ID/secret are correct and have necessary scopes
- Check that your token/credentials haven't expired

### Multiple Docker Instances

Clean up with the included script:

```bash
./cleanup-docker.sh
```

Or manually:

```bash
docker-compose down --remove-orphans
docker ps -a --filter "name=domo-mcp-server" --format "{{.ID}}" | xargs -r docker rm -f
```

### Search Returns No Results

- With **Developer Token**: Uses server-side search (fast, accurate)
- With **OAuth**: Uses client-side filtering of first 500 datasets (may miss some)

If using OAuth and not finding expected datasets, consider switching to Developer Token authentication.

### JWT Authentication Errors

- **"Invalid JWT signature"** — Ensure `JWT_SIGNING_KEY` matches the value configured in your gateway. Both sides must use the same shared secret.
- **"JWT issuer mismatch"** — `GATEWAY_BASE_URL` must match the `iss` claim in the JWT exactly (including `https://` and no trailing slash).
- **"Your account is not linked to a Domo account"** — The `email` claim in the JWT doesn't match any Domo user. Verify the email exists in your Domo instance.
- **"Access denied" on a dataset** — The user's Domo account doesn't have a PDP policy granting access to the requested dataset. Check the dataset's PDP configuration in Domo.

### Client Compatibility (n8n, etc.)

Some MCP clients send extra metadata fields with tool calls (e.g., `toolCallId`, `project_id`, `metadata`). This server automatically filters these extra fields, so it works out of the box with:

- **n8n** - AI Agent nodes with MCP tools
- **Custom integrations** - Any client that passes through extra context
- **Standard MCP clients** - Claude Desktop, VS Code, Cursor, etc.

No configuration needed—unknown parameters are silently ignored.

## Security & Authentication

### MCP Server Authentication (Vercel HTTP Endpoint)

The Vercel HTTP endpoint supports multiple authentication modes. See [MCP Server Authentication Modes](#mcp-server-authentication-modes) for an overview.

**Setting Up Authentication:**

1. **Generate a secure token:**
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Set the token in Vercel:**
   ```bash
   vercel env add MCP_AUTH_TOKENS production
   # Paste your generated token when prompted
   ```

3. **Update your MCP client configuration** to include the Authorization header:
   ```json
   {
     "mcpServers": {
       "domo": {
         "type": "http",
         "url": "https://your-project.vercel.app/api/mcp",
         "headers": {
           "Authorization": "Bearer your-token-here"
         }
       }
     }
   }
   ```

**Multiple Tokens (Zero-Downtime Rotation):**

You can configure multiple tokens for different clients or for token rotation:

```bash
# In Vercel, set MCP_AUTH_TOKENS with comma-separated tokens
MCP_AUTH_TOKENS=token1,token2,token3
```

To rotate tokens without downtime:
1. Add new token to the list: `old_token,new_token`
2. Deploy
3. Update clients to use new token
4. Remove old token: `new_token`
5. Deploy again

**Disabling Authentication:**

If `MCP_AUTH_TOKENS` is not set or empty, authentication is disabled and all requests are accepted. This is suitable for local development but **not recommended for production**.

**Local Development:**

Add to your `.env.local` file:
```bash
MCP_AUTH_TOKENS=local-dev-token-for-testing
```

#### JWT Authentication (Gateway Integration)

JWT mode is designed for use with an upstream gateway that authenticates users and forwards their identity via signed JWTs.

**Setup:**

1. **Set environment variables in Vercel:**
   ```bash
   vercel env add AUTH_MODE production        # set to "jwt"
   vercel env add JWT_SIGNING_KEY production  # shared secret with your gateway
   vercel env add GATEWAY_BASE_URL production # e.g., https://gateway.example.com
   ```

2. **How it works:**
   - The gateway signs JWTs with a shared secret (`JWT_SIGNING_KEY`) using HS256
   - The key is derived via HKDF from the shared secret (low-entropy material is acceptable)
   - The server validates the JWT signature, issuer (`GATEWAY_BASE_URL`), and expiration
   - The `email` claim (or `upstream_claims.email`) is used to resolve the user's Domo account
   - [PDP policies](#personalized-data-permissions-pdp) are enforced based on the resolved Domo user

3. **Required JWT claims:**
   - `iss` — Must match `GATEWAY_BASE_URL` exactly
   - `email` or `upstream_claims.email` — Must match a Domo user's email address

### Domo API Authentication

Your Domo credentials provide direct access to your instance:

- Secure your `.env` file and never commit it to version control
- For Vercel deployments, use environment variables (not checked into code)
- Use Developer Token for full API access, OAuth for limited server-to-server access
- Regularly rotate your tokens and credentials

### Best Practices

- **Production**: Always enable MCP authentication on Vercel deployments
- **Tokens**: Use cryptographically secure tokens (minimum 32 bytes of entropy)
- **HTTPS**: Vercel enforces HTTPS automatically - tokens are encrypted in transit
- **Access Control**: Consider restricting CORS origins in `api/mcp.py` for additional security
- **Monitoring**: Check Vercel logs for unauthorized access attempts

## Architecture

This fork uses [FastMCP v3](https://github.com/jlowin/fastmcp) for both server modes. All tools are defined once in `server_factory.py` and shared across modes:

- **stdio mode** (`python -m domo_mcp`) — For local use with VS Code, Claude Desktop, and MCP inspector
- **HTTP mode** (`api/mcp.py`) — For Vercel serverless deployment with Streamable HTTP transport

Both modes provide:
- Automatic tool discovery and schema generation
- Pydantic input validation on all tools
- PDP enforcement when JWT identity is available (HTTP/JWT mode only)

The HTTP mode additionally provides:
- Stateless HTTP transport for serverless environments
- CORS support for browser-based clients
- Multi-mode authentication (Bearer token or JWT)
