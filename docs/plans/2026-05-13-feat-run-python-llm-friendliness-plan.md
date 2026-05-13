---
title: "feat: Make run_python tool maximally LLM-friendly"
type: feat
status: active
date: 2026-05-13
---

# Make run_python Maximally LLM-Friendly

## Overview

The `run_python` MCP tool in domo-fastmcp executes Python code in a restricted sandbox. Recent debugging surfaced a string of small ergonomic gotchas that cause LLM-generated code to fail in ways the LLM can't recover from: imports of pre-bound modules raise cryptic errors, the sandbox is missing common builtins like `__build_class__`, error messages omit line numbers, output truncation is silent, and the bare-string return shape forces LLMs to do string-prefix matching to detect errors. This plan implements 12 targeted improvements grouped into five coherent units: ergonomic wins in `execute()`, sandbox completeness, a structured tool response, an updated docstring, and a new MCP resource that documents the runtime environment.

## Problem Frame

`run_python` is the analytics layer behind `query_dataset`. When the LLM needs to compute YoY deltas, pivots, rankings, or anything more involved than a SQL aggregation, it writes Python that runs in our sandbox. Every avoidable failure mode in that sandbox costs an extra tool round-trip — sometimes several — and burns context window on confusing error strings. The current tool has accumulated these:

- **Hidden namespace contract.** `pd`, `json`, etc. are pre-bound but the LLM doesn't know it, so it writes `import pandas as pd` and is then surprised when the sandbox accepts that (post our recent fix) or rejects other plausible imports like `numpy`, `datetime`, `re`.
- **Missing builtins.** `class Foo: pass` fails with `NameError: __build_class__`. `chr`, `ord`, `bytes` are absent. None of these expand the attack surface.
- **Opaque errors.** `Error: KeyError: 'foo'` — no line number, no traceback. The LLM has to guess where the error came from.
- **Silent failures.** Forgetting `print()` yields `"(no output)"`. Output >20K is truncated with a one-line message but no structured signal. The LLM can't reliably distinguish "code ran and produced nothing meaningful" from "code never ran" from "code ran but I'm seeing only the first 20K of output."
- **Stringly-typed response.** The tool returns a plain string with `"Error:"` prefixes. LLMs must string-match to detect errors. Future tools that want to chain on `run_python` output have nothing structured to consume.
- **Forced JSON round-trip for `data`.** If the caller already has the list/dict in hand, they must serialize to JSON for the tool to immediately deserialize.
- **No discoverability surface.** The LLM can only learn the sandbox contract by reading the tool's docstring at registration time. There is no MCP resource the LLM can re-read mid-conversation if it forgets.

This plan implements all 12 improvements identified in conversation as one cohesive change.

## Requirements Trace

Each requirement maps to one of the 12 improvements agreed in conversation.

**Ergonomic wins:**
- **R1.** Empty stdout returns an explanatory hint that names `print()` and explains exec-vs-REPL semantics.
- **R2.** A bare expression on the last line is auto-printed REPL-style (its `repr()` goes to stdout).
- **R3.** Exceptions report the line number from the user's code (`tb_lineno` on the relevant traceback frame).
- **R4.** Output truncation is surfaced as a structured flag with the original length, not just an inline message.

**Sandbox completeness:**
- **R5.** `numpy`, `datetime`, and `re` are pre-bound in the namespace and added to `_ALLOWED_IMPORTS`.
- **R6.** `__build_class__` is in `_SAFE_BUILTINS` so `class` statements work.
- **R7.** Add `chr`, `ord`, `bin`, `hex`, `oct`, `complex`, `bytes`, `bytearray`, `slice` to `_SAFE_BUILTINS`.

**Tool surface:**
- **R8.** `run_python` returns a structured JSON payload (`{ok, stdout, stderr, truncated, original_length, execution_ms}` on success; `{ok: false, error_type, error_message, line}` on error) instead of a bare string.
- **R9.** When `data` is non-empty, the response includes a `data_summary` field describing its type, length, and sample keys.
- **R10.** The tool's `data` parameter accepts either a JSON string (current behavior) or a native list/dict.

