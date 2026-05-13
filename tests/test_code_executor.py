"""Tests for the sandboxed Python code executor."""

import inspect
import json
import re
import textwrap

import pytest

from domo_mcp import server_factory
from domo_mcp.code_executor import (
    MAX_OUTPUT_LENGTH,
    NO_OUTPUT_HINT,
    execute,
)
from domo_mcp.server_factory import create_server


# ---------------------------------------------------------------------------
# Unit 1: Sandbox namespace and builtins completeness
# ---------------------------------------------------------------------------


class TestSandboxImports:
    """Pre-bound modules and whitelisted imports."""

    def test_numpy_pre_bound(self):
        np = pytest.importorskip("numpy")
        _ = np  # silence unused
        result = execute("print(np.array([1, 2, 3]).sum())")
        assert result["ok"] is True
        assert result["stdout"].strip() == "6"

    def test_numpy_import_allowed(self):
        pytest.importorskip("numpy")
        result = execute("import numpy as np\nprint(np.array([1, 2, 3]).sum())")
        assert result["ok"] is True
        assert result["stdout"].strip() == "6"

    def test_datetime_pre_bound(self):
        result = execute("print(datetime.date(2026, 1, 1).isoformat())")
        assert result["ok"] is True
        assert result["stdout"].strip() == "2026-01-01"

    def test_datetime_submodule_from_import(self):
        result = execute("from datetime import timedelta\nprint(timedelta(days=1))")
        assert result["ok"] is True
        assert result["stdout"].strip() == "1 day, 0:00:00"

    def test_re_pre_bound(self):
        result = execute("print(re.search('foo', 'foobar').group())")
        assert result["ok"] is True
        assert result["stdout"].strip() == "foo"

    def test_re_import_allowed(self):
        result = execute("import re\nprint(re.search('foo', 'foobar').group())")
        assert result["ok"] is True
        assert result["stdout"].strip() == "foo"


class TestSandboxBuiltins:
    """New entries in _SAFE_BUILTINS."""

    def test_class_definition_works(self):
        code = "class Foo:\n    x = 1\nprint(Foo().x)"
        result = execute(code)
        assert result["ok"] is True
        assert result["stdout"].strip() == "1"

    def test_chr_ord_bin_bytes(self):
        result = execute(
            "print(chr(65), bin(5), bytes([1, 2, 3]))"
        )
        assert result["ok"] is True
        assert result["stdout"].strip() == r"A 0b101 b'\x01\x02\x03'"

    def test_hex_oct_complex(self):
        result = execute("print(hex(255), oct(8), complex(1, 2))")
        assert result["ok"] is True
        assert result["stdout"].strip() == "0xff 0o10 (1+2j)"

    def test_bytearray_and_slice(self):
        result = execute("print(bytearray([1, 2, 3]), slice(0, 3))")
        assert result["ok"] is True
        out = result["stdout"].strip()
        assert "bytearray(b'\\x01\\x02\\x03')" in out
        assert "slice(0, 3, None)" in out


class TestSandboxSecurityRegressions:
    """Blocked imports stay blocked."""

    @pytest.mark.parametrize("module", ["os", "subprocess", "urllib.request", "socket", "sys"])
    def test_blocked_import(self, module):
        result = execute(f"import {module}")
        assert result["ok"] is False
        assert "not allowed in sandbox" in result["error_message"]


# ---------------------------------------------------------------------------
# Unit 2: execute() result enrichment
# ---------------------------------------------------------------------------


class TestResultShape:
    """Verify the structured dict shape and common fields."""

    def test_success_has_required_fields(self):
        result = execute("print('hi')")
        assert result["ok"] is True
        for key in ("stdout", "stderr", "truncated", "original_length", "execution_ms"):
            assert key in result
        assert result["stdout"] == "hi\n"
        assert result["truncated"] is False
        assert result["original_length"] == 3  # "hi\n"

    def test_error_has_required_fields(self):
        result = execute("1/0")
        assert result["ok"] is False
        for key in ("error_type", "error_message", "line", "stdout", "execution_ms"):
            assert key in result
        assert result["error_type"] == "ZeroDivisionError"

    def test_execution_ms_is_int(self):
        assert isinstance(execute("print(1)")["execution_ms"], int)

    def test_no_traceback_leak(self):
        """Regression guard: full tracebacks must not appear in the result."""
        result = execute("raise ValueError('boom')")
        # error_message is just the message, no "Traceback (most recent call last)"
        assert "Traceback" not in result["error_message"]
        assert "Traceback" not in result.get("stdout", "")


