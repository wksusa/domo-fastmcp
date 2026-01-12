# Domo MCP Server

A Model Context Protocol (MCP) server that connects to Domo API. This is an enhanced fork of [DomoApps/domo-mcp-server](https://github.com/DomoApps/domo-mcp-server) with added support for OAuth authentication and Vercel deployment via FastMCP.

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

   # MCP Server Authentication (recommended for production)
   # Generate a secure token first:
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   # Then set it:
   vercel env add MCP_AUTH_TOKENS production
   ```
5. Deploy:
   ```bash
   vercel deploy --prod
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

**Note:** If you don't set `MCP_AUTH_TOKENS`, authentication is disabled. See [Security & Authentication](#security--authentication) for more details.

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

## Security & Authentication

### MCP Server Authentication (Vercel HTTP Endpoint)

The Vercel HTTP endpoint supports Bearer token authentication to secure access to the MCP server. This prevents unauthorized users from calling your MCP tools.

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

This fork uses [FastMCP](https://github.com/jlowin/fastmcp) for the Vercel deployment, providing:

- Stateless HTTP transport for serverless environments
- CORS support for browser-based clients
- Automatic tool discovery and schema generation

The local stdio server uses the original MCP implementation for compatibility with VS Code and other stdio-based clients.