**Discoverability:**
- **R11.** A new MCP resource (`python://env`) documents the runtime environment: available modules, the `data` variable contract, the print-only output rule, builtin allowlist, and limits.
- **R12.** The tool docstring includes two examples: one using pandas, one using plain-Python aggregation.

## Scope Boundaries

- **Not changing the sandbox security model.** No new module categories beyond the listed additions. No file/network/OS access. The whitelist approach stays.
- **Not changing the threading model.** Still a `ThreadPoolExecutor` with `max_workers=2` and a 15s timeout per call.
- **Not changing the 8K code-length or 15s timeout limits.** If those need tuning, that's a separate discussion.
- **Not adding pyproject.toml or migrating to uv.** This project uses `requirements.txt`; out of scope.
- **`run_python` is the only tool affected.** Other tools (`query_dataset`, `search_datasets`, etc.) are not touched here — they have a separate brainstorm (`docs/brainstorms/2026-04-24-agent-effectiveness-and-reliability-brainstorm.md`) that explicitly carves `run_python` out.

### Deferred to Separate Tasks

- **Tool response curation for the rest of the server** — covered by the agent-effectiveness brainstorm and its follow-up plan.
- **Adding `pandas`/`numpy` to a future `pyproject.toml`** — the project uses `requirements.txt` and both packages are already listed (numpy transitively via pandas). If a `pyproject.toml` is added later, parity with `requirements.txt` should be enforced there.

## Context & Research

### Relevant Code and Patterns

- `domo_mcp/code_executor.py` — sandbox definition (`_SAFE_BUILTINS`, `_ALLOWED_IMPORTS`, `_safe_import`, `_run_in_thread`, `execute`). All sandbox-level changes land here.
- `domo_mcp/server_factory.py:478` — the `@mcp.tool() async def run_python(...)` definition. All tool-surface changes land here.
- `tests/conftest.py` — pytest fixtures live here. New `tests/test_code_executor.py` should follow the conventions of existing test modules.
- `tests/test_request_filter.py` — example of a unit-test module in this repo; mirror its style.
- No existing MCP resource implementations in `domo_mcp/`. A grep for `@mcp.resource` returned zero matches. This plan introduces the first resource and establishes the pattern (`domo_mcp/resources/python_env.py` under a new `domo_mcp/resources/` package), registered from `server_factory.py` similar to how tools are registered today.

### Institutional Learnings

- **The sandbox already pre-binds modules into the namespace and additionally allows imports of the same set** (post our recent `_safe_import` fix). This dual surface is intentional: pre-binding handles the common case, `_safe_import` handles LLMs that write `import` anyway. The new modules (`numpy`, `datetime`, `re`) follow the same dual pattern.
- **The Vercel runtime uses `requirements.txt`, not `pyproject.toml`.** Both `pandas` and `numpy` are already importable in production (numpy as a pandas transitive dep). The local-dev venv may lack one or both, so tests must skip gracefully when a module isn't installed, mirroring the existing pandas-availability check in `_run_in_thread`.
- **FastMCP tools return string content by default.** Returning a JSON string is well-supported — the LLM sees JSON text, which is more useful than prose-with-prefix because clients can `json.loads` it and the LLM can branch on `ok` cleanly.
- **Brainstorm context:** `docs/brainstorms/2026-04-24-agent-effectiveness-and-reliability-brainstorm.md` says "`run_python` is unchanged" (scope boundary, line 49). This plan intentionally departs from that boundary because the recent debugging session surfaced concrete failures that the brainstorm didn't anticipate. Documented as a Key Decision below.

### External References

- Python `ast` module — used for compile-and-auto-print-last-expression (R2). The pattern is: parse the source with `ast.parse(...)`, separate the last node, compile the prefix as `"exec"` and the last node (if `ast.Expr`) as `"eval"`, then `exec` then `eval`+`print(repr(...))`. Standard REPL technique.
- Python `traceback` module — `tb_lineno` on the relevant traceback frame for R3.

## Key Technical Decisions

