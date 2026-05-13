---
title: "feat: run_python code-review follow-ups (gated_auto + manual)"
type: feat
status: active
date: 2026-05-13
references:
  - docs/plans/2026-05-13-feat-run-python-llm-friendliness-plan.md
  - PR: https://github.com/wksusa/domo-fastmcp/pull/5
  - Code review run: .context/compound-engineering/ce-code-review/20260513-185811-95fd37e2/
---

# run_python Code-Review Follow-ups

## Why this exists

PR #5 (`feat(run_python): structured JSON response and sandbox completeness`)
shipped 12 LLM-friendliness improvements. The multi-persona code review
afterwards surfaced findings that are concrete and fixable but were intentionally
NOT applied as `safe_auto` autofixes — they change observable behavior,
contracts, or require judgment.

This plan captures the remaining work so a fresh session can pick it up with
full context.

**Read first:**
- The base PR: https://github.com/wksusa/domo-fastmcp/pull/5
- The original plan: `docs/plans/2026-05-13-feat-run-python-llm-friendliness-plan.md`
- The review artifact directory: `.context/compound-engineering/ce-code-review/20260513-185811-95fd37e2/`
  - Each persona wrote full JSON there (correctness, testing, maintainability, security, adversarial, api-contract, reliability, kieran-python, project-standards, ce-agent-native-reviewer, ce-learnings-researcher)
- Already-applied safe_auto cleanups: commit `0978aac` on `feat/run-python-llm-friendliness`

**NOT in scope here** (separate P0 work, file a Linear issue):
- The pre-existing CPython sandbox escape via `getattr(json, '__builtins__')['__import__']('os')`. Confirmed exploit in the review session. Predates this PR; the threat-model decision (remove reflection builtins / module copying / subprocess isolation) is its own discussion.
- The thread-leak DoS via `future.cancel()` not killing running threads. Pre-existing; aggravated slightly by adding `re` (ReDoS) and `numpy` (uncancellable C loops) to the sandbox.

## Scope summary

10 findings:
- 5 small "contract stability" fixes
- 1 schema fix that touches inputSchema visibility
- 1 small refactor
- 1 documentation fix
- 1 test-backfill push
- 1 small consistency fix

All land on the same branch (`feat/run-python-llm-friendliness`) and get
folded into PR #5, OR ship as a follow-up PR — caller's choice.

## Implementation Units

- [ ] **Unit A: Always-present response fields (R5, R10, R11 from review)**

**Goal:** Make the success and error response shapes share a stable key set.
Clients should not need to branch on `ok` before reading `truncated`, `original_length`, `stderr`, `data_summary`.

**Files:**
- Modify: `domo_mcp/code_executor.py` (`_run_in_thread` and `execute` error paths)
- Modify: `tests/test_code_executor.py` (assert presence of fields on both branches)

**Approach:**
- Success result: already has these. Add `data_summary` always (use `None` when no data, JSON serializes to `null`).
- Error result (runtime exception path in `_run_in_thread`): currently includes `stdout` + `execution_ms` only. Add `stderr` (always empty string when absent), `truncated`, `original_length`, `data_summary: None`.
- Error result (compile-time `SyntaxError` path): same fields.
- `execute()`'s outer error paths (`CodeTooLong`, `Timeout`, generic `Exception`): same fields.
- Helper `_error_result(...)` (see Unit C) is a natural place to centralize this.

**Test scenarios:**
- Add an assertion class `TestResponseShape` that calls `execute(...)` with success and error inputs and asserts the set of keys is identical across both.
- `data_summary` present (as None) when no data passed.

---

- [ ] **Unit B: Catch BaseException, not just Exception**

**Goal:** Prevent worker thread crashes when user code raises a BaseException
subclass (which is constructible via `type('X', (Exception.__bases__[0],), {})`).

**Files:**
- Modify: `domo_mcp/code_executor.py` (`_run_in_thread` line ~233, `execute` outer handler)
- Modify: `tests/test_code_executor.py`

**Approach:**
- Change `except Exception as exc:` to `except BaseException as exc:` in both
  the inner runtime-exception block and the outer `execute()` handler.
