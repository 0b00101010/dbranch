from __future__ import annotations

import subprocess
from pathlib import Path
from dataclasses import dataclass, field

import yaml


CONFIG_DIR = Path.home() / ".config" / "dbranch"
PROJECTS_DIR = CONFIG_DIR / "projects"


@dataclass
class ConnectionConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""


@dataclass
class TargetApp:
    """An app directory that receives a .env.db-schema file on create."""
    path: str  # relative to worktree root, e.g. "apps/mysql-use-project"
    env_file: str = ".env.db-schema"
    env_key: str = "DB_NAME"


@dataclass
class HookStep:
    """A single post-create hook step."""
    type: str  # "sql" or "shell"
    value: str  # file path for sql, command string for shell


@dataclass
class HooksConfig:
    post_create: list[HookStep] = field(default_factory=list)


@dataclass
class Config:
    project_name: str = ""
    git_common_dir: str = ""
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    schema_prefix: str = "dbb_"
    targets: list[TargetApp] = field(default_factory=list)
    hooks: HooksConfig = field(default_factory=HooksConfig)


def get_git_common_dir() -> str:
    """Get the git common dir (shared across worktrees)."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository.")
    return str(Path(result.stdout.strip()).resolve())


def get_git_toplevel() -> Path:
    """Get the current worktree's root directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository.")
    return Path(result.stdout.strip()).resolve()


def find_project_config() -> tuple[Path, str] | None:
    """Find project config by matching git common dir.
    Returns (config_path, project_name) or None.
    """
    if not PROJECTS_DIR.is_dir():
        return None

    try:
        current_common = get_git_common_dir()
    except RuntimeError:
        return None

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        config_path = project_dir / "config.yaml"
        if not config_path.is_file():
            continue
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        if raw.get("git_common_dir") == current_common:
            return config_path, project_dir.name

    return None


def _parse_hooks(raw: dict) -> HooksConfig:
    hooks = HooksConfig()
    for item in raw.get("post_create", []):
        if "sql" in item:
            hooks.post_create.append(HookStep(type="sql", value=item["sql"]))
        elif "shell" in item:
            hooks.post_create.append(HookStep(type="shell", value=item["shell"]))
    return hooks


def _parse_targets(raw: list) -> list[TargetApp]:
    targets = []
    for item in raw:
        targets.append(TargetApp(
            path=item["path"],
            env_file=item.get("env_file", ".env.db-schema"),
            env_key=item.get("env_key", "DB_NAME"),
        ))
    return targets


def load_config() -> Config:
    """Load project config by auto-detecting git repo."""
    result = find_project_config()
    if result is None:
        raise FileNotFoundError(
            "No DBranch config found for this repository. Run 'dbb init' first."
        )

    config_path, project_name = result

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    conn_raw = raw.get("connection", {})

    connection = ConnectionConfig(
        host=conn_raw.get("host", "localhost"),
        port=int(conn_raw.get("port", 3306)),
        user=conn_raw.get("user", "root"),
        password=str(conn_raw.get("password", "")),
    )

    hooks = _parse_hooks(raw.get("hooks", {}))
    targets = _parse_targets(raw.get("targets", []))

    return Config(
        project_name=project_name,
        git_common_dir=raw.get("git_common_dir", ""),
        connection=connection,
        schema_prefix=raw.get("schema_prefix", "dbb_"),
        targets=targets,
        hooks=hooks,
    )


def save_project_config(project_name: str, data: dict) -> Path:
    """Save config to ~/.config/dbranch/projects/<name>/config.yaml."""
    project_dir = PROJECTS_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    config_path = project_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return config_path
