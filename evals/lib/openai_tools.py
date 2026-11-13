"""Convert FastMCP tool listings to OpenAI function-calling JSON."""

from __future__ import annotations

from typing import Any


def mcp_tool_to_openai(tool: Any) -> dict:
    params = getattr(tool, "parameters", None) or {}
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    elif not isinstance(params, dict):
        params = {}

    description = getattr(tool, "description", "") or ""
    name = getattr(tool, "name", "")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": params.get("type", "object"),
                "properties": params.get("properties", {}),
                "required": params.get("required", []),
                "additionalProperties": params.get("additionalProperties", False),
            },
        },
    }


async def export_openai_tools() -> list[dict]:
    """List tools from the lightweight metadata FastMCP surface."""
    from evals.lib.tool_surface import build_metadata_mcp

    mcp = build_metadata_mcp()
    tools = await mcp.list_tools()
    tools.sort(key=lambda t: t.name)
    return [mcp_tool_to_openai(t) for t in tools]