class TestAutoPrintLastExpression:
    """R2: bare expression on the last line is auto-printed REPL-style."""

    def test_single_line_expression_auto_prints(self):
        result = execute("1 + 1")
        assert result["ok"] is True
        assert result["stdout"] == "2\n"

    def test_multi_line_auto_prints_last(self):
        result = execute("x = 5\nx * 2")
        assert result["ok"] is True
        assert result["stdout"] == "10\n"

    def test_statement_does_not_auto_print(self):
        result = execute("x = 5")
        assert result["ok"] is True
        assert result["stdout"] == NO_OUTPUT_HINT

    def test_explicit_none_value_not_printed(self):
        result = execute("print('a')\nNone")
        assert result["ok"] is True
        assert result["stdout"] == "a\n"

    def test_function_call_returning_none_not_double_printed(self):
        result = execute("print('a')")
        assert result["ok"] is True
        assert result["stdout"] == "a\n"

    def test_string_repr_is_used(self):
        result = execute("'hello'")
        assert result["ok"] is True
        assert result["stdout"] == "'hello'\n"


class TestNoOutputHint:
    """R1: empty stdout returns the hint."""

    def test_empty_code(self):
        result = execute("")
        assert result["ok"] is True
        assert result["stdout"] == NO_OUTPUT_HINT

    def test_assignment_only(self):
        result = execute("x = 1\ny = 2")
        assert result["ok"] is True
        assert result["stdout"] == NO_OUTPUT_HINT


class TestLineNumbers:
    """R3: error responses include the user's line number."""

    def test_single_line_error(self):
        result = execute("1/0")
        assert result["ok"] is False
        assert result["line"] == 1

    def test_multi_line_error(self):
        result = execute("x = 1\ny = 2\n1/0")
        assert result["ok"] is False
        assert result["line"] == 3

    def test_syntax_error_line(self):
        result = execute("def foo(")
        assert result["ok"] is False
        assert result["error_type"] == "SyntaxError"
        assert result["line"] == 1

    def test_keyerror_line(self):
        code = "d = {'a': 1}\nprint(d['missing'])"
        result = execute(code)
        assert result["ok"] is False
        assert result["error_type"] == "KeyError"
        assert result["line"] == 2


class TestStructuredTruncation:
    """R4: truncation surfaced via `truncated` + `original_length` flags."""

    def test_no_truncation_when_under_limit(self):
        result = execute("print('hi')")
        assert result["truncated"] is False
        assert result["original_length"] == 3

    def test_truncation_above_limit(self):
        # Produce more than MAX_OUTPUT_LENGTH chars.
        code = f"print('x' * {MAX_OUTPUT_LENGTH + 1000})"
        result = execute(code)
        assert result["ok"] is True
        assert result["truncated"] is True
        # original_length is the printed string + newline (so MAX + 1001)
        assert result["original_length"] == MAX_OUTPUT_LENGTH + 1001
        assert len(result["stdout"]) == MAX_OUTPUT_LENGTH
        # No inline "...truncated at N chars" suffix any more.
        assert "truncated at" not in result["stdout"]