- **Structured JSON is a controlled break with the current string-return shape.** The current consumers of `run_python` output are LLM clients that parse text. Returning a JSON string preserves the MCP text-content contract, and is *more* useful to LLMs than the current prose-with-prefix format because they can `json.loads()` and branch on `ok`. We are not adding an opt-in `structured=true` parameter — that would force two code paths and the migration cost is near zero. Documented as a "behavior change" in the README / release notes.
- **`data_summary` lives in the structured response, not in stdout.** Originally we considered prepending a `# data: ...` comment to stdout. That pollutes the output the LLM is trying to read. Instead, `execute()` computes a summary and surfaces it as a top-level field. Suppressible by passing an empty `data` value.
- **Auto-print only for bare expressions, not for statements.** REPL semantics: `1 + 1` on the last line prints `2`; `x = 1 + 1` on the last line prints nothing. Implemented by checking `isinstance(last_node, ast.Expr)` after parsing.
- **Line numbers come from `tb_lineno` of the user's frame, not the full traceback string.** Returning a full traceback would leak sandbox internals and waste context. Just the line number is enough for the LLM to find its mistake.
- **The new MCP resource is a *resource*, not a tool.** The LLM doesn't *call* `python_env`; it *reads* it. Resources are the right MCP primitive for "fetch the env description on demand." We introduce a `domo_mcp/resources/` package even though only one resource exists today, mirroring the convention referenced in `.claude/rules/mcp-conventions.md`.
- **Departure from the agent-effectiveness brainstorm's "`run_python` is unchanged" boundary** is intentional and limited. The brainstorm's scope was tool-response curation for the Domo API tools. This plan addresses a different problem (sandbox ergonomics) that surfaced after that brainstorm was written. The brainstorm's other work is unaffected.

## Open Questions

### Resolved During Planning

- **Q: Should `data_summary` go in stdout or as a structured field?** Resolved: structured field, so it doesn't pollute user output.
- **Q: Should the structured response change be opt-in?** Resolved: no — the migration cost is near zero and dual code paths are net-negative.
- **Q: Where does the new MCP resource live?** Resolved: new `domo_mcp/resources/` package, file `python_env.py`. Establishes the convention referenced in `.claude/rules/mcp-conventions.md`.
- **Q: Should we add a full traceback to error responses?** Resolved: no — `error_type`, `error_message`, and `line` are enough; full tracebacks leak sandbox internals and waste context.

### Deferred to Implementation

- **Exact phrasing of the "no output" hint.** Should mention `print()`, mention that bare expressions are now auto-printed, and clarify exec-vs-REPL. Final wording chosen during implementation; verified against test expectations.
- **Exact data-summary schema.** For `list[dict]`: `type`, `length`, sample of keys from the first row. For `dict`: `type`, key count, sample keys. For `list[scalar]`: `type`, `length`, type of the first element. For other types: `type`, `repr` truncated to 80 chars. Detailed shape pinned during implementation.
- **MCP resource URI scheme.** Likely `python://env` or `domo://python-env`. Decided during implementation based on what FastMCP's resource URI conventions prefer.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

The shape of the post-change tool response (success and error cases):

```
SUCCESS:
{
  "ok": true,
  "stdout": "...",
  "stderr": "",
  "truncated": false,
  "original_length": 1234,
  "execution_ms": 42,
  "data_summary": "list of 480 items; sample keys: ['LocationDesc', 'AcctGrName', 'total_amt']"  // omitted if no data
}

ERROR:
{
  "ok": false,
  "error_type": "KeyError",
  "error_message": "'foo'",
  "line": 7,
  "stdout": "...partial output before the error, if any...",
  "execution_ms": 5
}
```

Internal data flow:

