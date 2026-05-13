"""Tests for the python://env MCP resource."""

import pytest

from domo_mcp.code_executor import EXEC_TIMEOUT, MAX_CODE_LENGTH, MAX_OUTPUT_LENGTH
from domo_mcp.resources.python_env import URI, _CONTENT
from domo_mcp.server_factory import create_server


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DOMO_DEVELOPER_TOKEN", "test-token")
    monkeypatch.setenv("DOMO_HOST", "test.domo.com")
    return create_server()


class TestContentStructure:
    """Static checks on the resource body."""

    @pytest.mark.parametrize(
        "needle",
        ["data", "pd", "np", "datetime", "re", "print()"],
    )
    def test_mentions_expected_topics(self, needle):
        assert needle in _CONTENT, f"Resource missing expected substring: {needle!r}"

    def test_limits_match_executor_constants(self):
        """Limits section must reflect the actual executor constants, not stale literals."""
        assert f"{MAX_CODE_LENGTH:,}" in _CONTENT
        assert f"{MAX_OUTPUT_LENGTH:,}" in _CONTENT
        assert f"{EXEC_TIMEOUT:g} seconds" in _CONTENT

    def test_no_template_placeholders_left(self):
        """Regression guard: substitution must complete at import time."""
        assert "{limits}" not in _CONTENT

    def test_code_fences_balanced(self):
        # Every ``` opens or closes a block — must be even.
        assert _CONTENT.count("```") % 2 == 0


class TestResourceRegistration:
    """Round-trip through the MCP machinery to confirm registration."""

    async def test_resource_listed(self, server):
        resources = await server.list_resources()
        uris = [str(r.uri) for r in resources]
        assert URI in uris

    async def test_resource_has_description(self, server):
        resources = await server.list_resources()
        match = next(r for r in resources if str(r.uri) == URI)
        assert match.description
        assert "Python runtime environment" in match.description

    async def test_resource_read_returns_content(self, server):
        result = await server.read_resource(URI)
        # FastMCP returns ReadResourceResult with `.contents[0].content`
        text = result.contents[0].content
        assert "pd (pandas)" in text or "pd" in text
        assert "data" in text

    async def test_tools_list_still_succeeds(self, server):
        """Regression guard: registering the resource didn't break tool listing."""
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "run_python" in names
