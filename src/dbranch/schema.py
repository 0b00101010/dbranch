from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pymysql

from dbranch.config import Config, HookStep, TargetApp, get_git_toplevel, ConnectionConfig
from dbranch.db import get_connection, execute_sql

# Schema name: alphanumeric and underscore only, no leading digit
VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
MYSQL_MAX_SCHEMA_LENGTH = 64

METADATA_SCHEMA = "_dbb_metadata"
METADATA_TABLE = "managed_schemas"

METADATA_DDL = f"""\
CREATE SCHEMA IF NOT EXISTS `{METADATA_SCHEMA}`;
CREATE TABLE IF NOT EXISTS `{METADATA_SCHEMA}`.`{METADATA_TABLE}` (
    schema_name VARCHAR(64) NOT NULL PRIMARY KEY,
    logical_name VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def validate_name(name: str) -> str | None:
    """Validate a logical schema name. Returns error message or None."""
    if "/" in name:
        return "Schema name must not contain '/'. Use underscores instead."
    if not VALID_NAME_PATTERN.match(name):
        return (
            "Schema name must start with a letter or underscore, "
            "and contain only alphanumeric characters and underscores."
        )
    return None


def full_schema_name(prefix: str, logical_name: str) -> str:
    """Build the actual MySQL schema name."""
    full = f"{prefix}{logical_name}"
    if len(full) > MYSQL_MAX_SCHEMA_LENGTH:
        raise ValueError(
            f"Full schema name '{full}' exceeds MySQL's "
            f"{MYSQL_MAX_SCHEMA_LENGTH}-character limit."
        )
    return full


def ensure_metadata(config: Config) -> None:
    """Create the metadata schema and table if they don't exist."""
    execute_sql(config.connection, METADATA_DDL)


def _write_env_files(
    config: Config,
    schema_name: str,
    worktree_root: Path,
) -> list[str]:
    """Write .env.db-schema files for each target app. Returns list of written paths."""
    written = []
    for target in config.targets:
        target_dir = (worktree_root / target.path).resolve()
        if not target_dir.is_dir():
            target_dir.mkdir(parents=True, exist_ok=True)

        env_path = target_dir / target.env_file
        env_path.write_text(f"{target.env_key}={schema_name}\n")
        written.append(str(env_path))

    return written


