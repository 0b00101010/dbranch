"""Tests for config parsing, git helpers, and config load/save."""
from __future__ import annotations

import pytest

import os
import subprocess
from pathlib import Path

from dbranch.config import (
    _parse_hooks,
    _parse_targets,
    get_git_common_dir,
    get_git_toplevel,
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
