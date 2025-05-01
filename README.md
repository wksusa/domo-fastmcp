# Domo MCP Server

A Model Context Protocol (MCP) server that connects to Domo API.

## Features

- Get metadata about Domo DataSets
- Run SQL queries on Domo DataSets

## Prerequisites

- Python 3.11+
- Domo instance with:
  - Developer access token
  - Access to datasets to query

## Setup

1. Clone this repository
1. Add this server as an MCP server in VS Code
   ```json
   {
     "name": "Domo MCP Server",
     "type": "stdio",
     "command": "python",
     "args": ["-m", "domo_mcp"],
     "env": {
       "PYTHONPATH": "${workspaceFolder}",
       "DOMO_DEVELOPER_TOKEN": "<your_domo_developer_token>",
       "DOMO_HOST": "<your_domo_host eg. instance-name.domo.com>"
     }
   }
   ```
1. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
1. Ensure the server is running

### Obtaining a Domo Developer Token

[Follow these steps](https://domo-support.domo.com/s/article/360042934494?language=en_US) to generate an access token.

## Running the Server

Start the MCP server:

```
python domo.py
```

You can test the MCP server using the inspector by running

```
npx @modelcontextprotocol/inspector python3 domo.py
```

## Available MCP Tools

The following MCP tools are available:

1. **get_dataset_metadata(dataset_id: str)** - Get metadata for a DataSet
2. **get_dataset_schema(dataset_id: str)** - Get the schema for a DataSet
3. **query_dataset(dataset_id: str, query: str)** - Query a DataSet with SQL
4. **search_datasets(query: str)** - Search for a DataSet by name to get its id

## Example Usage with LLMs

When used with LLMs that support the MCP protocol, this server enables natural language interaction with your Domo environment:

- "How many orders in my Example Sales dataset have critical priority?"
- "Who owns the Customer Invoice dataset?"
- "Show me the logs for the last 3 hours in my Activity Log dataset."

## Troubleshooting

### Connection Issues

- Ensure your Domo host is correct and doesn't include `https://` prefix
- Verify your personal access token has the necessary permissions and hasn't expired
- Run the included test script: `python test_connection.py`

## Security Considerations

- Your Domo developer token provides direct access to your instance
- Secure your `.env` file and never commit it to version control
- Run this server in a secure environment
