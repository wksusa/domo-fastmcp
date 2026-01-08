"""Shared test fixtures and configuration."""

import pytest


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""

    class MockLogger:
        def __init__(self):
            self.messages = {"info": [], "warning": [], "error": []}

        def info(self, message: str) -> None:
            self.messages["info"].append(message)

        def warning(self, message: str) -> None:
            self.messages["warning"].append(message)

        def error(self, message: str) -> None:
            self.messages["error"].append(message)

    return MockLogger()


@pytest.fixture
def sample_dataset_response():
    """Sample dataset metadata response."""
    return {
        "id": "abc123-def456",
        "name": "Test Dataset",
        "description": "A test dataset",
        "rows": 1000,
        "columns": 5,
    }


@pytest.fixture
def sample_schema_response():
    """Sample dataset schema response."""
    return {
        "columns": [
            {"name": "id", "type": "LONG"},
            {"name": "name", "type": "STRING"},
            {"name": "value", "type": "DOUBLE"},
        ]
    }


@pytest.fixture
def sample_query_response():
    """Sample query result response."""
    return {
        "columns": ["id", "name", "value"],
        "rows": [
            [1, "Item 1", 100.0],
            [2, "Item 2", 200.0],
        ],
    }


@pytest.fixture
def sample_roles_response():
    """Sample roles list response."""
    return [
        {"id": 1, "name": "Admin", "description": "Administrator role"},
        {"id": 2, "name": "Viewer", "description": "Read-only access"},
    ]