def create_schema(
    config: Config,
    logical_name: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a new managed schema. Returns info dict."""
    schema = full_schema_name(config.schema_prefix, logical_name)
    worktree_root = get_git_toplevel()

    ensure_metadata(config)

    with get_connection(config.connection) as conn:
        with conn.cursor() as cursor:
            # Check if already exists
            cursor.execute(
                f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                f"WHERE SCHEMA_NAME = %s",
                (schema,),
            )
            if cursor.fetchone():
                raise ValueError(f"Schema '{schema}' already exists.")

            # Create the schema
            cursor.execute(f"CREATE SCHEMA `{schema}`")

            # Register in metadata
            cursor.execute(
                f"INSERT INTO `{METADATA_SCHEMA}`.`{METADATA_TABLE}` "
                f"(schema_name, logical_name, description) VALUES (%s, %s, %s)",
                (schema, logical_name, description),
            )
        conn.commit()

    # Write env files to target apps
    env_files = _write_env_files(config, schema, worktree_root)

    # Run post-create hooks
    _run_hooks(config, schema, worktree_root)

    return {
        "schema_name": schema,
        "logical_name": logical_name,
        "created_at": datetime.now().isoformat(),
        "env_files": env_files,
    }


def _run_hooks(config: Config, schema_name: str, worktree_root: Path) -> None:
    """Execute post-create hooks."""
    for step in config.hooks.post_create:
        if step.type == "sql":
            _run_sql_hook(config, schema_name, step.value, worktree_root)
        elif step.type == "shell":
            _run_shell_hook(schema_name, step.value, worktree_root)


def _run_sql_hook(
    config: Config,
    schema_name: str,
    file_path: str,
    worktree_root: Path,
) -> None:
    """Read and execute a SQL hook file with template substitution."""
    resolved = (worktree_root / file_path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"SQL hook file not found: {resolved}")

    sql = resolved.read_text()
    sql = sql.replace("{schema_name}", schema_name)
    execute_sql(config.connection, sql, database=schema_name)


def _run_shell_hook(
    schema_name: str,
    command: str,
    worktree_root: Path,
) -> None:
    """Execute a shell hook command."""
    env = {**os.environ, "SCHEMA_NAME": schema_name}
    result = subprocess.run(
        command,
        shell=True,
        cwd=str(worktree_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Shell hook failed (exit {result.returncode}): {result.stderr}"
        )


def _parse_duration(duration_str: str) -> timedelta:
    """Parse a duration string like '7d', '24h', '2w' into a timedelta."""
    match = re.match(r"^(\d+)([dhw])$", duration_str.strip())
    if not match:
        raise ValueError(
            f"Invalid duration '{duration_str}'. Use format like '7d', '24h', '2w'."
        )
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return timedelta(days=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "w":
        return timedelta(weeks=value)
    raise ValueError(f"Unknown duration unit: {unit}")


def list_schemas(
    config: Config,
    older_than: str | None = None,
) -> list[dict[str, Any]]:
    """List all managed schemas."""
    ensure_metadata(config)

    query = (
        f"SELECT m.schema_name, m.logical_name, m.created_at, m.description "
        f"FROM `{METADATA_SCHEMA}`.`{METADATA_TABLE}` m "
        f"INNER JOIN information_schema.SCHEMATA s "
        f"ON s.SCHEMA_NAME = m.schema_name"
    )
    params: list[Any] = []

    if older_than:
        delta = _parse_duration(older_than)
        cutoff = datetime.now() - delta
        query += " WHERE m.created_at < %s"
        params.append(cutoff)

    query += " ORDER BY m.created_at DESC"

    with get_connection(config.connection) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or None)
            rows = cursor.fetchall()

    return [
        {
            "schema_name": row["schema_name"],
            "logical_name": row["logical_name"],
            "created_at": row["created_at"].isoformat()
            if isinstance(row["created_at"], datetime)
            else str(row["created_at"]),
            "description": row["description"] or "",
        }
        for row in rows
    ]


def get_status(config: Config) -> dict[str, Any]:
    """Read current worktree's .env.db-schema files and return status."""
    worktree_root = get_git_toplevel()
    targets_status = []

    for target in config.targets:
        target_dir = (worktree_root / target.path).resolve()
        env_path = target_dir / target.env_file

        entry: dict[str, Any] = {
            "target_path": target.path,
            "env_file": str(env_path),
            "configured": False,
            "schema_name": None,
        }

        if env_path.is_file():
            content = env_path.read_text().strip()
            for line in content.splitlines():
                if line.startswith(f"{target.env_key}="):
                    entry["schema_name"] = line.split("=", 1)[1]
                    entry["configured"] = True
                    break

        targets_status.append(entry)

    # Check if the schemas actually exist in MySQL
    if any(t["schema_name"] for t in targets_status):
        schema_names = [t["schema_name"] for t in targets_status if t["schema_name"]]
        with get_connection(config.connection) as conn:
            with conn.cursor() as cursor:
                placeholders = ",".join(["%s"] * len(schema_names))
                cursor.execute(
                    f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    f"WHERE SCHEMA_NAME IN ({placeholders})",
                    schema_names,
                )
                existing = {row["SCHEMA_NAME"] for row in cursor.fetchall()}

        for entry in targets_status:
            if entry["schema_name"]:
                entry["exists_in_db"] = entry["schema_name"] in existing
    else:
        for entry in targets_status:
            entry["exists_in_db"] = False

    return {
        "worktree_root": str(worktree_root),
        "project_name": config.project_name,
        "targets": targets_status,
    }


def clone_schema(
    config: Config,
    source_name: str,
    new_name: str,
    description: str = "",
) -> dict[str, Any]:
    """Clone an existing schema (structure + data) into a new one."""
    source_schema = full_schema_name(config.schema_prefix, source_name)
    new_schema = full_schema_name(config.schema_prefix, new_name)
    worktree_root = get_git_toplevel()

    ensure_metadata(config)

    with get_connection(config.connection) as conn:
        with conn.cursor() as cursor:
            # Verify source exists
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME = %s",
                (source_schema,),
            )
            if not cursor.fetchone():
                raise ValueError(f"Source schema '{source_schema}' does not exist.")

            # Check new doesn't exist
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME = %s",
                (new_schema,),
            )
            if cursor.fetchone():
                raise ValueError(f"Schema '{new_schema}' already exists.")

            # Create new schema
            cursor.execute(f"CREATE SCHEMA `{new_schema}`")

            # Get all tables from source
            cursor.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
                (source_schema,),
            )
            tables = [row["TABLE_NAME"] for row in cursor.fetchall()]

            # Clone each table (structure + data)
            for table in tables:
                cursor.execute(
                    f"CREATE TABLE `{new_schema}`.`{table}` "
                    f"LIKE `{source_schema}`.`{table}`"
                )
                cursor.execute(
                    f"INSERT INTO `{new_schema}`.`{table}` "
                    f"SELECT * FROM `{source_schema}`.`{table}`"
                )

            # Clone views
            cursor.execute(
                "SELECT TABLE_NAME, VIEW_DEFINITION FROM information_schema.VIEWS "
                "WHERE TABLE_SCHEMA = %s",
                (source_schema,),
            )
            views = cursor.fetchall()
            views_cloned = 0
            for view in views:
                view_name = view["TABLE_NAME"]
                view_def = view["VIEW_DEFINITION"]
                # Rewrite schema references in view definition
                view_def = view_def.replace(f"`{source_schema}`.", f"`{new_schema}`.")
                cursor.execute(
                    f"CREATE VIEW `{new_schema}`.`{view_name}` AS {view_def}"
                )
                views_cloned += 1

            # Clone routines (procedures and functions).
            # Uses SHOW CREATE to get the full DDL including parameter lists.
            cursor.execute(
                "SELECT ROUTINE_NAME, ROUTINE_TYPE "
                "FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = %s",
                (source_schema,),
            )
            routines = cursor.fetchall()
            routines_cloned = 0
            for routine in routines:
                r_name = routine["ROUTINE_NAME"]
                r_type = routine["ROUTINE_TYPE"]
                try:
                    cursor.execute(
                        f"SHOW CREATE {r_type} `{source_schema}`.`{r_name}`"
                    )
                    show_row = cursor.fetchone()
                    # Key varies: "Create Procedure" or "Create Function"
                    ddl = None
                    for key in show_row:
                        if key.lower().startswith("create"):
                            ddl = show_row[key]
                            break
                    if not ddl:
                        continue
                    # Remove DEFINER clause so the routine is created with
                    # the current user's privileges
                    ddl = re.sub(
                        r"DEFINER\s*=\s*`[^`]*`@`[^`]*`\s*",
                        "",
                        ddl,
                    )
                    # Rewrite schema references in the body
                    ddl = ddl.replace(f"`{source_schema}`.", f"`{new_schema}`.")
                    # Replace the unqualified routine name in the CREATE header
                    # with a schema-qualified name so it lands in new_schema.
                    ddl = ddl.replace(
                        f"CREATE {r_type} `{r_name}`",
                        f"CREATE {r_type} `{new_schema}`.`{r_name}`",
                        1,
                    )
                    cursor.execute(ddl)
                    routines_cloned += 1
                except Exception:
                    # Skip routines that can't be cloned (e.g., permission issues)
                    pass

            # Register in metadata
            cursor.execute(
                f"INSERT INTO `{METADATA_SCHEMA}`.`{METADATA_TABLE}` "
                f"(schema_name, logical_name, description) VALUES (%s, %s, %s)",
                (new_schema, new_name, description or f"Cloned from {source_name}"),
            )
        conn.commit()

    # Write env files
    env_files = _write_env_files(config, new_schema, worktree_root)

    # Run post-create hooks
    _run_hooks(config, new_schema, worktree_root)

    return {
        "schema_name": new_schema,
        "logical_name": new_name,
        "cloned_from": source_schema,
        "tables_cloned": len(tables),
        "views_cloned": views_cloned,
        "routines_cloned": routines_cloned,
        "created_at": datetime.now().isoformat(),
        "env_files": env_files,
    }
