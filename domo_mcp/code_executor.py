"""Sandboxed Python code execution for analytics computations.

Runs user-supplied code in a restricted namespace with no file/network/OS access.
Available libraries: pandas, json, math, statistics, collections, decimal.
Output is captured from stdout and returned as a string.
"""

from __future__ import annotations

import collections
import contextlib
import decimal
import io
import json
import math
import statistics
import textwrap
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

MAX_CODE_LENGTH = 8_000   # characters
MAX_OUTPUT_LENGTH = 20_000  # characters
EXEC_TIMEOUT = 15.0  # seconds

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="code_exec")

_SAFE_BUILTINS = {
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


def _run_in_thread(code: str, data: object) -> str:
    """Execute code synchronously — called from a thread pool."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        import pandas as pd
        has_pandas = True
    except ImportError:
        has_pandas = False

    namespace: dict = {
        "__builtins__": _SAFE_BUILTINS,
        "data": data,
        "json": json,
        "math": math,
        "statistics": statistics,
        "collections": collections,
        "decimal": decimal,
    }
    if has_pandas:
        namespace["pd"] = pd

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            exec(compile(code, "<analyst>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"

    output = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    if err:
        output += f"\n[stderr]\n{err}"

    if len(output) > MAX_OUTPUT_LENGTH:
        output = output[:MAX_OUTPUT_LENGTH] + f"\n... (output truncated at {MAX_OUTPUT_LENGTH} chars)"

    return output or "(no output)"


def execute(code: str, data: object = None) -> str:
    """Execute Python analytics code in a restricted sandbox.

    Args:
        code: Python source code to execute.
        data: Pre-parsed data object (list/dict from a prior query result).

    Returns:
        Captured stdout, or an error message prefixed with "Error:".
    """
    if len(code) > MAX_CODE_LENGTH:
        return f"Error: code too long ({len(code)} chars, max {MAX_CODE_LENGTH})"

    # Dedent so Claude can indent its code naturally inside a JSON string
    code = textwrap.dedent(code)

    future = _executor.submit(_run_in_thread, code, data)
    try:
        return future.result(timeout=EXEC_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        return f"Error: execution timed out after {EXEC_TIMEOUT}s"
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"
