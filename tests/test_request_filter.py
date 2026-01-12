"""Tests for request filter middleware."""

import json
import pytest

from domo_mcp.request_filter import RequestFilterMiddleware, TOOL_PARAMETERS


class TestToolParameters:
    """Test that TOOL_PARAMETERS is correctly defined."""

    def test_all_tools_have_parameters_defined(self):
        """Ensure we have parameter definitions for expected tools."""
        expected_tools = {
            "get_dataset_schema",
            "get_dataset_metadata",
            "query_dataset",
            "search_datasets",
            "list_roles",
            "create_role",
            "list_role_authorities",
        }
        assert set(TOOL_PARAMETERS.keys()) == expected_tools

    def test_get_dataset_schema_parameters(self):
        assert TOOL_PARAMETERS["get_dataset_schema"] == {"dataset_id"}

    def test_query_dataset_parameters(self):
        assert TOOL_PARAMETERS["query_dataset"] == {"dataset_id", "sql"}

    def test_list_roles_has_no_parameters(self):
        assert TOOL_PARAMETERS["list_roles"] == set()

    def test_create_role_parameters(self):
        assert TOOL_PARAMETERS["create_role"] == {"name", "from_role_id", "description"}


class TestRequestFilterMiddleware:
    """Test the request filter middleware."""

    def test_filter_request_body_with_extra_fields(self):
        """Test that extra fields are stripped from tool call requests."""
        middleware = RequestFilterMiddleware(None)

        # Simulated n8n request with extra fields
        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_dataset_schema",
                "arguments": {
                    "dataset_id": "abc123",
                    # Extra fields from n8n that should be stripped
                    "id": "a91df285-a609-4e4f-a81b-49c66dd773bc",
                    "_xact_id": "1000196408583467833",
                    "project_id": "e03b26c4-5565-41d2-b4bf-01032c16d0da",
                    "toolCallId": "call_AXNV1HHuAJjWnN7ngzjvh609",
                    "metadata": None,
                }
            }
        }

        body = json.dumps(request_body).encode()
        filtered = middleware._filter_request_body(body)
        result = json.loads(filtered)

        # Should only have dataset_id
        assert result["params"]["arguments"] == {"dataset_id": "abc123"}

    def test_filter_request_body_preserves_valid_fields(self):
        """Test that valid fields are preserved."""
        middleware = RequestFilterMiddleware(None)

        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "query_dataset",
                "arguments": {
                    "dataset_id": "abc123",
                    "sql": "SELECT * FROM table",
                }
            }
        }

        body = json.dumps(request_body).encode()
        filtered = middleware._filter_request_body(body)
        result = json.loads(filtered)

        assert result["params"]["arguments"] == {
            "dataset_id": "abc123",
            "sql": "SELECT * FROM table",
        }

    def test_filter_request_body_ignores_non_tool_calls(self):
        """Test that non-tool-call requests are passed through unchanged."""
        middleware = RequestFilterMiddleware(None)

        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"extra": "field"}
        }

        body = json.dumps(request_body).encode()
        filtered = middleware._filter_request_body(body)

        # Should be unchanged
        assert filtered == body

    def test_filter_request_body_handles_unknown_tool(self):
        """Test that unknown tools are passed through unchanged."""
        middleware = RequestFilterMiddleware(None)

        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "unknown_tool",
                "arguments": {"some": "args"}
            }
        }

        body = json.dumps(request_body).encode()
        filtered = middleware._filter_request_body(body)

        # Should be unchanged since tool is unknown
        assert filtered == body

    def test_filter_request_body_handles_empty_body(self):
        """Test that empty body is handled."""
        middleware = RequestFilterMiddleware(None)

        filtered = middleware._filter_request_body(b"")
        assert filtered == b""

    def test_filter_request_body_handles_invalid_json(self):
        """Test that invalid JSON is passed through unchanged."""
        middleware = RequestFilterMiddleware(None)

        body = b"not valid json"
        filtered = middleware._filter_request_body(body)
        assert filtered == body

    def test_filter_request_body_tool_with_no_parameters(self):
        """Test filtering for a tool with no expected parameters."""
        middleware = RequestFilterMiddleware(None)

        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_roles",
                "arguments": {
                    # All extra fields from n8n
                    "id": "a91df285-a609-4e4f-a81b-49c66dd773bc",
                    "toolCallId": "call_123",
                }
            }
        }

        body = json.dumps(request_body).encode()
        filtered = middleware._filter_request_body(body)
        result = json.loads(filtered)

        # Should be empty since list_roles takes no parameters
        assert result["params"]["arguments"] == {}
