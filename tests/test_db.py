"""Integration tests for dbranch.db module (MySQL connection required)."""
from __future__ import annotations

import uuid

import pytest

from dbranch.db import test_connection as db_test_connection, execute_sql, get_connection


class TestDBConnection:
    """Tests that require a live MySQL connection."""

    def test_connection_success(self, mysql_conn_config):
        """test_connection() returns a dict with a version string."""
        result = db_test_connection(mysql_conn_config)
        assert "version" in result
        assert isinstance(result["version"], str)
        assert len(result["version"]) > 0

    def test_execute_sql(self, mysql_conn_config, mysql_cleanup):
        """execute_sql() can create a temp schema and we can verify it exists."""
        schema_name = f"_dbb_test_{uuid.uuid4().hex[:8]}"
        mysql_cleanup.append(schema_name)

        execute_sql(mysql_conn_config, f"CREATE SCHEMA `{schema_name}`")

        # Verify the schema exists
        with get_connection(mysql_conn_config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    "WHERE SCHEMA_NAME = %s",
                    (schema_name,),
                )
                row = cursor.fetchone()
                assert row is not None
                assert row["SCHEMA_NAME"] == schema_name
