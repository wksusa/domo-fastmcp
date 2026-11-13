"""Regression tests for eval harness fixtures (tools.json, mocks, export)."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_JSON = REPO_ROOT / "evals" / "agents" / "domo-mcp" / "tools.json"
EVALS_CONFIG = REPO_ROOT / "evals" / "evals.config.yaml"
BASELINE_MOCKS = REPO_ROOT / "evals" / "suites" / "tool-smoke" / "mocks" / "baseline.json"


def _repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_committed_tools() -> list[dict]:
    return json.loads(TOOLS_JSON.read_text(encoding="utf-8"))


def _tool_names(tools: list[dict]) -> set[str]:
    return {entry["function"]["name"] for entry in tools}


def _load_export_script_module():
    script = REPO_ROOT / "evals" / "scripts" / "export_tools_json.py"
    spec = importlib.util.spec_from_file_location("export_tools_json", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    real_socket = socket.socket

    def guarded_socket(family=-1, type=-1, proto=-1, fileno=None):
        if family in (socket.AF_INET, socket.AF_INET6):
            raise OSError("Network access blocked in eval harness test")
        return real_socket(family, type, proto, fileno)

    def guarded_create_connection(*_args, **_kwargs):
        raise OSError("Network access blocked in eval harness test")

    monkeypatch.setattr(socket, "socket", guarded_socket)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


@pytest.fixture
def guard_domo_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args, **_kwargs):
        raise RuntimeError("Domo runtime must not load during eval export")

    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", blocked)

    domo_stub = type(sys)("domo_mcp.domo")
    domo_stub.DomoClient = blocked
    domo_stub.DomoRequestError = RuntimeError
    monkeypatch.setitem(sys.modules, "domo_mcp.domo", domo_stub)

    code_stub = type(sys)("domo_mcp.code_executor")
    code_stub._error_result = lambda *_a, **_k: {}
    code_stub.execute = blocked
    monkeypatch.setitem(sys.modules, "domo_mcp.code_executor", code_stub)


@pytest.mark.asyncio
async def test_tools_json_matches_fastmcp(
    block_sockets: None,
    guard_domo_runtime: None,
) -> None:
    _repo_on_path()
    from evals.lib.openai_tools import export_openai_tools

    exported = await export_openai_tools()
    committed = _load_committed_tools()
    assert exported == committed


def test_evals_config_strict_unmocked_tools() -> None:
    config = yaml.safe_load(EVALS_CONFIG.read_text(encoding="utf-8"))
    assert config["budget"]["strict_unmocked_tools"] is True


def test_baseline_mocks_cover_all_exported_tools() -> None:
    baseline = json.loads(BASELINE_MOCKS.read_text(encoding="utf-8"))
    tool_names = _tool_names(_load_committed_tools())
    assert set(baseline.keys()) == tool_names


class _BlockDomoModules:
    """Fail loudly if export tries to import Domo runtime modules."""

    def __init__(self, *names: str) -> None:
        self._names = frozenset(names)

    def find_spec(self, fullname, _path, _target=None):
        if fullname in self._names:
            raise RuntimeError(f"import blocked: {fullname}")
        return None


@pytest.mark.asyncio
async def test_export_offline_without_domo_client(
    block_sockets: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Export must succeed with sockets blocked and Domo imports guarded."""
    for mod in (
        "domo_mcp.server_factory",
        "domo_mcp.domo",
        "domo_mcp.code_executor",
    ):
        sys.modules.pop(mod, None)

    def blocked(*_args, **_kwargs):
        raise RuntimeError("load_dotenv blocked")

    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", blocked)

    import_hook = _BlockDomoModules("domo_mcp.domo", "domo_mcp.code_executor")
    sys.meta_path.insert(0, import_hook)
    try:
        _repo_on_path()
        export_mod = _load_export_script_module()

        exported = await export_mod._export()
        assert "domo_mcp.domo" not in sys.modules
        assert "domo_mcp.code_executor" not in sys.modules
        assert exported == _load_committed_tools()
    finally:
        sys.meta_path.remove(import_hook)
