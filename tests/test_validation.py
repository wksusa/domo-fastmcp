"""Tests for input validation models."""

import pytest
from pydantic import ValidationError

from domo_mcp.validation import (
    CreateRoleInput,
    DatasetId,
    RoleId,
    SearchQuery,
    SqlQuery,
)


class TestDatasetId:
    """Tests for DatasetId validation."""

    def test_valid_dataset_id(self):
        """Valid dataset IDs should pass validation."""
        valid_ids = [
            "abc123",
            "ABC-123",
            "dataset_name_123",
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ]
        for id_value in valid_ids:
            result = DatasetId(dataset_id=id_value)
            assert result.dataset_id == id_value

    def test_empty_dataset_id(self):
        """Empty dataset ID should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            DatasetId(dataset_id="")
        assert "cannot be empty" in str(exc_info.value)

    def test_whitespace_only_dataset_id(self):
        """Whitespace-only dataset ID should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            DatasetId(dataset_id="   ")
        assert "cannot be empty" in str(exc_info.value)

    def test_invalid_characters_dataset_id(self):
        """Dataset ID with invalid characters should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            DatasetId(dataset_id="dataset!@#$%")
        assert "alphanumeric" in str(exc_info.value)

    def test_too_long_dataset_id(self):
        """Dataset ID exceeding max length should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            DatasetId(dataset_id="a" * 101)
        assert "too long" in str(exc_info.value)

    def test_dataset_id_whitespace_stripped(self):
        """Dataset ID should have whitespace stripped."""
        result = DatasetId(dataset_id="  abc123  ")
        assert result.dataset_id == "abc123"


class TestSqlQuery:
    """Tests for SqlQuery validation."""

    def test_valid_sql_query(self):
        """Valid SQL queries should pass validation."""
        valid_queries = [
            "SELECT * FROM table",
            "SELECT id, name FROM users WHERE id = 1",
            "SELECT COUNT(*) FROM orders GROUP BY status",
        ]
        for query in valid_queries:
            result = SqlQuery(sql=query)
            assert result.sql == query

    def test_empty_sql_query(self):
        """Empty SQL query should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SqlQuery(sql="")
        assert "cannot be empty" in str(exc_info.value)

    def test_whitespace_only_sql_query(self):
        """Whitespace-only SQL query should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SqlQuery(sql="   ")
        assert "cannot be empty" in str(exc_info.value)

    def test_too_long_sql_query(self):
        """SQL query exceeding max length should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SqlQuery(sql="SELECT " + "x" * 10001)
        assert "too long" in str(exc_info.value)

    def test_sql_query_whitespace_stripped(self):
        """SQL query should have whitespace stripped."""
        result = SqlQuery(sql="  SELECT * FROM table  ")
        assert result.sql == "SELECT * FROM table"


class TestSearchQuery:
    """Tests for SearchQuery validation."""

    def test_valid_search_query(self):
        """Valid search queries should pass validation."""
        valid_queries = ["sales", "customer data", "Q4 2024 report"]
        for query in valid_queries:
            result = SearchQuery(query=query)
            assert result.query == query

    def test_empty_search_query(self):
        """Empty search query should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchQuery(query="")
        assert "cannot be empty" in str(exc_info.value)

    def test_too_long_search_query(self):
        """Search query exceeding max length should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            SearchQuery(query="a" * 501)
        assert "too long" in str(exc_info.value)


class TestRoleId:
    """Tests for RoleId validation."""

    def test_valid_role_id(self):
        """Valid role IDs should pass validation."""
        valid_ids = [1, 100, 999999]
        for id_value in valid_ids:
            result = RoleId(role_id=id_value)
            assert result.role_id == id_value

    def test_zero_role_id(self):
        """Zero role ID should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            RoleId(role_id=0)
        assert "positive integer" in str(exc_info.value)

    def test_negative_role_id(self):
        """Negative role ID should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            RoleId(role_id=-1)
        assert "positive integer" in str(exc_info.value)


class TestCreateRoleInput:
    """Tests for CreateRoleInput validation."""

    def test_valid_create_role_input(self):
        """Valid role creation input should pass validation."""
        result = CreateRoleInput(
            name="Test Role",
            from_role_id=1,
            description="A test role",
        )
        assert result.name == "Test Role"
        assert result.from_role_id == 1
        assert result.description == "A test role"

    def test_valid_create_role_without_description(self):
        """Role creation without description should pass validation."""
        result = CreateRoleInput(name="Test Role", from_role_id=1)
        assert result.name == "Test Role"
        assert result.from_role_id == 1
        assert result.description is None

    def test_empty_role_name(self):
        """Empty role name should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            CreateRoleInput(name="", from_role_id=1)
        assert "cannot be empty" in str(exc_info.value)

    def test_too_long_role_name(self):
        """Role name exceeding max length should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            CreateRoleInput(name="a" * 201, from_role_id=1)
        assert "too long" in str(exc_info.value)

    def test_invalid_from_role_id(self):
        """Invalid from_role_id should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            CreateRoleInput(name="Test Role", from_role_id=0)
        assert "positive integer" in str(exc_info.value)

    def test_too_long_description(self):
        """Description exceeding max length should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            CreateRoleInput(name="Test Role", from_role_id=1, description="a" * 1001)
        assert "too long" in str(exc_info.value)

    def test_empty_description_becomes_none(self):
        """Empty string description should become None."""
        result = CreateRoleInput(name="Test Role", from_role_id=1, description="")
        assert result.description is None

    def test_whitespace_description_becomes_none(self):
        """Whitespace-only description should become None."""
        result = CreateRoleInput(name="Test Role", from_role_id=1, description="   ")
        assert result.description is None