```
run_python(code, data)
  │
  ├─ if data is str: data = json.loads(data)        # accept native or JSON (R10)
  ├─ elif data is None/empty: data = None
  │
  └─ execute(code, data) -> dict                    # structured result, not string
        │
        ├─ ast.parse(code), split last node
        ├─ exec(prefix), eval(last_expr) if Expr    # auto-print last expr (R2)
        ├─ capture stdout/stderr
        ├─ on exception: walk tb for user frame,
        │   extract line number (R3)
        ├─ if len(stdout) > MAX_OUTPUT_LENGTH:
        │     truncated=True, original_length=...   # structured (R4)
        ├─ compute data_summary if data           (R9)
        └─ return dict

run_python serializes dict to JSON string         (R8)
```

## Implementation Units

- [ ] **Unit 1: Sandbox namespace and builtins completeness**

**Goal:** Make the sandbox accept common analytics-adjacent code patterns without surprises: `numpy`, `datetime`, `re`, `class` definitions, and the missing arithmetic-related builtins.

**Requirements:** R5, R6, R7

**Dependencies:** None.

**Files:**
- Modify: `domo_mcp/code_executor.py`
- Test: `tests/test_code_executor.py` (new file)

**Approach:**
- Extend `_ALLOWED_IMPORTS` to include `numpy`, `datetime`, `re`.
- Add `numpy as np`, `datetime`, `re` to the pre-bound namespace in `_run_in_thread`. Use the same `try/except ImportError` pattern that pandas already uses, so a missing optional dep doesn't break the module load.
- Add `__build_class__` to `_SAFE_BUILTINS` (sourced from `builtins.__build_class__`).
- Add `chr`, `ord`, `bin`, `hex`, `oct`, `complex`, `bytes`, `bytearray`, `slice` to `_SAFE_BUILTINS`.
- Verify nothing in the additions opens file/network/OS access; all are pure data transforms.

**Patterns to follow:**
- The existing `try: import pandas as pd / except ImportError` block in `_run_in_thread` (`domo_mcp/code_executor.py:102-106`).
- The existing dual-surface convention: pre-bind in namespace **and** allow in `_ALLOWED_IMPORTS`.

**Test scenarios:**
- Happy path: `import numpy as np; print(np.array([1,2,3]).sum())` → output `"6"`. Skip if numpy not installed locally.
- Happy path: `import datetime; print(datetime.date(2026,1,1).isoformat())` → `"2026-01-01"`.
- Happy path: `import re; print(re.search('foo', 'foobar').group())` → `"foo"`.
- Happy path: `class Foo:\n    x = 1\nprint(Foo().x)` → `"1"`.
- Happy path: `print(chr(65), bin(5), bytes([1,2,3]))` → `"A 0b101 b'\\x01\\x02\\x03'"`.
- Edge case: `from datetime import timedelta; print(timedelta(days=1))` (submodule access) → `"1 day, 0:00:00"`.
- Error path: `import os` → result is an error mentioning `"not allowed in sandbox"` (regression guard).
- Error path: `import subprocess` → error (regression guard).
- Error path: `import urllib.request` → error (regression guard).

**Verification:**
- All listed test scenarios pass.
- `domo_mcp/code_executor.py` still has zero references to `os`, `sys`, `subprocess`, `socket`, `urllib`, `open` outside the allowed-imports list (security regression guard).

---

- [ ] **Unit 2: `execute()` result enrichment — line numbers, last-expr auto-print, structured truncation, data summary, "no output" hint**

**Goal:** Move `execute()` from returning a bare string to returning a structured dict that captures everything callers need to render a high-fidelity response. Land all `execute()`-side ergonomic wins together because they share the same `_run_in_thread` rewrite.

**Requirements:** R1, R2, R3, R4, R9

**Dependencies:** None. (Can be developed in parallel with Unit 1 — they touch different parts of `code_executor.py`.)

**Files:**
- Modify: `domo_mcp/code_executor.py`
- Test: `tests/test_code_executor.py`

