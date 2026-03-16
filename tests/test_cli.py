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

    def test_create_no_config(self, tmp_git_repo, mock_config_dir, monkeypatch):
        monkeypatch.chdir(tmp_git_repo)
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "create", "valid_name"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "init" in data["message"].lower()
