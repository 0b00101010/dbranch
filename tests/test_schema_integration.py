"""Integration tests for schema operations (MySQL required)."""
from __future__ import annotations

import uuid

import pytest

from dbranch.db import get_connection
from dbranch.schema import (
    METADATA_SCHEMA,
    METADATA_TABLE,
    create_schema,
    clone_schema,
    full_schema_name,
    list_schemas,
    get_status,
)


def _unique_name() -> str:
    """Generate a unique logical schema name for test isolation."""
    return f"t_{uuid.uuid4().hex[:8]}"


class TestCreateSchema:
    """Integration tests for create_schema()."""

    def test_create_basic(self, integration_config, mysql_cleanup, monkeypatch):
        """create_schema creates a schema that exists in MySQL."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        result = create_schema(integration_config, name)

        assert result["schema_name"] == schema
        assert result["logical_name"] == name

        # Verify it actually exists in MySQL
        with get_connection(integration_config.connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    "WHERE SCHEMA_NAME = %s",
                    (schema,),
                )
                row = cursor.fetchone()
                assert row is not None

    def test_create_duplicate_raises(self, integration_config, mysql_cleanup, monkeypatch):
        """Creating the same logical name twice raises ValueError."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        create_schema(integration_config, name)

        with pytest.raises(ValueError, match="already exists"):
            create_schema(integration_config, name)

    def test_create_writes_env_file(self, integration_config, mysql_cleanup, tmp_git_repo, monkeypatch):
        """create_schema writes a .env.db-schema file with the correct content."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        result = create_schema(integration_config, name)

        env_path = tmp_git_repo / "app" / ".env.db-schema"
        assert env_path.is_file()
        content = env_path.read_text()
        assert f"DB_NAME={schema}" in content

    def test_create_with_description(self, integration_config, mysql_cleanup, monkeypatch):
        """create_schema stores description in the metadata table."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)
        desc = "test description for integration"

        create_schema(integration_config, name, description=desc)

        with get_connection(integration_config.connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT description FROM `{METADATA_SCHEMA}`.`{METADATA_TABLE}` "
                    f"WHERE schema_name = %s",
                    (schema,),
                )
                row = cursor.fetchone()
                assert row is not None
                assert row["description"] == desc