**Approach:**
- Change `execute()` (and `_run_in_thread`) to return a `dict` with fields: `ok`, `stdout`, `stderr`, `truncated`, `original_length`, `execution_ms`, `error_type`, `error_message`, `line`, `data_summary`. Successful runs populate the success fields and omit the error fields; failures do the inverse. Keep the function name `execute` — only its return type changes.
- **Auto-print last expression (R2):** Parse `code` with `ast.parse`. If the last top-level node is an `ast.Expr`, separate it from the rest. Compile the prefix as `"exec"` and the last node as `"eval"`. Run the prefix, then `result = eval(last)`, then `print(repr(result))` into the same stdout buffer (unless the result is `None`, in which case skip the print to match REPL behavior). Fall back to the current full-`exec` path on `SyntaxError` so we don't make failure cases worse.
- **Line numbers (R3):** Catch the exception, walk the traceback (`exc.__traceback__`) to the deepest frame whose `co_filename == "<analyst>"`, take `tb_lineno`. If no analyst frame exists (compile-time error), use `SyntaxError.lineno`.
- **Structured truncation (R4):** After capturing stdout, set `original_length = len(stdout)`. If it exceeds `MAX_OUTPUT_LENGTH`, set `truncated = True` and slice. Drop the inline `"... (output truncated at N chars)"` suffix — clients have the structured signal now.
- **Data summary (R9):** Compute a short summary string from `data`:
  - `list` of dicts → `"list of N items; sample keys: [...]"` (first 5 keys of first item)
  - `list` of scalars → `"list of N items; element type: <type>"`
  - `dict` → `"dict with N keys; sample keys: [...]"`
  - other → `"<type>: <repr truncated to 80 chars>"`
  - `None`/empty → field omitted.
- **"No output" hint (R1):** When `stdout` is empty *and* there was no error, replace with a hint string: `"(no output — exec(), not a REPL. Use print() to emit values; a bare expression on the last line is auto-printed.)"`. Auto-print (R2) will eliminate this in most real cases.
- **Execution time:** `execution_ms = int((time.monotonic() - start) * 1000)` around the exec call.

**Execution note:** Test-first for the auto-print and line-number behaviors — both are easy to get subtly wrong (e.g., printing `None`, off-by-one line numbers from the `ast` split).

**Patterns to follow:**
- The current `_run_in_thread` shape — keep the `contextlib.redirect_stdout/stderr` blocks; only change what's inside and what's returned.
- The existing return-from-thread-pool pattern in `execute()`.

**Test scenarios:**
- Happy path: `print('hello')` → `{ok: True, stdout: "hello\n", truncated: False, ...}`.
- Happy path (auto-print): `1 + 1` (single line) → `stdout == "2\n"`.
- Happy path (auto-print, multi-line): `"x = 5\nx * 2"` → `stdout == "10\n"`.
- Edge case (no auto-print for statements): `x = 5` → `stdout` is the "no output" hint.
- Edge case (no auto-print for None): `"print('a')\nNone"` → `stdout == "a\n"` (no extra `None\n`).
- Edge case: empty code `""` → no error, "no output" hint.
- Error path: `1/0` (single line) → `{ok: False, error_type: "ZeroDivisionError", line: 1, ...}`.
- Error path (multi-line): `"x = 1\ny = 2\n1/0"` → `line == 3`.
- Error path (SyntaxError): `"def foo("` → `{ok: False, error_type: "SyntaxError", line: 1, ...}`.
- Edge case (truncation): code that prints 30K chars → `{truncated: True, original_length: ~30000, stdout: len 20000}`.
- Happy path (data_summary, list of dicts): `data=[{"a":1},{"a":2}]` → `data_summary` mentions `"list of 2 items"` and `"['a']"`.
- Happy path (data_summary, list of scalars): `data=[1,2,3]` → `data_summary` mentions `"list of 3 items"`.
- Happy path (data_summary, dict): `data={"a":1,"b":2}` → `data_summary` mentions `"dict with 2 keys"`.
- Edge case (no data_summary): `data=None` → key omitted from result dict.
- Error path (timeout): code with `while True: pass` → `{ok: False, error_type: "Timeout", error_message: "..."}` (current timeout path now returns dict instead of string).

**Verification:**
- All scenarios pass.
- The `execute()` callers in the codebase (only `server_factory.py:run_python` today) compile and route through Unit 3.
- No traceback strings appear in the structured response (security/info-leak regression guard).

---

