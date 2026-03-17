from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from dbranch.config import ConnectionConfig, Config, TargetApp, HooksConfig, save_project_config
from dbranch.schema import METADATA_SCHEMA, METADATA_TABLE


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository and return its path."""
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return tmp_path


@pytest.fixture
def mock_config_dir(tmp_path: Path, monkeypatch):
    """Monkeypatch PROJECTS_DIR to a temporary directory."""
    import dbranch.config as config_mod

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(config_mod, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture
def sample_config_data(tmp_git_repo: Path) -> dict:
    """Return a valid config data dict with a real git_common_dir."""
    git_common_dir = str((tmp_git_repo / ".git").resolve())
    return {
        "git_common_dir": git_common_dir,
        "connection": {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "secret",
        },
        "schema_prefix": "test_",
        "targets": [
            {"path": "apps/web"},
            {"path": "apps/api", "env_key": "MYSQL_DB"},
        ],
        "hooks": {
            "post_create": [
                {"sql": "seed.sql"},
                {"shell": "echo done"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# MySQL integration test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mysql_conn_config():
    """Create ConnectionConfig from env vars, skip if MySQL is unavailable."""
    from dbranch.db import test_connection

    config = ConnectionConfig(
        host=os.environ.get("DBB_TEST_HOST", "localhost"),
        port=int(os.environ.get("DBB_TEST_PORT", "3306")),
        user=os.environ.get("DBB_TEST_USER", "root"),
        password=os.environ.get("DBB_TEST_PASSWORD", ""),
    )
    try:
        test_connection(config)
    except Exception as exc:
        pytest.skip(f"MySQL unavailable: {exc}")
    return config


@pytest.fixture
def mysql_cleanup(mysql_conn_config):
    """Track schema names created during test and drop them in teardown."""
    from dbranch.db import get_connection

    created: list[str] = []
    yield created
    # Teardown: drop all tracked schemas and delete their metadata rows
    with get_connection(mysql_conn_config) as conn:
        with conn.cursor() as cursor:
            # Check if metadata schema exists before attempting deletes
            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                "WHERE SCHEMA_NAME = %s",
                (METADATA_SCHEMA,),
            )
            has_metadata = cursor.fetchone() is not None

            for name in created:
                cursor.execute(f"DROP SCHEMA IF EXISTS `{name}`")
                if has_metadata:
                    cursor.execute(
                        f"DELETE FROM `{METADATA_SCHEMA}`.`{METADATA_TABLE}` "
                        f"WHERE schema_name = %s",
                        (name,),
                    )
        conn.commit()


@pytest.fixture
def cli_no_config_env(tmp_git_repo, mock_config_dir, monkeypatch):
    """Set up a git repo with mocked config dir but no saved config."""
    monkeypatch.chdir(tmp_git_repo)
    return tmp_git_repo


@pytest.fixture
def integration_config(tmp_git_repo, mock_config_dir, mysql_conn_config, monkeypatch):
    """Full Config wired to test MySQL + temp git repo + mock config dir.

    Saves config via save_project_config so load_config() works.
    Target points at a real directory inside tmp_git_repo.
    """
    import dbranch.config as config_mod

    monkeypatch.chdir(tmp_git_repo)

    git_common_dir = str((tmp_git_repo / ".git").resolve())
    project_name = "test_project"
    # Use a unique prefix to avoid collisions between parallel test runs
    prefix = f"dbb_t{uuid.uuid4().hex[:6]}_"

    # Create target directory inside the worktree
    target_dir = tmp_git_repo / "app"
    target_dir.mkdir(exist_ok=True)

    # Save raw config so load_config() can find it
    raw_data = {
        "git_common_dir": git_common_dir,
        "connection": {
            "host": mysql_conn_config.host,
            "port": mysql_conn_config.port,
            "user": mysql_conn_config.user,
            "password": mysql_conn_config.password,
        },
        "schema_prefix": prefix,
        "targets": [
            {"path": "app"},
        ],
    }
    save_project_config(project_name, raw_data)

    config = Config(
        project_name=project_name,
        git_common_dir=git_common_dir,
        connection=mysql_conn_config,
        schema_prefix=prefix,
        targets=[TargetApp(path="app")],
        hooks=HooksConfig(),
    )
    return config
