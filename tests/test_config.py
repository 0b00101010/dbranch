"""Tests for config parsing, git helpers, and config load/save."""
from __future__ import annotations

import pytest

import subprocess
from pathlib import Path

from dbranch.config import (
    _parse_hooks,
    _parse_targets,
    find_project_config,
    get_git_common_dir,
    get_git_toplevel,
    load_config,
    save_project_config,
    HookStep,
    TargetApp,
)


class TestParseHooks:
    """Tests for _parse_hooks()."""

    def test_empty(self):
        result = _parse_hooks({})
        assert result.post_create == []

    def test_sql_hook(self):
        raw = {"post_create": [{"sql": "seed.sql"}]}
        result = _parse_hooks(raw)
        assert len(result.post_create) == 1
        assert result.post_create[0] == HookStep(type="sql", value="seed.sql")

    def test_shell_hook(self):
        raw = {"post_create": [{"shell": "echo hello"}]}
        result = _parse_hooks(raw)
        assert len(result.post_create) == 1
        assert result.post_create[0] == HookStep(type="shell", value="echo hello")

    def test_mixed_hooks(self):
        raw = {
            "post_create": [
                {"sql": "schema.sql"},
                {"shell": "make migrate"},
                {"sql": "seed.sql"},
            ]
        }
        result = _parse_hooks(raw)
        assert len(result.post_create) == 3
        assert result.post_create[0].type == "sql"
        assert result.post_create[1].type == "shell"
        assert result.post_create[2].type == "sql"

    def test_unknown_type_ignored(self):
        raw = {"post_create": [{"python": "run.py"}, {"sql": "seed.sql"}]}
        result = _parse_hooks(raw)
        assert len(result.post_create) == 1
        assert result.post_create[0].type == "sql"


class TestParseTargets:
    """Tests for _parse_targets()."""

    def test_empty(self):
        result = _parse_targets([])
        assert result == []

    def test_single_with_defaults(self):
        raw = [{"path": "apps/web"}]
        result = _parse_targets(raw)
        assert len(result) == 1
        assert result[0].path == "apps/web"
        assert result[0].env_file == ".env.db-schema"
        assert result[0].env_key == "DB_NAME"

    def test_custom_env_settings(self):
        raw = [{"path": "api", "env_file": ".env.local", "env_key": "DATABASE_URL"}]
        result = _parse_targets(raw)
        assert result[0].env_file == ".env.local"
        assert result[0].env_key == "DATABASE_URL"

    def test_multiple_targets(self):
        raw = [
            {"path": "apps/web"},
            {"path": "apps/api", "env_key": "MYSQL_DB"},
        ]
        result = _parse_targets(raw)
        assert len(result) == 2
        assert result[0].path == "apps/web"
        assert result[1].path == "apps/api"
        assert result[1].env_key == "MYSQL_DB"


class TestGetGitCommonDir:
    """Tests for get_git_common_dir()."""

    def test_success(self, tmp_git_repo, monkeypatch):
        monkeypatch.chdir(tmp_git_repo)
        result = get_git_common_dir()
        expected = str((tmp_git_repo / ".git").resolve())
        assert result == expected

    def test_not_a_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="Not inside a git repository"):
            get_git_common_dir()


class TestGetGitToplevel:
    """Tests for get_git_toplevel()."""

    def test_success(self, tmp_git_repo, monkeypatch):
        monkeypatch.chdir(tmp_git_repo)
        result = get_git_toplevel()
        assert result == tmp_git_repo.resolve()

    def test_not_a_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="Not inside a git repository"):
            get_git_toplevel()


class TestSaveProjectConfig:
    """Tests for save_project_config()."""

    def test_save_creates_file(self, mock_config_dir, sample_config_data):
        path = save_project_config("myproject", sample_config_data)
        assert path.is_file()
        assert path == mock_config_dir / "myproject" / "config.yaml"


class TestFindProjectConfig:
    """Tests for find_project_config()."""

    def test_find_matches(
        self, tmp_git_repo, mock_config_dir, sample_config_data, monkeypatch
    ):
        monkeypatch.chdir(tmp_git_repo)
        save_project_config("myproject", sample_config_data)
        result = find_project_config()
        assert result is not None
        config_path, project_name = result
        assert project_name == "myproject"
        assert config_path.is_file()

    def test_find_no_match(self, tmp_git_repo, mock_config_dir, monkeypatch):
        monkeypatch.chdir(tmp_git_repo)
        # No config saved, so no match
        result = find_project_config()
        assert result is None


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_success(
        self, tmp_git_repo, mock_config_dir, sample_config_data, monkeypatch
    ):
        monkeypatch.chdir(tmp_git_repo)
        save_project_config("myproject", sample_config_data)

        config = load_config()
        assert config.project_name == "myproject"
        assert config.git_common_dir == sample_config_data["git_common_dir"]
        assert config.connection.host == "localhost"
        assert config.connection.port == 3306
        assert config.connection.user == "root"
        assert config.connection.password == "secret"
        assert config.schema_prefix == "test_"
        assert len(config.targets) == 2
        assert config.targets[0].path == "apps/web"
        assert config.targets[1].env_key == "MYSQL_DB"
        assert len(config.hooks.post_create) == 2
        assert config.hooks.post_create[0].type == "sql"
        assert config.hooks.post_create[1].type == "shell"

    def test_load_not_found_raises(self, tmp_git_repo, mock_config_dir, monkeypatch):
        monkeypatch.chdir(tmp_git_repo)
        with pytest.raises(FileNotFoundError, match="No DBranch config found"):
            load_config()
