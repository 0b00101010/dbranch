from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import pymysql
from pymysql.cursors import DictCursor

from dbranch.config import ConnectionConfig


@contextmanager
def get_connection(
    conn_config: ConnectionConfig,
    database: str | None = None,
) -> Generator[pymysql.connections.Connection, None, None]:
    """Context manager for a MySQL connection."""
    conn = pymysql.connect(
        host=conn_config.host,
        port=conn_config.port,
        user=conn_config.user,
        password=conn_config.password,
        database=database,
        cursorclass=DictCursor,
        charset="utf8mb4",
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
    )
    try:
        yield conn
    finally:
        conn.close()


def test_connection(conn_config: ConnectionConfig) -> dict[str, Any]:
    """Test MySQL connection, return server info."""
    with get_connection(conn_config) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            row = cursor.fetchone()
            return {"version": row["version"]}


def execute_sql(
    conn_config: ConnectionConfig,
    sql: str,
    database: str | None = None,
) -> None:
    """Execute a SQL string (may contain multiple statements)."""
    with get_connection(conn_config, database=database) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