- [ ] **Unit 3: `run_python` tool surface — structured JSON response and dual-typed `data` parameter**

**Goal:** Surface the new structured `execute()` result through the MCP tool, and let callers pass `data` as either a JSON string (current behavior) or a native list/dict.

**Requirements:** R8, R10

**Dependencies:** Unit 2.

**Files:**
- Modify: `domo_mcp/server_factory.py` (the `run_python` function body)
- Test: `tests/test_code_executor.py` (add an integration-style block that drives `run_python` end-to-end without spinning up an MCP server — call the closed-over function directly, or factor the body into a helper)

**Approach:**
- Change the `data: str = ""` parameter to accept `str | list | dict | None`. FastMCP's tool-schema generator will need to accept the union — verify that `Union[str, list, dict]` is supported. If not, fall back to `data: object = None` and inspect at runtime.
- Parse logic:
  - `None` or empty string → `parsed_data = None`
  - `str` → `json.loads(data)`; on `JSONDecodeError`, return error JSON immediately
  - `list` or `dict` → use as-is
  - anything else → return error JSON
- Call `execute(code, parsed_data)` to get the structured dict.
- Serialize the dict to a JSON string with `json.dumps(result)` (no `indent` — keep it compact for token economy).
- Return that string. The MCP layer sees text content; the LLM client parses JSON.
- Preserve the existing structured-log lines (`run_python: executing N chars`, `output length=N`) but route `output length` off the new `original_length` field.

**Patterns to follow:**
- The compact-JSON convention from the agent-effectiveness brainstorm (R4 in that doc): no `indent=2`.
- The existing `StructuredLoggingMiddleware` wiring — don't change it; logs continue to flow through `_ToolNameLoggingMiddleware`.

**Test scenarios:**
- Happy path: `run_python(code='print("hi")')` → JSON string with `{"ok": true, "stdout": "hi\n", ...}` (parseable via `json.loads`).
- Happy path (native list): `run_python(code='print(len(data))', data=[1,2,3])` → `{"ok": true, "stdout": "3\n", "data_summary": ...}`.
- Happy path (JSON string back-compat): `run_python(code='print(len(data))', data='[1,2,3]')` → identical output.
- Happy path (native dict): `data={"a":1,"b":2}` → `data_summary` present, code can read `data["a"]`.
- Edge case: `data=""` or omitted → no `data_summary`, `data` is `None` in code.
- Error path: `run_python(code='1/0')` → JSON with `{"ok": false, "error_type": "ZeroDivisionError", "line": 1}`.
- Error path (invalid JSON in string `data`): `data='{not valid'` → JSON with `{"ok": false, "error_type": "JSONDecodeError", ...}`.
- Edge case (unsupported `data` type): `data=42` → error JSON, doesn't crash.
- Integration: stdout shows up in the structured log line via `original_length` (verify via `caplog`).

