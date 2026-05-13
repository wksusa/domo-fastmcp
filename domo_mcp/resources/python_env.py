"""MCP resource describing the `run_python` sandbox runtime environment.

Read this resource at `python://env` to refresh the sandbox contract without
re-reading the `run_python` tool docstring.
"""

from __future__ import annotations

from fastmcp import FastMCP

URI = "python://env"

_CONTENT = """\
# `run_python` runtime environment

`run_python` executes Python in an isolated sandbox. This document is the
authoritative reference for what's available, what's blocked, and how output
is captured.

## Output rules — exec, not REPL

- `print()` writes to stdout. Whatever you print becomes the `stdout` field of
  the structured response.
- A bare expression on the **last line** is auto-printed REPL-style: its
  `repr()` is appended to stdout. `1 + 1` on its own line prints `2`.
- Statements (`x = 1`, function defs, loops with no `print`) do not auto-print.

## Response shape

Success:
```
{
  "ok": true,
  "stdout": "...",
  "stderr": "",
  "truncated": false,
  "original_length": 1234,
  "execution_ms": 42,
  "data_summary": "list of 480 items; sample keys: ['LocationDesc', 'AcctGrName']"
}
```

Error:
```
{
  "ok": false,
  "error_type": "KeyError",
  "error_message": "'foo'",
  "line": 7,
  "stdout": "...partial output before the error...",
  "execution_ms": 5
}
```

## Pre-bound names

These names are already in scope — **use them directly, do not `import`** them:

| Name | What it is |
|------|------------|
| `data` | The pre-parsed input (see "The `data` variable" below). |
| `pd` | pandas |
| `np` | numpy |
| `json`, `math`, `statistics`, `collections`, `decimal` | stdlib modules |
| `datetime`, `re` | stdlib modules |

If you do write `import pandas as pd` (etc.) for any of these modules, the
sandbox will allow it — it's redundant but not an error.

## The `data` variable

The `data` parameter to `run_python` accepts either:

- A native list or dict (preferred — no JSON round-trip).
- A JSON string (back-compat — will be parsed).
- `null` / omitted (then `data` is `None` inside your code).

When `data` is non-empty, the response includes a `data_summary` field that
describes its shape (e.g., `"list of 480 items; sample keys: ['x', 'y']"`).

## Limits

- **Code size**: 8,000 characters max.
- **Output size**: 20,000 characters max. Larger output is truncated — the
  response sets `truncated: true` and `original_length` reports the pre-truncation
  length so you know how much was dropped.
- **Execution time**: 15 seconds per call. Beyond that you get an error with
  `error_type: "Timeout"`.

## What's blocked

- File system: `open`, `pathlib`, etc. are unavailable.
- Network: no `urllib`, `requests`, `socket`, `httpx`, etc.
- OS / shell: no `os`, `sys`, `subprocess`, `shutil`.
- Imports of any module **outside the allowlist above** raise
  `ImportError: import of 'X' is not allowed in sandbox`.
- The `__builtins__` table is locked to a small whitelist; introspection-heavy
  helpers (`eval`, `exec`, `compile`, `open`, `input`, `__import__` of unsafe
  modules) are not exposed.

## Example: pandas

```python
df = pd.DataFrame(data)
df["change"] = df["FY2025"] - df["FY2024"]
print(df.to_string(index=False))
```

## Example: plain Python

```python
counts = collections.Counter(row["category"] for row in data)
for category, n in counts.most_common(5):
    print(f"{category}: {n}")
```
"""


def register(mcp: FastMCP) -> None:
    """Register the python_env resource with the given FastMCP server."""

    @mcp.resource(
        uri=URI,
        name="python_env",
        description=(
            "Python runtime environment for the run_python tool: available "
            "modules, the data contract, output rules, limits, and what's blocked."
        ),
        mime_type="text/markdown",
    )
    def python_env() -> str:  # pragma: no cover — exercised via MCP machinery
        return _CONTENT
