"""Pydantic models for input validation."""

import re
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator


# Domo dataset IDs are typically UUIDs or alphanumeric strings
DATASET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9\-_]+$")

# Maximum SQL query length (reasonable limit to prevent abuse)
MAX_SQL_LENGTH = 10000


class DatasetId(BaseModel):
    """Validated dataset ID."""

    dataset_id: str = Field(
        description="The Domo dataset ID (alphanumeric with hyphens/underscores)"
    )

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Dataset ID cannot be empty")
        v = v.strip()
        if not DATASET_ID_PATTERN.match(v):
            raise ValueError(
                "Dataset ID must contain only alphanumeric characters, hyphens, and underscores"
            )
        if len(v) > 100:
            raise ValueError("Dataset ID is too long (max 100 characters)")
        return v


class SqlQuery(BaseModel):
    """Validated SQL query."""

    sql: str = Field(description="The SQL query to execute")

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("SQL query cannot be empty")
        v = v.strip()
        if len(v) > MAX_SQL_LENGTH:
            raise ValueError(f"SQL query is too long (max {MAX_SQL_LENGTH} characters)")
        return v


class SearchQuery(BaseModel):
    """Validated search query."""

    query: str = Field(description="The search query string")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Search query cannot be empty")
        v = v.strip()
        if len(v) > 500:
            raise ValueError("Search query is too long (max 500 characters)")
        return v


class RoleId(BaseModel):
    """Validated role ID."""

    role_id: int = Field(description="The role ID (positive integer)")

    @field_validator("role_id")
    @classmethod
    def validate_role_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Role ID must be a positive integer")
        return v


class CreateRoleInput(BaseModel):
    """Validated input for creating a role."""

    name: str = Field(description="The name of the role")
    from_role_id: int = Field(description="The role ID to copy permissions from")
    description: Optional[str] = Field(default=None, description="Optional role description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Role name cannot be empty")
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Role name is too long (max 200 characters)")
        return v

    @field_validator("from_role_id")
    @classmethod
    def validate_from_role_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Source role ID must be a positive integer")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > 1000:
                raise ValueError("Description is too long (max 1000 characters)")
            return v if v else None
        return v


class AccessTokenId(BaseModel):
    """Validated access token ID."""

    token_id: int = Field(description="The access token ID (positive integer)")

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Token ID must be a positive integer")
        return v


class CreateAccessTokenInput(BaseModel):
    """Validated input for creating an access token."""

    name: str = Field(description="Display name for the access token")
    owner_id: int = Field(description="Domo user ID who will own the token")
    expires_in_days: int = Field(
        default=365, description="Token lifetime in days (default 1 year)"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Token name cannot be empty")
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Token name is too long (max 200 characters)")
        return v

    @field_validator("owner_id")
    @classmethod
    def validate_owner_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Owner ID must be a positive integer")
        return v

    @field_validator("expires_in_days")
    @classmethod
    def validate_expires_in_days(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Expiration must be at least 1 day")
        if v > 3650:
            raise ValueError("Expiration cannot exceed 3650 days (~10 years)")
        return v
