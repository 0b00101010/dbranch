from __future__ import annotations

import json
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table

from dbranch.config import (
    PROJECTS_DIR,
    find_project_config,
    get_git_common_dir,
    get_git_toplevel,
    load_config,
    save_project_config,
)
from dbranch.db import test_connection
from dbranch.schema import (
    clone_schema,
    create_schema,
    get_status,
    list_schemas,
    validate_name,
    full_schema_name,
)

console = Console()
err_console = Console(stderr=True)


MAIN_HELP = """\
DBranch (dbb) - Database branching for parallel worktree development.

Manages isolated MySQL schemas so that multiple git worktrees (or branches)
can each have their own database without conflicts.

\b
QUICK START (for humans):
  1. cd <your-monorepo-root>
  2. dbb init              # one-time interactive setup
  3. dbb create my_feature # create an isolated schema

\b
USAGE BY AI AGENTS:
  All commands support --json for machine-readable output.
  Typical agent workflow:
    dbb --json status                        # check current worktree schema
    dbb --json create <name>                 # create new isolated schema
    dbb --json clone <source> <new_name>     # clone existing schema with data
    dbb --json ls                            # list all managed schemas

\b
GLOBAL OPTIONS:
  --json    Output JSON instead of human-readable text.
            JSON output goes to stdout; errors also use JSON format.

\b
CONFIG LOCATION:
  ~/.config/dbranch/projects/<project-name>/config.yaml
  Config is auto-detected by matching the current git repository.

\b
SCHEMA NAMING:
  Names must use only [a-zA-Z0-9_] (no '/' or special characters).
  The configured prefix (default: 'dbb_') is prepended automatically.
  Example: 'dbb create foo' -> MySQL schema 'dbb_foo'

\b
SAFETY:
  This tool intentionally does NOT support dropping schemas.
  Schemas must be removed manually via MySQL to prevent accidental data loss.\
"""

CREATE_HELP = """\
Create a new isolated MySQL schema and write .env.db-schema files.

\b
WHAT IT DOES:
  1. Creates a new MySQL schema named '<prefix><name>'
     (e.g., 'dbb_feature_auth' with default prefix 'dbb_')
  2. Registers the schema in the _dbb_metadata tracking table
  3. Writes .env.db-schema to each configured target app directory
     so the application automatically uses the new schema
  4. Runs any configured post-create hooks (SQL seed files, shell scripts)

\b
SCHEMA NAME RULES:
  - Only alphanumeric characters and underscores: [a-zA-Z0-9_]
  - Must start with a letter or underscore
  - Must NOT contain '/' (convert branch names: feature/foo -> feature_foo)
  - Full name (prefix + name) must be <= 64 characters (MySQL limit)

\b
EXAMPLES:
  dbb create my_feature
  dbb create feature_auth -d "Auth feature branch schema"
  dbb --json create hotfix_123

\b
JSON OUTPUT (--json):
  {
    "status": "ok",
    "message": "Schema 'dbb_my_feature' created.",
    "data": {
      "schema_name": "dbb_my_feature",
      "logical_name": "my_feature",
      "created_at": "2026-03-12T15:30:00",
      "env_files": ["/path/to/apps/my-app/.env.db-schema"]
    }
  }

\b
ERROR OUTPUT (--json):
  {"status": "error", "message": "Schema 'dbb_my_feature' already exists."}

\b
EXIT CODES:
  0  Success
  1  Error (invalid name, schema already exists, connection failure, etc.)\
"""

LS_HELP = """\
List all schemas managed by DBranch.

\b
WHAT IT DOES:
  Queries the _dbb_metadata tracking table and cross-references with
  MySQL's information_schema to show only schemas that actually exist.

\b
FILTERING:
  --older-than <duration>   Show only schemas older than the given duration.
                            Format: <number><unit> where unit is:
                              d = days    (e.g., 7d)
                              h = hours   (e.g., 24h)
                              w = weeks   (e.g., 2w)

\b
EXAMPLES:
  dbb ls                       # list all managed schemas
  dbb ls --older-than 7d       # schemas older than 7 days
  dbb ls --older-than 2w       # schemas older than 2 weeks
  dbb --json ls                # JSON array output
  dbb --json ls --older-than 1d

\b
TABLE OUTPUT (default):
  Name         Schema            Created              Description
  my_feature   dbb_my_feature    2026-03-12T15:30:00
  hotfix_123   dbb_hotfix_123    2026-03-10T09:00:00  urgent fix

\b
JSON OUTPUT (--json):
  [
    {
      "schema_name": "dbb_my_feature",
      "logical_name": "my_feature",
      "created_at": "2026-03-12T15:30:00",
      "description": ""
    }
  ]

\b
EXIT CODES:
  0  Success (even if no schemas found - returns empty list/table)
  1  Error (config not found, connection failure, etc.)\
"""