**Verification:**
- All scenarios pass.
- `tests/test_request_filter.py` still passes (`run_python` is in the `TOOL_PARAMETERS` allowlist, signature change shouldn't break it — confirm).
- Manual smoke: hit the tool over MCP from `mcp_inspector` or a `curl`-driven `tools/call` invocation; verify the response is a JSON-parsable string.

---

- [ ] **Unit 4: Tool docstring — two examples, structured-response shape, explicit guidance**

**Goal:** Update the `run_python` docstring so the LLM understands the new structured response and sees one pandas-style example and one plain-Python aggregation example.

**Requirements:** R12 (and implicitly documents R8/R10 in the docstring text)

**Dependencies:** Unit 3.

**Files:**
- Modify: `domo_mcp/server_factory.py` (docstring on `run_python`)

**Approach:**
- Keep the existing `Args` and `Returns` sections, but:
  - Update `Returns` to describe the structured JSON shape (success and error fields).
  - Expand `Args.data` to note both supported forms: native list/dict or JSON string.
  - Keep the existing "Available names: pd, json, math, statistics, collections, decimal" list and add `np` (numpy), `datetime`, `re`.
  - Keep the "do not import unnecessarily" guidance from the prior fix.
- Replace the single example with two:
  - **Example 1 (pandas):** the existing `pd.DataFrame(data)` example, minus the bogus `import json` line.
  - **Example 2 (plain Python):** a small aggregation using `collections.Counter` and a list comprehension over `data`, no pandas. Demonstrates that the tool is useful for non-DataFrame work.
- Add one short line: "See the `python://env` resource for the full runtime environment listing."

**Patterns to follow:**
- The current docstring's tone — short paragraphs, indented code blocks.

**Test scenarios:**
- Test expectation: none for behavior — this unit is documentation only.
- **Doc verification (manual or automated):** Both code blocks in the docstring should execute cleanly through `execute()`. Add a docstring-validation test that extracts the two example code blocks via regex and runs them through `execute()` to confirm they don't raise. This catches docstring drift over time.

**Verification:**
- Docstring renders cleanly when introspected (`run_python.__doc__`).
- Both example snippets execute through `execute()` with `ok: true`.

---

- [ ] **Unit 5: `python_env` MCP resource — runtime environment documentation**

**Goal:** Introduce an MCP resource the LLM can read on demand to refresh its understanding of the sandbox: available modules, the `data` variable contract, the print-only-plus-auto-print output rule, the builtin allowlist, and the limits (8K code, 20K output, 15s timeout).

**Requirements:** R11

**Dependencies:** Units 1, 2, 3 (the resource describes the post-change behavior).

**Files:**
- Create: `domo_mcp/resources/__init__.py` (empty package marker)
- Create: `domo_mcp/resources/python_env.py` (resource definition)
- Modify: `domo_mcp/server_factory.py` (register the resource alongside tools)
- Test: `tests/test_python_env_resource.py` (new file)

**Approach:**
- Define a `register(mcp)` function in `domo_mcp/resources/python_env.py` that calls `@mcp.resource(uri=..., name="python_env", description=...)` on a function returning a markdown-formatted string.
- URI: `python://env` (pinned during implementation if FastMCP requires a different scheme).
- The resource content is a multi-section markdown string with:
  1. **Overview** — what `run_python` is for, exec-not-REPL, auto-print-last-expr behavior.
  2. **Pre-bound names** — `data`, `pd`, `np`, `json`, `math`, `statistics`, `collections`, `decimal`, `datetime`, `re`. Note that explicit imports of the same modules also work.
  3. **`data` contract** — accepted forms, what `data_summary` will look like, shape of the pre-parsed value.
  4. **Output** — `print()` writes to stdout; bare expression on last line is auto-printed; full response is structured JSON with `{ok, stdout, ...}`.
  5. **Limits** — 8K code, 20K output (with `truncated`/`original_length`), 15s timeout.
  6. **What's blocked** — file, network, OS, `subprocess`, non-allowlisted imports.
- Build the content as a module-level string literal so it doesn't need any runtime computation (no need to introspect `_SAFE_BUILTINS` on every read — those are stable).
- Call `register(mcp)` from `server_factory.py` near where the tools are registered.

**Patterns to follow:**
- No in-repo precedent. Mirror the FastMCP 3.0 `@mcp.resource` convention. Reference: `.claude/rules/mcp-conventions.md` mentions `ResourcesAsTools` in `wks-mcp` — review that pattern if FastMCP's resource API is ambiguous.

**Test scenarios:**
- Happy path: After `register(mcp)`, calling `mcp._resource_manager.get_resource("python://env")` (or whatever the FastMCP 3.0 introspection API is) returns the resource and its content includes the substring `"data"`, `"pd"`, `"np"`, `"datetime"`, `"re"`, `"print()"`, `"8,000"`, `"20,000"`, `"15s"`.
- Happy path: Resource description (visible in `resources/list`) is non-empty and mentions "Python runtime environment."
- Edge case: Content is valid markdown (no broken code-fence pairs, no unbalanced backticks). Verified with a simple regex or markdown-parser sanity check.
- Integration: `tools/list` and `resources/list` both succeed after registration (regression guard — confirm we didn't break the server bootstrap).

**Verification:**
- All scenarios pass.
- Manual smoke: `curl` an MCP `resources/list` against a local dev server and confirm `python://env` appears with the right description.
- Manual smoke: `resources/read` returns the markdown content.

## System-Wide Impact

- **Interaction graph:** `run_python` is called by LLM clients (Claude, MCP inspector). No internal callers chain off its output today — the structured response is a forward-compatible upgrade for future tool chaining.
- **Error propagation:** Errors now flow through structured JSON instead of `"Error:"`-prefixed strings. The MCP middleware (`_ToolNameLoggingMiddleware`) is unaffected — it logs at the message envelope level, not the response body.
- **State lifecycle risks:** None. The sandbox is stateless; each call runs in a fresh namespace.
- **API surface parity:** The new structured response is `run_python`-only. Other tools in this MCP keep their current response shapes (covered by the separate agent-effectiveness brainstorm).
- **Integration coverage:** `tests/test_request_filter.py` exercises the request-filter middleware's `TOOL_PARAMETERS` allowlist; verify that `run_python`'s parameter signature change (allowing union-typed `data`) does not break the allowlist match.
- **Unchanged invariants:** Sandbox security boundary (no file/network/OS access). 15s timeout. 8K code limit. 20K output cap. The `_safe_import` whitelist principle. Logging middleware. Auth/PDP layers.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Switching to a structured JSON response is a behavior change for any client that was string-parsing `"Error:"` prefixes. | Document in the README / next release notes. Current consumers are LLM clients that re-parse anyway; the migration is a net positive. |
| `ast.parse` + split-last-node may misbehave on rare valid-but-weird code (multi-statement last line via `;`, decorator at the end, etc.). | Fall back to plain `exec` on any `SyntaxError` from the split path. Test scenarios cover the common cases; weird edge cases fall back to existing behavior. |
| `numpy` and `pandas` may not be installed in the local venv even though they are in `requirements.txt`. | Mirror the existing `try/except ImportError` pattern in `_run_in_thread`. Tests that exercise pandas/numpy use `pytest.importorskip`. |
| FastMCP may not support `Union[str, list, dict]` in tool parameter schemas (R10). | Fallback: declare `data: object = None` and validate at runtime. Tested during Unit 3. |
| The new MCP resource introduces a pattern this repo has never used. | Follow `.claude/rules/mcp-conventions.md` and the `wks-mcp` reference. Keep the resource simple (one file, static content). |
| Misaligned line numbers when the auto-print split changes the offset of the last node. | Auto-print walks the AST; line numbers come from the *exception*'s traceback, not from the source-split position. Test scenarios cover multi-line error reporting. |

## Documentation / Operational Notes

- **README:** Add a short section under the existing `run_python` docs noting the new structured response shape and the new MCP resource.
- **Release notes for next deploy:** Call out the structured-response change as a behavior change. Note that no auth or data behavior is affected.
- **No migration needed for env vars, secrets, or Domo configuration.** Pure code change.
- **Linting:** Run `python -m ruff check domo_mcp tests` before declaring done (the project uses ruff; see `tests/test_request_filter.py` style).
- **Tests:** Run `pytest` from project root. The new `tests/test_code_executor.py` and `tests/test_python_env_resource.py` should be picked up automatically by the existing `pytest.ini`.
- **Deploy:** Standard Vercel flow (`vercel deploy --prod --scope wksusa`). No env-var changes.

## Sources & References

- Adjacent brainstorm (carves `run_python` out of scope, but useful context): `docs/brainstorms/2026-04-24-agent-effectiveness-and-reliability-brainstorm.md`
- Conventions: `.claude/rules/mcp-conventions.md`, `.claude/rules/mcp-deployment.md`
- Code under change: `domo_mcp/code_executor.py`, `domo_mcp/server_factory.py:478`
- Recent prior fix (context for why this plan exists): commits adding `_safe_import` and the docstring correction earlier today.
- FastMCP resource pattern reference: `wks-mcp` repo (see `ResourcesAsTools` transform mention in `.claude/rules/mcp-conventions.md`).
