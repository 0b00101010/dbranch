from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


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