INIT_HELP = """\
Initialize DBranch configuration for this git repository (interactive).

\b
This command is designed for humans, not agents. It walks you through:
  1. Project name
  2. MySQL connection details (host, port, user, password)
  3. Schema name prefix (default: 'dbb_')
  4. Target app directories (where .env.db-schema gets written)
  5. Post-create hook setup

\b
Config is saved to ~/.config/dbranch/projects/<project-name>/config.yaml
and is auto-detected by matching the git repository.

\b
Re-running 'dbb init' on an already-configured repo lets you update
settings. Previous values are shown as defaults; press Enter to keep them.
Password is preserved if you press Enter without typing a new one.

\b
EXAMPLES:
  dbb init          # first-time setup or update existing config\
"""

STATUS_HELP = """\
Show which schema the current worktree is using.

\b
WHAT IT DOES:
  Reads the .env.db-schema file(s) in each configured target app directory
  and checks whether the referenced schema actually exists in MySQL.

\b
USE CASE:
  Before running migrations or starting work, an agent can check if this
  worktree already has a schema assigned, and whether it's still valid.

\b
EXAMPLES:
  dbb status
  dbb --json status

\b
JSON OUTPUT (--json):
  {
    "worktree_root": "/path/to/worktree",
    "project_name": "my-monorepo",
    "targets": [
      {
        "target_path": "apps/mysql-use-project",
        "env_file": "/path/to/apps/mysql-use-project/.env.db-schema",
        "configured": true,
        "schema_name": "dbb_feature_bar",
        "exists_in_db": true
      }
    ]
  }

\b
FIELDS:
  configured    Whether an .env.db-schema file exists with a value set.
  schema_name   The schema name read from the env file (null if not configured).
  exists_in_db  Whether that schema actually exists in MySQL.

\b
EXIT CODES:
  0  Success
  1  Error (config not found, connection failure, etc.)\
"""

CLONE_HELP = """\
Clone an existing schema (structure + data) into a new one.

\b
WHAT IT DOES:
  1. Verifies the source schema exists
  2. Creates a new MySQL schema named '<prefix><new_name>'
  3. Copies all tables from the source (CREATE TABLE ... LIKE + INSERT ... SELECT)
  4. Registers the new schema in _dbb_metadata
  5. Writes .env.db-schema to target app directories (points to new schema)
  6. Runs post-create hooks

\b
USE CASE:
  When you need a new worktree that starts with the same data as an existing
  branch's database. Useful for testing migrations against real data, or
  branching off a known-good state.

\b
SCHEMA NAME RULES:
  Same as 'dbb create' - only [a-zA-Z0-9_], no '/'.

\b
EXAMPLES:
  dbb clone main_dev feature_auth
  dbb clone staging hotfix_123 -d "Clone staging for hotfix"
  dbb --json clone main_dev feature_auth

\b
JSON OUTPUT (--json):
  {
    "status": "ok",
    "message": "Schema 'dbb_feature_auth' cloned from 'dbb_main_dev'.",
    "data": {
      "schema_name": "dbb_feature_auth",
      "logical_name": "feature_auth",
      "cloned_from": "dbb_main_dev",
      "tables_cloned": 12,
      "created_at": "2026-03-12T15:30:00",
      "env_files": ["/path/to/apps/my-app/.env.db-schema"]
    }
  }

\b
EXIT CODES:
  0  Success
  1  Error (source not found, target exists, connection failure, etc.)\
"""


