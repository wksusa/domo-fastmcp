"""FastMCP tool definitions mirroring domo_mcp/server_factory.py (metadata only).

Signatures and docstrings must stay aligned with the production server so
evals/agents/domo-mcp/tools.json stays accurate without importing Domo client
code or the code executor.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def build_metadata_mcp() -> FastMCP:
    """Build a FastMCP instance that exposes the Domo MCP tool schemas only."""
    mcp = FastMCP(name="domo-mcp")

    @mcp.tool()
    async def get_dataset_schema(dataset_id: str) -> str:
        """Get the schema of a Domo dataset.

        Args:
            dataset_id: The ID of the dataset to get the schema for.

        Returns:
            JSON string containing the dataset schema.
        """
        return ""

    @mcp.tool()
    async def get_dataset_metadata(dataset_id: str) -> str:
        """Get metadata for a Domo dataset.

        Args:
            dataset_id: The ID of the dataset to get metadata for.

        Returns:
            JSON string containing the dataset metadata.
        """
        return ""

    @mcp.tool()
    async def query_dataset(dataset_id: str, sql: str) -> str:
        """Query a Domo dataset using SQL.

        Args:
            dataset_id: The ID of the dataset to query.
            sql: The SQL query to execute on the dataset.

        Returns:
            JSON string containing the query results.
        """
        return ""

    @mcp.tool()
    async def search_datasets(query: str) -> str:
        """Search for datasets in a Domo instance by name.

        Note: Domo's search API does not PDP-filter results. JWT users see all
        datasets in search but get 403 or filtered rows when actually querying.

        Args:
            query: The search query to find datasets by name.

        Returns:
            JSON string containing matching datasets with their IDs and names.
        """
        return ""

    @mcp.tool()
    async def list_roles() -> str:
        """List all roles in the Domo instance.

        Returns:
            JSON string containing all roles in the Domo instance.
        """
        return ""

    @mcp.tool()
    async def create_role(name: str, from_role_id: int, description: str | None = None) -> str:
        """Create a new role in the Domo instance.

        Args:
            name: The name of the new role.
            from_role_id: The role ID to copy permissions from.
            description: Optional description of the role.

        Returns:
            JSON string containing the created role data.
        """
        return ""

    @mcp.tool()
    async def list_role_authorities(role_id: int) -> str:
        """List authorities (permissions) for a specific role in the Domo instance.

        Args:
            role_id: The ID of the role to list authorities for.

        Returns:
            JSON string containing the role's authorities.
        """
        return ""

    @mcp.tool()
    async def run_python(
        code: str,
        data: Annotated[
            list | dict | str | None,
            Field(
                description=(
                    "Input data, available in `code` as the `data` variable. "
                    "Preferred: pass a native list or dict (no JSON round-trip). "
                    "Also accepted: a JSON string (parsed before execution) or null."
                ),
            ),
        ] = None,
    ) -> str:
        """Execute Python code to compute analytics on data returned by query_dataset.

        Use this after fetching data with query_dataset when you need calculations
        that are more reliable in code than in your head: YoY change columns,
        percentage deltas, totals, averages, pivots, rankings, etc.

        Args:
            code: Python source to execute. Either `print()` values, or end with
                  a bare expression — its repr() is auto-printed REPL-style.
                  The following names are pre-bound and ready to use directly
                  (re-importing them is allowed but redundant):
                    - pd (pandas), np (numpy)
                    - json, math, statistics, collections, decimal, datetime, re
                  The `data` variable holds the parsed input. Imports of any
                  other module are blocked; no file, network, or OS access.
            data: Input data, available in code as `data`. Accepts a native
                  list/dict, or a JSON string (which will be parsed). Pass
                  nothing if `code` doesn't need input data.

        Returns:
            A JSON string with the same key set on success and error:
              ok, stdout, stderr, truncated, original_length, execution_ms,
              data_summary, plus error_type / error_message / line (null on
              success). Branch on `ok` before reading the rest.

        Note: `query_dataset` returns column-oriented data
        (`{columns, rows, ...}`). `run_python` **auto-reshapes** that payload
        into a list of row-dicts before binding it to `data`, so pass the
        whole `query_dataset` result through unchanged — `pd.DataFrame(data)`
        and `data[0]["col"]` both work. See the `python://env` resource for
        the full contract.

        Example 1 (pandas — pass the whole query_dataset result):
            code = '''
            df = pd.DataFrame(data)
            df["change"] = df["FY2025"] - df["FY2024"]
            df["change_pct"] = (df["change"] / df["FY2024"] * 100).round(1)
            print(df.to_string(index=False))
            '''
            data = {"columns": ["FiscalPrd", "FY2024", "FY2025"],
                    "rows": [[10, 2733551, 9895014], ...]}

        Example 2 (plain Python — same contract):
            code = '''
            counts = collections.Counter(row["category"] for row in data)
            for category, n in counts.most_common(5):
                print(f"{category}: {n}")
            '''
            data = {"columns": ["category", "n"],
                    "rows": [["A", 1], ["B", 2], ["A", 3]]}
        """
        return ""

    return mcp
