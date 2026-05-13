"""Sandboxed Python code execution for analytics computations.

Runs user-supplied code in a restricted namespace with no file/network/OS access.
Available libraries: pandas, numpy, json, math, statistics, collections, decimal,
datetime, re. Output is captured from stdout and returned as a structured dict.
"""

from __future__ import annotations

import ast
import builtins
import collections
import contextlib
import datetime as _datetime_module
import decimal
import io
import json
import math
import re as _re_module
import statistics
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

MAX_CODE_LENGTH = 8_000   # characters
MAX_OUTPUT_LENGTH = 20_000  # characters
EXEC_TIMEOUT = 15.0  # seconds

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="code_exec")

_ALLOWED_IMPORTS = {
    "pandas",
    "numpy",
    "json",
    "math",
    "statistics",
    "collections",
    "decimal",
    "datetime",
    "re",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Restricted __import__: only allows whitelisted modules.

    The sandbox pre-binds these modules in the namespace, so user code rarely
    needs to import them — but LLM-generated code often writes the import
    anyway, and failing on a harmless `import pandas as pd` is a bad UX.
    """
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS:
        raise ImportError(f"import of '{name}' is not allowed in sandbox")
    return __import__(name, globals, locals, fromlist, level)


_SAFE_BUILTINS = {
    "__import__": _safe_import,
    "__build_class__": builtins.__build_class__,
    "print": print,
    "repr": repr,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "sum": sum,
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "type": type,
    "hasattr": hasattr,
    "getattr": getattr,
    "setattr": setattr,
    "vars": vars,
    "dir": dir,
    "iter": iter,
    "next": next,
    "any": any,
    "all": all,
    "divmod": divmod,
    "pow": pow,
    "hash": hash,
    "id": id,
    "format": format,
    "chr": chr,
    "ord": ord,
    "bin": bin,
    "hex": hex,
    "oct": oct,
    "complex": complex,
    "bytes": bytes,
    "bytearray": bytearray,
    "slice": slice,
    "True": True,
    "False": False,
    "None": None,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "StopIteration": StopIteration,
    "Exception": Exception,
}


NO_OUTPUT_HINT = (
    "(no output — run_python uses exec(), not a REPL. Use print() to emit "
    "values; a bare expression on the last line is auto-printed.)"
)


def _summarize_data(data: object) -> str | None:
    """Return a short human-readable summary of `data`, or None to omit."""
    if data is None:
        return None
    if isinstance(data, list):
        if not data:
            return "list of 0 items"
        head = data[0]
        if isinstance(head, dict):
            sample = list(head.keys())[:5]
            return f"list of {len(data)} items; sample keys: {sample}"
        return f"list of {len(data)} items; element type: {type(head).__name__}"
    if isinstance(data, dict):
        sample = list(data.keys())[:5]
        return f"dict with {len(data)} keys; sample keys: {sample}"
    rep = repr(data)
    if len(rep) > 80:
        rep = rep[:77] + "..."
    return f"{type(data).__name__}: {rep}"


def _user_line_from_traceback(exc: BaseException) -> int | None:
    """Walk the traceback and return the deepest user-frame line number."""
    tb = exc.__traceback__
    line: int | None = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<analyst>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _compile_split(code: str):
    """Parse `code` and split off the last bare-expression node if present.

    Returns (prefix_code_obj, last_expr_code_obj | None). Raises SyntaxError
    on parse failure — callers should catch and fall back.
    """
    tree = ast.parse(code, filename="<analyst>", mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = tree.body[-1]
        prefix = ast.Module(body=tree.body[:-1], type_ignores=tree.type_ignores)
        ast.fix_missing_locations(prefix)
        prefix_obj = compile(prefix, "<analyst>", "exec")
        expr = ast.Expression(body=last.value)
        ast.copy_location(expr, last)
        ast.fix_missing_locations(expr)
        last_obj = compile(expr, "<analyst>", "eval")
        return prefix_obj, last_obj
    return compile(tree, "<analyst>", "exec"), None


def _build_namespace(data: object) -> dict:
    namespace: dict = {
        "__builtins__": _SAFE_BUILTINS,
        # __name__ is required for `class` statements (Python sets Foo.__module__ from it).
        "__name__": "__analyst__",
        "data": data,
        "json": json,
        "math": math,
        "statistics": statistics,
        "collections": collections,
        "decimal": decimal,
        "datetime": _datetime_module,
        "re": _re_module,
    }
    try:
        import pandas as pd
        namespace["pd"] = pd
    except ImportError:
        pass
    try:
        import numpy as np
        namespace["np"] = np
    except ImportError:
        pass
    return namespace


def _run_in_thread(code: str, data: object) -> dict:
    """Execute code synchronously — called from a thread pool. Returns a dict."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    namespace = _build_namespace(data)
    start = time.monotonic()
    error_type: str | None = None
    error_message: str | None = None
    error_line: int | None = None

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        prefix_obj = last_obj = None
        try:
            prefix_obj, last_obj = _compile_split(code)
        except SyntaxError as exc:
            # Compile-time failure: report directly. tb_lineno isn't useful here.
            error_type = "SyntaxError"
            error_message = exc.msg or str(exc)
            error_line = exc.lineno
        if error_type is None:
            try:
                exec(prefix_obj, namespace)  # noqa: S102
                if last_obj is not None:
                    value = eval(last_obj, namespace)  # noqa: S307
                    if value is not None:
                        print(repr(value))
            except Exception as exc:
                error_type = type(exc).__name__
                error_message = str(exc)
                error_line = _user_line_from_traceback(exc)

    raw_stdout = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    original_length = len(raw_stdout)
    truncated = original_length > MAX_OUTPUT_LENGTH
    stdout = raw_stdout[:MAX_OUTPUT_LENGTH] if truncated else raw_stdout
    execution_ms = int((time.monotonic() - start) * 1000)

    if error_type is not None:
        result: dict = {
            "ok": False,
            "error_type": error_type,
            "error_message": error_message,
            "line": error_line,
            "stdout": stdout,
            "execution_ms": execution_ms,
        }
        if err:
            result["stderr"] = err
        return result

    if not stdout:
        stdout = NO_OUTPUT_HINT

    result = {
        "ok": True,
        "stdout": stdout,
        "stderr": err,
        "truncated": truncated,
        "original_length": original_length,
        "execution_ms": execution_ms,
    }
    summary = _summarize_data(data)
    if summary is not None:
        result["data_summary"] = summary
    return result


def execute(code: str, data: object = None) -> dict:
    """Execute Python analytics code in a restricted sandbox.

    Args:
        code: Python source code to execute.
        data: Pre-parsed data object (list/dict from a prior query result).

    Returns:
        A dict with `ok` plus either success fields
        (`stdout`, `stderr`, `truncated`, `original_length`, `execution_ms`,
        optional `data_summary`) or error fields (`error_type`,
        `error_message`, `line`, partial `stdout`, `execution_ms`).
    """
    if len(code) > MAX_CODE_LENGTH:
        return {
            "ok": False,
            "error_type": "CodeTooLong",
            "error_message": f"code too long ({len(code)} chars, max {MAX_CODE_LENGTH})",
            "line": None,
            "stdout": "",
            "execution_ms": 0,
        }

    # Dedent so Claude can indent its code naturally inside a JSON string
    code = textwrap.dedent(code)

    future = _executor.submit(_run_in_thread, code, data)
    try:
        return future.result(timeout=EXEC_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        return {
            "ok": False,
            "error_type": "Timeout",
            "error_message": f"execution timed out after {EXEC_TIMEOUT}s",
            "line": None,
            "stdout": "",
            "execution_ms": int(EXEC_TIMEOUT * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "line": None,
            "stdout": "",
            "execution_ms": 0,
        }
