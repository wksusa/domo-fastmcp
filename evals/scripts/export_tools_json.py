#!/usr/bin/env python3
"""Export OpenAI-format tools.json from the FastMCP server (offline).

Uses stub Domo credentials when DOMO_DEVELOPER_TOKEN / DOMO_HOST are unset so
no live API calls are made. Regenerate after changing tools in server_factory.py:

    python3 evals/scripts/export_tools_json.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT = _REPO_ROOT / "evals" / "agents" / "domo-mcp" / "tools.json"


def _ensure_stub_domo_env() -> None:
    if not os.getenv("DOMO_DEVELOPER_TOKEN") and not (
        os.getenv("DOMO_CLIENT_ID") and os.getenv("DOMO_CLIENT_SECRET")
    ):
        os.environ.setdefault("DOMO_DEVELOPER_TOKEN", "eval-export-stub")
        os.environ.setdefault("DOMO_HOST", "example.domo.com")


def _mcp_tool_to_openai(tool) -> dict:
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


async def _export() -> list[dict]:
    _ensure_stub_domo_env()
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from domo_mcp.server_factory import create_server

    mcp = create_server(auth=None)
    tools = await mcp.list_tools()
    tools.sort(key=lambda t: t.name)
    return [_mcp_tool_to_openai(t) for t in tools]


def main() -> None:
    payload = asyncio.run(_export())
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload)} tools to {_OUTPUT.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