class TestDataSummary:
    """R9: data_summary describes the data variable."""

    def test_list_of_dicts(self):
        result = execute("print(len(data))", data=[{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        assert result["ok"] is True
        assert "data_summary" in result
        summary = result["data_summary"]
        assert "list of 2 items" in summary
        assert "a" in summary  # one of the sample keys

    def test_list_of_scalars(self):
        result = execute("print(sum(data))", data=[1, 2, 3])
        assert result["ok"] is True
        assert "list of 3 items" in result["data_summary"]
        assert "int" in result["data_summary"]

    def test_dict(self):
        result = execute("print(data['a'])", data={"a": 1, "b": 2})
        assert result["ok"] is True
        assert "dict with 2 keys" in result["data_summary"]

    def test_none_data_summary_is_null(self):
        """When data is None, data_summary is present but null (stable key set)."""
        result = execute("print('hi')", data=None)
        assert result["data_summary"] is None

    def test_empty_list_does_not_index(self):
        result = execute("print(len(data))", data=[])
        assert result["ok"] is True
        assert "list of 0 items" in result["data_summary"]


class TestExecuteCodeTooLong:
    """Boundary: oversize code returns CodeTooLong error."""

    def test_code_too_long(self):
        code = "x = 1\n" * 5_000  # well over MAX_CODE_LENGTH
        result = execute(code)
        assert result["ok"] is False
        assert result["error_type"] == "CodeTooLong"
        assert result["line"] is None


# ---------------------------------------------------------------------------
# Unit 3: run_python tool surface — dual-typed data, JSON response
# ---------------------------------------------------------------------------


@pytest.fixture
def server(monkeypatch):
    # run_python doesn't touch Domo, but create_server instantiates DomoClient
    # which requires credentials. Stub a developer-token config so the factory
    # builds; nothing here exercises the network.
    monkeypatch.setenv("DOMO_DEVELOPER_TOKEN", "test-token")
    monkeypatch.setenv("DOMO_HOST", "test.domo.com")
    return create_server()


async def _call_run_python(server, **kwargs) -> dict:
    """Invoke the run_python tool and return the parsed JSON payload."""
    result = await server.call_tool("run_python", kwargs)
    text = result.content[0].text
    return json.loads(text)


class TestRunPythonResponse:
    """JSON-shape and parsing tests for the run_python tool."""

    async def test_print_returns_json_string(self, server):
        payload = await _call_run_python(server, code="print('hi')")
        assert payload["ok"] is True
        assert payload["stdout"] == "hi\n"

    async def test_native_list_data(self, server):
        payload = await _call_run_python(
            server, code="print(len(data))", data=[1, 2, 3]
        )
        assert payload["ok"] is True
        assert payload["stdout"].strip() == "3"
        assert "list of 3 items" in payload["data_summary"]

    async def test_json_string_data_back_compat(self, server):
        payload = await _call_run_python(
            server, code="print(len(data))", data="[1,2,3]"
        )
        assert payload["ok"] is True
        assert payload["stdout"].strip() == "3"

    async def test_native_dict_data(self, server):
        payload = await _call_run_python(
            server, code="print(data['a'])", data={"a": 1, "b": 2}
        )
        assert payload["ok"] is True
        assert payload["stdout"].strip() == "1"
        assert "dict with 2 keys" in payload["data_summary"]

    async def test_empty_data_summary_is_null(self, server):
        payload = await _call_run_python(server, code="print('hi')", data="")
        assert payload["ok"] is True
        assert payload["data_summary"] is None

    async def test_runtime_error_returns_structured_error(self, server):
        payload = await _call_run_python(server, code="1/0")
        assert payload["ok"] is False
        assert payload["error_type"] == "ZeroDivisionError"
        assert payload["line"] == 1

    async def test_invalid_json_string_data(self, server):
        payload = await _call_run_python(
            server, code="print(data)", data="{not valid"
        )
        assert payload["ok"] is False
        assert payload["error_type"] == "JSONDecodeError"

    async def test_unsupported_data_type(self, server):
        """Pydantic rejects an unsupported `data` type at the MCP boundary.

        The tool body's defensive TypeError branch is unreachable now that
        the parameter has a real union schema — the call never reaches it.
        We verify the rejection surfaces as a tool-call error instead of a
        structured `{ok: false}` response.
        """
        with pytest.raises(Exception) as exc_info:
            await server.call_tool("run_python", {"code": "print(data)", "data": 42})
        message = str(exc_info.value)
        assert "validation" in message.lower() or "type" in message.lower()


# ---------------------------------------------------------------------------
# Unit 4: run_python docstring — both examples must execute cleanly.
# ---------------------------------------------------------------------------


def _extract_docstring_examples(docstring: str) -> list[str]:
    """Pull each `code = '''...'''` block out of the run_python docstring."""
    blocks = re.findall(r"code\s*=\s*'''(.*?)'''", docstring, re.DOTALL)
    return [textwrap.dedent(b).strip("\n") for b in blocks]


def _run_python_docstring() -> str:
    """Find the run_python tool's docstring without instantiating a server."""
    source = inspect.getsource(server_factory.create_server)
    # The signature may span multiple lines (Annotated unions etc.), so match
    # up to the `-> str:` arrow rather than balancing the parens.
    m = re.search(
        r'async def run_python\b.*?->\s*str:\s*"""(.*?)"""',
        source,
        re.DOTALL,
    )
    assert m, "Could not locate run_python docstring"
    return m.group(1)


class TestRunPythonDocstring:
    def test_docstring_contains_two_examples(self):
        examples = _extract_docstring_examples(_run_python_docstring())
        assert len(examples) == 2, f"Expected 2 examples, got {len(examples)}"

    def test_pandas_example_runs(self):
        pytest.importorskip("pandas")
        examples = _extract_docstring_examples(_run_python_docstring())
        code = examples[0]
        data = [
            {"FiscalPrd": 10, "FY2024": 2733551, "FY2025": 9895014},
            {"FiscalPrd": 11, "FY2024": 1500000, "FY2025": 2000000},
        ]
        result = execute(code, data)
        assert result["ok"] is True, result.get("error_message")
        assert "change_pct" in result["stdout"]

    def test_plain_python_example_runs(self):
        examples = _extract_docstring_examples(_run_python_docstring())
        code = examples[1]
        data = [
            {"category": "A"},
            {"category": "B"},
            {"category": "A"},
            {"category": "C"},
            {"category": "A"},
        ]
        result = execute(code, data)
        assert result["ok"] is True, result.get("error_message")
        assert "A: 3" in result["stdout"]


# ---------------------------------------------------------------------------
# Unit H: Test backfill — coverage gaps surfaced by the code review.
# ---------------------------------------------------------------------------


class TestStableResponseShape:
    """Success and error responses share the same key set."""

    _expected_keys = {
        "ok",
        "stdout",
        "stderr",
        "truncated",
        "original_length",
        "execution_ms",
        "data_summary",
    }
    _error_extra = {"error_type", "error_message", "line"}

    def test_success_shape_keys(self):
        result = execute("print('hi')")
        assert self._expected_keys.issubset(result.keys())

    def test_error_shape_keys(self):
        result = execute("1/0")
        assert self._expected_keys.issubset(result.keys())
        assert self._error_extra.issubset(result.keys())


class TestErrorPathRetainsTruncationMetadata:
    """Error result must carry the same truncation fields as success."""

    def test_partial_stdout_on_runtime_error(self):
        result = execute("print('first')\nprint('second')\n1/0")
        assert result["ok"] is False
        assert result["error_type"] == "ZeroDivisionError"
        assert result["line"] == 3
        assert "first" in result["stdout"] and "second" in result["stdout"]
        assert result["truncated"] is False
        assert result["original_length"] > 0

    def test_truncated_stdout_on_error(self):
        code = f"print('x' * {MAX_OUTPUT_LENGTH + 1000})\n1/0"
        result = execute(code)
        assert result["ok"] is False
        assert result["truncated"] is True
        assert result["original_length"] > MAX_OUTPUT_LENGTH
        assert len(result["stdout"]) == MAX_OUTPUT_LENGTH


class TestBaseExceptionHandling:
    """User code raising BaseException subclasses must not crash a worker.

    SystemExit itself isn't reachable from inside the sandbox (it's not in
    _SAFE_BUILTINS), but a user can synthesise a direct BaseException
    subclass via `type() + Exception.__bases__[0]`. That's the realistic
    attack vector and the path we need to guard.
    """

    def test_user_constructed_base_exception(self):
        code = "E = type('E', (Exception.__bases__[0],), {})\nraise E('boom')"
        result = execute(code)
        assert result["ok"] is False
        assert result["error_type"] == "E"
        assert "boom" in result["error_message"]


class TestSubmoduleImportBlocking:
    """`from X import Y` is blocked when X is not allowlisted."""

    @pytest.mark.parametrize(
        "code",
        [
            "from os import path",
            "from subprocess import run",
            "from urllib import request",
        ],
    )
    def test_from_import_blocked(self, code):
        result = execute(code)
        assert result["ok"] is False
        assert result["error_type"] == "ImportError"
        assert "not allowed in sandbox" in result["error_message"]


class TestFalsyAutoPrint:
    """Auto-print fires for any non-None value, including falsy ones."""

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("0", "0\n"),
            ("[]", "[]\n"),
            ("False", "False\n"),
            ("''", "''\n"),
            ("0.0", "0.0\n"),
            ("{}", "{}\n"),
        ],
    )
    def test_falsy_value_is_auto_printed(self, expr, expected):
        result = execute(expr)
        assert result["ok"] is True
        assert result["stdout"] == expected


class TestSummarizeDataFallback:
    """Non-list, non-dict data still gets a summary."""

    def test_tuple_summary(self):
        result = execute("print(data)", data=(1, 2, 3))
        # Pydantic doesn't sit between execute() and the user — direct calls accept any type.
        assert result["ok"] is True
        assert result["data_summary"].startswith("tuple")

    def test_scalar_summary(self):
        result = execute("print(data)", data=42)
        assert result["ok"] is True
        assert result["data_summary"].startswith("int")
        assert "42" in result["data_summary"]

    def test_long_repr_truncated_to_80(self):
        # A string longer than 80 chars exercises the truncation branch.
        long_string = "x" * 200
        result = execute("print(len(data))", data=long_string)
        assert result["ok"] is True
        # data_summary is "str: 'xxx...'" — the inner repr is truncated.
        assert len(result["data_summary"]) < 200
        assert result["data_summary"].endswith("...")


class TestTimeoutPath:
    """execute() returns a structured Timeout result when work overruns.

    We mock the executor's future rather than actually running an infinite
    loop — the production code path's `future.cancel()` does NOT stop a
    running thread (a known pre-existing limitation tracked in the sandbox-
    escape Linear issue). A real infinite loop would leak a thread and hang
    pytest teardown.
    """

    def test_future_timeout_returns_structured_error(self, monkeypatch):
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        from domo_mcp import code_executor

        class _FakeFuture:
            def result(self, timeout=None):
                raise FuturesTimeoutError()

            def cancel(self):
                return True

        monkeypatch.setattr(code_executor._executor, "submit", lambda *a, **kw: _FakeFuture())
        result = execute("print('does not matter')")
        assert result["ok"] is False
        assert result["error_type"] == "Timeout"
        assert "timed out" in result["error_message"]
        assert result["execution_ms"] > 0


class TestCrossRequestModuleIsolation:
    """REGRESSION CAPTURE — currently FAILS because the sandbox allows
    cross-request module mutation via setattr on shared singletons. When this
    test starts passing, the pre-existing P0 sandbox-escape issue is fixed.
    Marked xfail so it doesn't block CI but still runs and reports state.
    """

    @pytest.mark.xfail(
        reason="Pre-existing sandbox escape: setattr persists across requests. "
        "See the P0 Linear issue tracking the sandbox-hardening work.",
        strict=False,
    )
    def test_math_pi_not_mutated_across_calls(self):
        import math as _real_math
        original_pi = _real_math.pi
        try:
            execute("setattr(math, 'pi', 999.0)")
            result = execute("print(math.pi)")
            assert result["stdout"].strip() == str(original_pi)
        finally:
            _real_math.pi = original_pi  # type: ignore[misc]


class TestSyntaxErrorLineNumber:
    """SyntaxError reports the user's line, not None."""

    def test_simple_syntax_error_has_line(self):
        result = execute("def foo(")
        assert result["ok"] is False
        assert result["error_type"] == "SyntaxError"
        assert result["line"] == 1

    def test_multi_line_syntax_error_has_line(self):
        # The unmatched paren is on line 3.
        result = execute("x = 1\ny = 2\nz = (\n")
        assert result["ok"] is False
        assert result["error_type"] == "SyntaxError"
        assert result["line"] is not None
        assert result["line"] >= 3


class TestSerializationFallback:
    """run_python returns a SerializationError when the result dict can't json.dumps."""

    async def test_unserializable_result_returns_error(self, server, monkeypatch):
        # Inject a non-serializable value into the executor's return.
        def broken_execute(code, data=None):
            return {"ok": True, "stdout": object(), "execution_ms": 1}

        monkeypatch.setattr(
            "domo_mcp.server_factory._execute_code", broken_execute
        )
        payload = await _call_run_python(server, code="print(1)")
        assert payload["ok"] is False
        assert payload["error_type"] == "SerializationError"
        assert "could not be serialized" in payload["error_message"]
