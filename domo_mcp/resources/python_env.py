"""MCP resource describing the `run_python` sandbox runtime environment.

Read this resource at `python://env` to refresh the sandbox contract without
re-reading the `run_python` tool docstring.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ..code_executor import EXEC_TIMEOUT, MAX_CODE_LENGTH, MAX_OUTPUT_LENGTH

URI = "python://env"

_LIMITS = f"""\
- **Code size**: {MAX_CODE_LENGTH:,} characters max.
- **Output size**: {MAX_OUTPUT_LENGTH:,} characters max. Larger output is truncated — the
  response sets `truncated: true` and `original_length` reports the pre-truncation
  length so you know how much was dropped.
- **Execution time**: {EXEC_TIMEOUT:g} seconds per call. Beyond that you get an error with
  `error_type: "Timeout"`."""

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

### Pass `query_dataset` results directly

`query_dataset` returns a column-oriented payload (either
`{"columns": ["col1", ...], "rows": [[...], ...]}` or
`{"columns": [{"name": "col1", ...}, ...], "rows": [[...], ...]}`).

`run_python` **auto-reshapes** that payload into a list of row-dicts before
binding it to `data`, so you can pass the whole `query_dataset` result through
without converting it yourself. Inside `code`:

```python
df = pd.DataFrame(data)                # works
first_loc = data[0]["LocationDesc"]    # works
```

The `data_summary` in the response will reflect the reshaped form, e.g.
`"list of 141 items; sample keys: ['LocationDesc', 'Sales', ...]"`.

If you pass a raw list of lists (e.g. you sliced `result["rows"]` before the
call), `run_python` cannot infer column names — you'll get back a list of
positional lists. In that case pass the original payload instead, or pass a
list of row-dicts you built yourself.

## Limits

{limits}

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

_CONTENT = _CONTENT.replace("{limits}", _LIMITS)


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
