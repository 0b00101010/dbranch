from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from dbranch.cli import cli


class TestCreateCLI:
    def test_create_rejects_slash(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "create", "feature/bar"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert "/" in data["message"]

    def test_create_rejects_hyphen(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "create", "feature-bar"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_create_rejects_empty_name(self):
        runner = CliRunner()
        # Click will show usage error for missing argument
        result = runner.invoke(cli, ["--json", "create"])
        assert result.exit_code != 0

    def test_create_no_config(self, cli_no_config_env):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "create", "valid_name"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "init" in data["message"].lower()


class TestLsCLI:
    def test_ls_no_config(self, cli_no_config_env):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "ls"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_ls_invalid_duration(self, cli_no_config_env):
        """ls with bad --older-than should fail, but only if config exists first."""
        runner = CliRunner()
        # Without config it fails on config lookup first
        result = runner.invoke(cli, ["--json", "ls", "--older-than", "abc"])
        assert result.exit_code == 1


class TestStatusCLI:
    def test_status_no_config(self, cli_no_config_env):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "status"])
        assert result.exit_code == 1

    def test_status_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "worktree" in result.output.lower()


class TestCloneCLI:
    def test_clone_rejects_slash_in_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "clone", "feature/bar", "valid"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "/" in data["message"]

    def test_clone_rejects_slash_in_target(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "clone", "valid", "feature/bar"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_clone_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["clone", "--help"])
        assert result.exit_code == 0
        assert "source" in result.output.lower()


class TestConfigShowCLI:
    def test_config_show_no_config(self, cli_no_config_env):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "config", "show"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_config_show_with_config(
        self, cli_no_config_env, sample_config_data
    ):
        from dbranch.config import save_project_config
        save_project_config("testproject", sample_config_data)

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "config", "show"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project_name"] == "testproject"
        assert "connection" in data
        assert data["connection"]["password"] == "***"