class OutputFormatter:
    """Handles plain text vs JSON output."""

    def __init__(self, use_json: bool):
        self.use_json = use_json

    def success(self, message: str, data: dict | None = None) -> None:
        if self.use_json:
            payload = {"status": "ok", "message": message}
            if data:
                payload["data"] = data
            click.echo(json.dumps(payload, indent=2, default=str))
        else:
            console.print(f"[green]{message}[/green]")

    def error(self, message: str) -> None:
        if self.use_json:
            click.echo(json.dumps({"status": "error", "message": message}))
        else:
            err_console.print(f"[red]Error:[/red] {message}")

    def table(self, rows: list[dict], columns: list[tuple[str, str]]) -> None:
        """Display data as a table or JSON array."""
        if self.use_json:
            click.echo(json.dumps(rows, indent=2, default=str))
            return

        if not rows:
            console.print("[dim]No schemas found.[/dim]")
            return

        table = Table(show_header=True, header_style="bold")
        for col_key, col_label in columns:
            table.add_column(col_label)

        for row in rows:
            table.add_row(*[str(row.get(k, "")) for k, _ in columns])

        console.print(table)


@click.group(help=MAIN_HELP)
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format.")
@click.pass_context
def cli(ctx: click.Context, output_json: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["fmt"] = OutputFormatter(output_json)


@cli.command(help=INIT_HELP)
@click.pass_context
def init(ctx: click.Context) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    # Load existing config as defaults
    existing = find_project_config()
    prev: dict = {}
    prev_name = ""
    if existing:
        config_path, prev_name = existing
        with open(config_path) as f:
            prev = yaml.safe_load(f) or {}
        if not Confirm.ask(
            f"[yellow]This repo already has config (project: {prev_name}). Update?[/yellow]",
            default=True,
        ):
            fmt.error("Aborted.")
            raise SystemExit(1)

    try:
        git_common = get_git_common_dir()
    except RuntimeError:
        fmt.error("Not inside a git repository.")
        raise SystemExit(1)

    prev_conn = prev.get("connection", {})

    console.print()
    console.print("[bold]DBranch Setup[/bold]")
    console.print()

    # --- Project name ---
    default_name = prev_name or Path.cwd().name
    project_name = Prompt.ask("  Project name", default=default_name)

    # --- Connection ---
    console.print()
    console.print("[bold]MySQL Connection[/bold]")
    host = Prompt.ask("  Host", default=prev_conn.get("host", "localhost"))
    port = IntPrompt.ask("  Port", default=prev_conn.get("port", 3306))
    user = Prompt.ask("  User", default=prev_conn.get("user", "root"))

    prev_password = prev_conn.get("password", "")
    if prev_password:
        console.print("  Password [dim](press Enter to keep current)[/dim]")
        password = Prompt.ask("  Password", password=True, default="")
        if not password:
            password = prev_password
    else:
        password = Prompt.ask("  Password", password=True)

    # --- Schema prefix ---
    console.print()
    console.print("[bold]Schema Settings[/bold]")
    prefix = Prompt.ask("  Schema name prefix", default=prev.get("schema_prefix", "dbb_"))

    # --- Targets ---
    prev_targets = prev.get("targets", [])
    console.print()
    console.print("[bold]Target Apps[/bold]")
    console.print("  Apps that receive .env.db-schema on 'dbb create'.")
    console.print("  Paths are relative to repo root.")

    if prev_targets:
        console.print(f"  Current targets: {', '.join(t['path'] for t in prev_targets)}")
        keep = Confirm.ask("  Keep current targets?", default=True)
        targets = prev_targets if keep else []
    else:
        targets = []

    if not targets or (prev_targets and not keep):
        while True:
            app_path = Prompt.ask("  App path (empty to finish)", default="")
            if not app_path:
                break
            env_file = Prompt.ask("    Env file name", default=".env.db-schema")
            env_key = Prompt.ask("    Env variable name", default="DB_NAME")
            targets.append({
                "path": app_path,
                "env_file": env_file,
                "env_key": env_key,
            })

    # --- Test connection ---
    console.print()
    from dbranch.config import ConnectionConfig

    test_config = ConnectionConfig(host=host, port=port, user=user, password=password)

    try:
        info = test_connection(test_config)
        console.print(
            f"  Connection test... [green]OK[/green] (MySQL {info['version']})"
        )
    except Exception as e:
        console.print(f"  Connection test... [red]FAILED[/red] ({e})")
        if not Confirm.ask("  Continue anyway?", default=False):
            raise SystemExit(1)

    # --- Hooks ---
    prev_hooks = prev.get("hooks")
    console.print()
    if prev_hooks:
        create_hooks = False  # keep existing hooks
    else:
        create_hooks = Confirm.ask("Generate example post-create hook?", default=True)

    # --- Build config ---
    config_data: dict = {
        "git_common_dir": git_common,
        "connection": {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
        },
        "schema_prefix": prefix,
    }

    if targets:
        config_data["targets"] = targets

    if create_hooks:
        worktree_root = get_git_toplevel()
        hooks_dir = worktree_root / "hooks"
        hooks_dir.mkdir(exist_ok=True)

        hook_file = hooks_dir / "post_create.sql"
        if not hook_file.exists():
            hook_file.write_text(
                "-- Post-create hook for DBranch\n"
                "-- This SQL runs inside the newly created schema.\n"
                "-- Available template variable: {schema_name}\n"
                "--\n"
                "-- Example: create an admin user table and seed it\n"
                "--\n"
                "-- CREATE TABLE admin_users (\n"
                "--     id INT AUTO_INCREMENT PRIMARY KEY,\n"
                "--     username VARCHAR(255) NOT NULL,\n"
                "--     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
                "-- );\n"
                "--\n"
                "-- INSERT INTO admin_users (username) VALUES ('admin');\n"
            )
            console.print(f"  Created {hook_file}")

        config_data["hooks"] = {
            "post_create": [
                {"sql": "./hooks/post_create.sql"},
            ],
        }
    elif prev_hooks:
        config_data["hooks"] = prev_hooks

    # --- Save ---
    # If project name changed, remove old config
    if prev_name and prev_name != project_name:
        old_dir = PROJECTS_DIR / prev_name
        if old_dir.is_dir():
            import shutil
            shutil.rmtree(old_dir)
    saved_path = save_project_config(project_name, config_data)
    console.print(f"  Saved config to {saved_path}")

    # --- .gitignore for .env.db-schema ---
    worktree_root = get_git_toplevel()
    gitignore = worktree_root / ".gitignore"
    ignore_entry = ".env.db-schema"
    existing_content = gitignore.read_text() if gitignore.exists() else ""
    if ignore_entry not in existing_content:
        with open(gitignore, "a") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write(f"{ignore_entry}\n")
        console.print(f"  Added '{ignore_entry}' to .gitignore")

    console.print()
    fmt.success("Initialization complete. Run 'dbb create <name>' to create a schema.")


@cli.command(help=CREATE_HELP)
@click.argument("name")
@click.option("--description", "-d", default="", help="Optional description for the schema.")
@click.pass_context
def create(ctx: click.Context, name: str, description: str) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    error = validate_name(name)
    if error:
        fmt.error(error)
        raise SystemExit(1)

    try:
        config = load_config()

        schema = full_schema_name(config.schema_prefix, name)
        if not fmt.use_json:
            console.print(f"Creating schema [bold]{schema}[/bold]...")

        result = create_schema(config, name, description)

        if not fmt.use_json and result.get("env_files"):
            for path in result["env_files"]:
                console.print(f"  Wrote {path}")

        fmt.success(f"Schema '{schema}' created.", data=result)

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        fmt.error(str(e))
        raise SystemExit(1)


@cli.command(name="ls", help=LS_HELP)
@click.option("--older-than", default=None, help="Filter schemas older than duration (e.g., 7d, 24h, 2w).")
@click.pass_context
def ls_cmd(ctx: click.Context, older_than: str | None) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    try:
        config = load_config()
        rows = list_schemas(config, older_than=older_than)

        fmt.table(
            rows,
            columns=[
                ("logical_name", "Name"),
                ("schema_name", "Schema"),
                ("created_at", "Created"),
                ("description", "Description"),
            ],
        )

    except (FileNotFoundError, ValueError) as e:
        fmt.error(str(e))
        raise SystemExit(1)


@cli.command(help=STATUS_HELP)
@click.pass_context
def status(ctx: click.Context) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    try:
        config = load_config()
        result = get_status(config)

        if fmt.use_json:
            click.echo(json.dumps(result, indent=2, default=str))
            return

        console.print(f"Project: [bold]{result['project_name']}[/bold]")
        console.print(f"Worktree: {result['worktree_root']}")
        console.print()

        if not result["targets"]:
            console.print("[dim]No target apps configured.[/dim]")
            return

        for t in result["targets"]:
            schema = t["schema_name"] or "[dim]not set[/dim]"
            if t["configured"] and t["exists_in_db"]:
                status_icon = "[green]active[/green]"
            elif t["configured"] and not t["exists_in_db"]:
                status_icon = "[red]missing in DB[/red]"
            else:
                status_icon = "[yellow]not configured[/yellow]"

            console.print(f"  {t['target_path']}")
            console.print(f"    Schema: {schema}  ({status_icon})")

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        fmt.error(str(e))
        raise SystemExit(1)


CONFIG_SHOW_HELP = """\
Show current project configuration.

\b
WHAT IT DOES:
  Displays the resolved configuration for the current git repository.
  Password is masked in output for safety.

\b
EXAMPLES:
  dbb config show
  dbb --json config show

\b
EXIT CODES:
  0  Success
  1  Error (config not found, not in a git repo)\
"""


@cli.group()
def config():
    """Manage DBranch configuration."""
    pass


@config.command(name="show", help=CONFIG_SHOW_HELP)
@click.pass_context
def config_show(ctx: click.Context) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    try:
        cfg = load_config()
        data = {
            "project_name": cfg.project_name,
            "git_common_dir": cfg.git_common_dir,
            "connection": {
                "host": cfg.connection.host,
                "port": cfg.connection.port,
                "user": cfg.connection.user,
                "password": "***",
            },
            "schema_prefix": cfg.schema_prefix,
            "targets": [
                {"path": t.path, "env_file": t.env_file, "env_key": t.env_key}
                for t in cfg.targets
            ],
            "hooks": {
                "post_create": [
                    {"type": h.type, "value": h.value}
                    for h in cfg.hooks.post_create
                ],
            },
        }

        if fmt.use_json:
            click.echo(json.dumps(data, indent=2))
        else:
            console.print(f"Project: [bold]{data['project_name']}[/bold]")
            console.print(f"Git:     {data['git_common_dir']}")
            console.print(f"Prefix:  {data['schema_prefix']}")
            console.print()
            conn = data["connection"]
            console.print(f"Connection: {conn['user']}@{conn['host']}:{conn['port']}")
            console.print()
            if data["targets"]:
                console.print("[bold]Targets:[/bold]")
                for t in data["targets"]:
                    console.print(f"  {t['path']} -> {t['env_file']} ({t['env_key']})")
            if data["hooks"]["post_create"]:
                console.print()
                console.print("[bold]Hooks (post_create):[/bold]")
                for h in data["hooks"]["post_create"]:
                    console.print(f"  [{h['type']}] {h['value']}")

    except (FileNotFoundError, RuntimeError) as e:
        fmt.error(str(e))
        raise SystemExit(1)


@cli.command(help=CLONE_HELP)
@click.argument("source")
@click.argument("new_name")
@click.option("--description", "-d", default="", help="Optional description for the new schema.")
@click.pass_context
def clone(ctx: click.Context, source: str, new_name: str, description: str) -> None:
    fmt: OutputFormatter = ctx.obj["fmt"]

    for name, label in [(source, "Source"), (new_name, "New name")]:
        error = validate_name(name)
        if error:
            fmt.error(f"{label}: {error}")
            raise SystemExit(1)

    try:
        config = load_config()

        source_schema = full_schema_name(config.schema_prefix, source)
        new_schema = full_schema_name(config.schema_prefix, new_name)
        if not fmt.use_json:
            console.print(f"Cloning [bold]{source_schema}[/bold] -> [bold]{new_schema}[/bold]...")

        result = clone_schema(config, source, new_name, description)

        if not fmt.use_json:
            console.print(f"  Tables cloned: {result['tables_cloned']}")
            if result.get("env_files"):
                for path in result["env_files"]:
                    console.print(f"  Wrote {path}")

        fmt.success(
            f"Schema '{new_schema}' cloned from '{source_schema}'.",
            data=result,
        )

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        fmt.error(str(e))
        raise SystemExit(1)
