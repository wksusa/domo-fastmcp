#!/usr/bin/env python3
"""Export OpenAI-format tools.json from the FastMCP tool surface (offline).

Uses a lightweight metadata-only FastMCP mirror under evals/lib (no Domo client,
no code executor, no network). Regenerate after changing tools in server_factory.py:

    python3 evals/scripts/export_tools_json.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT = _REPO_ROOT / "evals" / "agents" / "domo-mcp" / "tools.json"


async def _export() -> list[dict]:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from evals.lib.openai_tools import export_openai_tools

    return await export_openai_tools()


def main() -> None:
    payload = asyncio.run(_export())
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload)} tools to {_OUTPUT.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
