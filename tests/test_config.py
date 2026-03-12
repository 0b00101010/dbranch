"""Tests for config parsing, git helpers, and config load/save."""
from __future__ import annotations

import pytest

from dbranch.config import _parse_hooks, _parse_targets, HookStep, TargetApp


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