- Re-raise `KeyboardInterrupt` explicitly so Ctrl-C in a dev process still
  works. Do not swallow it into the structured response.
- `SystemExit`, `GeneratorExit`, custom `BaseException` subclasses → caught
  and reported via the normal error dict.

**Test scenarios:**
- Test that `raise SystemExit("bye")` returns `{ok: false, error_type: "SystemExit", line: 1}` instead of crashing the worker.
- Test that user code constructing a `BaseException` subclass via `type()` returns a structured error.
- (Do not test KeyboardInterrupt — too disruptive in pytest.)

---

- [ ] **Unit C: `_error_result` helper + truncation metadata on error**

**Goal:** Stop duplicating the error-dict literal in 4 places (code_executor.py)
and ensure error results carry the same truncation metadata as success results
(finding #10 + #9 combined — they share the same touch points).

**Files:**
- Modify: `domo_mcp/code_executor.py`

**Approach:**
- Define `_error_result(error_type: str, message: str, *, line: int | None = None, stdout: str = "", stderr: str = "", truncated: bool = False, original_length: int = 0, execution_ms: int = 0, data_summary: str | None = None) -> dict:` returning the canonical error dict shape.
- Replace 4 inline error-dict literals (runtime exception, `CodeTooLong`, `Timeout`, generic `Exception`) with calls to this helper.
- For the runtime exception path, pass the already-computed `truncated`, `original_length`, `stderr`, and `data_summary` so the partial-stdout-before-error case carries full context.

**Test scenarios:**
- Test that code which prints > MAX_OUTPUT_LENGTH chars and then raises returns `{ok: false, truncated: true, original_length: N}` with `len(stdout) == MAX_OUTPUT_LENGTH`.
- Existing tests should pass unchanged.

---

- [ ] **Unit D: `data` parameter — proper union schema**

**Goal:** Replace `data: Any = None` with a union type so FastMCP emits a real
JSON Schema, plus a `Field(description=...)` so the LLM understands when to
pass native vs JSON-string.

**Files:**
- Modify: `domo_mcp/server_factory.py` (the `run_python` signature)
- Verify: FastMCP renders the union cleanly into the inputSchema

**Approach:**
- Signature: `data: Annotated[list | dict | str | None, Field(description="Input data, available in code as `data`. Pass a native list or dict (preferred — no JSON round-trip). A JSON string is also accepted for back-compat. Omit or pass null if no input is needed.")] = None`
- Imports: `from typing import Annotated` and `from pydantic import Field` (already imported via ValidationError? — check).
- If FastMCP/Pydantic rejects the union in the schema, fall back: keep `data: Any = None` but document the dual form in the description via `Field(description=...)` alone. Use the smoke-test path to verify what the inputSchema actually looks like.

**Test scenarios:**
- The existing `TestRunPythonResponse` integration tests cover native list, native dict, JSON string, null, and unsupported (int). No new test needed for behavior, but consider asserting the inputSchema shape:
  ```python
  async def test_run_python_input_schema_has_anyof(server):
      tools = await server.list_tools()
      rp = next(t for t in tools if t.name == "run_python")
      data_schema = rp.inputSchema["properties"]["data"]
      assert "anyOf" in data_schema or "type" in data_schema
  ```

---

- [ ] **Unit E: `json.dumps(result)` serialization fallback**

**Goal:** When the result dict contains a value that `json.dumps` can't
serialize (e.g., surrogate-escaped bytes in stdout/stderr from numpy debug
output), return a structured `SerializationError` instead of raising into the
MCP layer.

**Files:**
- Modify: `domo_mcp/server_factory.py` (the `run_python` function body)

**Approach:**
- Wrap the final `return json.dumps(result)` in a try/except:
  ```python
  try:
      return json.dumps(result)
  except (TypeError, ValueError) as e:
      return json.dumps({
          "ok": False,
          "error_type": "SerializationError",
          "error_message": f"result could not be serialized: {e}",
          "line": None,
          "stdout": "",
          "stderr": "",
          "truncated": False,
          "original_length": 0,
          "execution_ms": result.get("execution_ms", 0),
          "data_summary": None,
      })
  ```
- The fallback dict is itself trivially serializable, so the second `json.dumps` cannot fail.

**Test scenarios:**
- Inject a non-serializable value into the result dict via a test double, assert SerializationError is returned. Or: write user code that prints a surrogate-escaped string (e.g., via `b'\xff'.decode('utf-8', 'surrogateescape')`) and assert the response is structured.

---

- [ ] **Unit F: `python_env._CONTENT` constants from source**

**Goal:** Stop hardcoding `8,000` / `20,000` / `15 seconds` in the resource
markdown. Source from `MAX_CODE_LENGTH` / `MAX_OUTPUT_LENGTH` / `EXEC_TIMEOUT`.

**Files:**
- Modify: `domo_mcp/resources/python_env.py`
- Modify: `tests/test_python_env_resource.py`

**Approach:**
- Option A (preferred): build `_CONTENT` from an f-string interpolating the
  constants. Keep most of the markdown as a literal, but replace the limits
  section with f-string substitution at module load.
- Option B: keep the literal text but add a test that asserts each numeric
  value appears in `_CONTENT` exactly matching `f"{MAX_CODE_LENGTH:,}"` etc.

Option A is the better fix; Option B is a less-invasive guard.

**Test scenarios:**
- Update the existing parametrized "mentions expected topics" test to use the actual constants, not hardcoded strings.
- If Option A, add a test asserting the formatted constants appear in `_CONTENT`.

---

- [ ] **Unit G: Document the `query_dataset` → `run_python` data shape**

**Goal:** Either normalize `query_dataset`'s response shape OR document the
reshape step prominently. Right now the `run_python` docstring assumes
`data` is `list[dict]` but `query_dataset` returns `{columns, rows}`. Agents
following the examples literally will fail.

**Files (decision dependent):**
- If normalize: modify `domo_mcp/server_factory.py` (`query_dataset`) — risky, affects every caller
- If document: modify `domo_mcp/server_factory.py` (`run_python` docstring) + `domo_mcp/resources/python_env.py` (add a section)

**Recommendation:** document, not normalize. `query_dataset`'s raw shape is
already in production; normalizing it is a separate breaking change. Add a
"From query_dataset to run_python" section to `python://env` with the reshape
snippet:

```python
# query_dataset returns {"columns": [{"name": ...}, ...], "rows": [[...], ...]}
cols = [c["name"] for c in data["columns"]]
rows = [dict(zip(cols, r)) for r in data["rows"]]
df = pd.DataFrame(rows)
```

Add a one-line reference in `run_python`'s docstring pointing to that section.

**Test scenarios:** docstring-validation test in `tests/test_code_executor.py` should still pass. Optionally add a test that runs the reshape snippet against a synthetic `{columns, rows}` payload.

---

- [ ] **Unit H: Test backfill**

**Goal:** Close coverage gaps identified by multiple reviewers. Each test is a
regression guard for a previously-uncovered behavior.

**Files:**
- Modify: `tests/test_code_executor.py`
- Modify: `tests/test_python_env_resource.py`

**Tests to add** (each is small, ~5-15 lines):

1. **Timeout path:** Execute `while True: pass` and assert `{ok: false, error_type: "Timeout"}` returns within EXEC_TIMEOUT + 2s.
2. **Partial stdout on error:** `"print('first')\nprint('second')\n1/0"` → assert `stdout` contains both prints, `ok: false`, `line: 3`.
3. **BaseException subclass:** `"raise SystemExit('bye')"` → assert structured error.
4. **Cross-request module isolation:** First call mutates `setattr(math, 'pi', 999.0)`. Second call asserts `math.pi == 3.14159...`. If this test fails, document the fix path in the sandbox-escape Linear issue. (Currently this WILL fail — captures the regression for when the sandbox is hardened.)
5. **Submodule import blocking:** `from os import path` → assert `ImportError: import of 'os'` (regression guard parallel to top-level `import os`).
6. **Falsy-but-not-None auto-print:** Last line `0`, `[]`, `False`, `""` → each prints its repr. Guards against someone "fixing" `if value is not None` to `if value`.
7. **`_summarize_data` fallback:** `data=(1, 2, 3)` or `data=42` → response includes a `data_summary` with type and repr (truncated to 80 chars for large values).
8. **`_CONTENT` numeric constants:** parametrized test asserting `MAX_CODE_LENGTH` value (formatted with commas) appears in `_CONTENT`, same for `MAX_OUTPUT_LENGTH` and `EXEC_TIMEOUT`.
9. **SyntaxError line number:** `"1 +\n2\n3"` → assert structured error with `line == 1` (or whatever Python reports — the point is to verify `exc.lineno` is captured on compile-time failures).

These are independent. Land them as separate commits if useful, or one batch.

---

- [ ] **Unit I: `python://` URI scheme (advisory, optional)**

**Goal:** Decide whether to switch to `domo://python-env` for forward
compatibility, or stay on `python://env`.

**Files:** `domo_mcp/resources/python_env.py`, `tests/test_python_env_resource.py`

**Approach:** Currently works with FastMCP and known clients. Switching is a
purely defensive change that costs nothing functionally but breaks any external
docs that link to `python://env`. Recommendation: **defer until a client
actually rejects the scheme.** Mark this as a watch item, not a fix.

## Scope Boundaries

- Do not touch the sandbox escape primitives. That's the pre-existing P0 work in a separate Linear issue.
- Do not change `query_dataset`'s response shape. Document the reshape instead.
- Do not introduce TypedDict / Pydantic models for the response. The bare-dict approach is documented; future-typed-response work is its own design discussion.
- Do not change `EXEC_TIMEOUT`, `MAX_CODE_LENGTH`, or `MAX_OUTPUT_LENGTH` constants. The plan only sources the existing values into the resource markdown.

## Verification

After each unit:
- `.venv/bin/pytest tests/test_code_executor.py tests/test_python_env_resource.py -q` — all green
- `.venv/bin/python -m ruff check domo_mcp/code_executor.py domo_mcp/resources domo_mcp/server_factory.py tests/test_code_executor.py tests/test_python_env_resource.py` — clean

End-to-end smoke (after all units):
- Boot local server: `DOMO_DEVELOPER_TOKEN=test-token DOMO_HOST=test.domo.com AUTH_MODE=none .venv/bin/python -m uvicorn api.mcp:app --host 127.0.0.1 --port 8765`
- `tools/call run_python {"code": "1/0"}` → response includes `truncated`, `original_length`, `stderr` keys (Unit A).
- `tools/list` for `run_python` → `inputSchema.properties.data` has `anyOf` or proper type (Unit D).
- `resources/read python://env` → mentions exactly the current `MAX_*` values (Unit F).

## Risks

| Risk | Mitigation |
|------|------------|
| Always-present fields change the response shape again (clients see new keys with null values) | The shape was just changed in PR #5; clients are already adapting. Add a single coordinated commit so the second adaptation is one step, not a string of incremental schema additions. |
| `BaseException` catch can hide test failures from pytest if `_run_in_thread` is ever called from a test context outside its thread pool | The function is only called via `_executor.submit`. Tests use `execute()` which sits behind the pool. No leak path. |
| FastMCP/Pydantic schema rendering of the union may not match what MCP clients expect (some clients require `type` not `anyOf`) | Smoke test against `tools/list` before merging Unit D. If broken, fall back to `Any` + `Field(description=...)`. |
| Surrogate-byte test (Unit E) may not reproduce reliably across Python versions | Use a synthetic broken-result-dict test (inject `{"stdout": object()}` via a test-only path) instead of trying to produce a surrogate byte from sandboxed code. |

## How to resume in a fresh session

```
# 1. Check out the branch
git checkout feat/run-python-llm-friendliness && git pull

# 2. Load the review artifacts for full reviewer findings
ls .context/compound-engineering/ce-code-review/20260513-185811-95fd37e2/

# 3. Read this plan + the original
less docs/plans/2026-05-13-feat-run-python-followups-plan.md
less docs/plans/2026-05-13-feat-run-python-llm-friendliness-plan.md

# 4. Start with Unit A or C — they unblock the others by establishing the canonical error dict shape via _error_result()
```
