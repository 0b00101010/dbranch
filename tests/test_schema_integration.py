"""Integration tests for schema operations (MySQL required)."""
from __future__ import annotations

import uuid

import pytest

from dbranch.db import get_connection, execute_sql
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


class TestListSchemas:
    """Integration tests for list_schemas()."""

    def test_list_empty(self, integration_config, mysql_cleanup):
        """list_schemas returns a list (possibly empty) when no schemas created."""
        result = list_schemas(integration_config)
        assert isinstance(result, list)

    def test_list_after_create(self, integration_config, mysql_cleanup, monkeypatch):
        """Created schema appears in list_schemas results."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        create_schema(integration_config, name)
        result = list_schemas(integration_config)

        schema_names = [r["schema_name"] for r in result]
        assert schema in schema_names

    def test_list_older_than_filters(self, integration_config, mysql_cleanup, monkeypatch):
        """A just-created schema is excluded by older_than='1d' filter."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        create_schema(integration_config, name)
        result = list_schemas(integration_config, older_than="1d")

        schema_names = [r["schema_name"] for r in result]
        assert schema not in schema_names


class TestCloneSchema:
    """Integration tests for clone_schema()."""

    def test_clone_basic(self, integration_config, mysql_cleanup, monkeypatch):
        """Clone copies table structure and data."""
        source_name = _unique_name()
        source_schema = full_schema_name(integration_config.schema_prefix, source_name)
        mysql_cleanup.append(source_schema)

        create_schema(integration_config, source_name)

        # Insert a table with data into the source schema
        conn_cfg = integration_config.connection
        execute_sql(
            conn_cfg,
            "CREATE TABLE test_tbl (id INT PRIMARY KEY, val VARCHAR(50))",
            database=source_schema,
        )
        execute_sql(
            conn_cfg,
            "INSERT INTO test_tbl (id, val) VALUES (1, 'hello'), (2, 'world')",
            database=source_schema,
        )

        # Clone it
        clone_name = _unique_name()
        clone_schema_name = full_schema_name(integration_config.schema_prefix, clone_name)
        mysql_cleanup.append(clone_schema_name)

        result = clone_schema(integration_config, source_name, clone_name)

        assert result["schema_name"] == clone_schema_name
        assert result["cloned_from"] == source_schema
        assert result["tables_cloned"] == 1

        # Verify data was copied
        with get_connection(conn_cfg, database=clone_schema_name) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM test_tbl")
                row = cursor.fetchone()
                assert row["cnt"] == 2

    def test_clone_nonexistent_source_raises(self, integration_config, mysql_cleanup, monkeypatch):
        """Cloning from a non-existent source raises ValueError."""
        clone_name = _unique_name()
        clone_schema_name = full_schema_name(integration_config.schema_prefix, clone_name)
        mysql_cleanup.append(clone_schema_name)

        with pytest.raises(ValueError, match="does not exist"):
            clone_schema(integration_config, "nonexistent_src_xyz", clone_name)

    def test_clone_target_exists_raises(self, integration_config, mysql_cleanup, monkeypatch):
        """Cloning into an already-existing target raises ValueError."""
        source_name = _unique_name()
        source_schema = full_schema_name(integration_config.schema_prefix, source_name)
        mysql_cleanup.append(source_schema)
        create_schema(integration_config, source_name)

        target_name = _unique_name()
        target_schema = full_schema_name(integration_config.schema_prefix, target_name)
        mysql_cleanup.append(target_schema)
        create_schema(integration_config, target_name)

        with pytest.raises(ValueError, match="already exists"):
            clone_schema(integration_config, source_name, target_name)


class TestGetStatus:
    """Integration tests for get_status()."""

    def test_status_no_env_file(self, integration_config, mysql_cleanup, monkeypatch):
        """When no .env.db-schema exists, configured should be False."""
        result = get_status(integration_config)

        assert "targets" in result
        assert len(result["targets"]) == 1
        target = result["targets"][0]
        assert target["configured"] is False
        assert target["exists_in_db"] is False

    def test_status_after_create(self, integration_config, mysql_cleanup, monkeypatch):
        """After create_schema, configured=True and exists_in_db=True."""
        name = _unique_name()
        schema = full_schema_name(integration_config.schema_prefix, name)
        mysql_cleanup.append(schema)

        create_schema(integration_config, name)

        result = get_status(integration_config)

        assert len(result["targets"]) == 1
        target = result["targets"][0]
        assert target["configured"] is True
        assert target["schema_name"] == schema
        assert target["exists_in_db"] is True
