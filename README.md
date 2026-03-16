# DBranch (`dbb`)

Database branching CLI for parallel worktree development. Designed primarily for AI agents (like Claude Code) working across multiple git worktrees simultaneously.

## Problem

When running multiple Claude Code sessions in parallel using git worktrees, they share the same database. This causes DB migration conflicts, schema collisions, and unpredictable state. DBranch solves this by giving each worktree its own isolated MySQL schema.

## How It Works

```
monorepo/                          → dbb_main
├── .worktrees/feature-auth/       → dbb_feature_auth     (isolated)
├── .worktrees/payment-refactor/   → dbb_payment_refactor (isolated)
└── .worktrees/add-user-column/    → dbb_add_user_column  (isolated)
```

Each worktree gets its own MySQL schema. DBranch creates the schema and writes a `.env.db-schema` file to the app directory so the application automatically connects to the right database.

## Install

```bash
pip install -e .
```

Requires Python 3.10+ and a running MySQL server.

## Quick Start

### 1. Initialize (one-time, by a human)

Run from your monorepo root:

```bash
dbb init
```

This interactively configures:
- MySQL connection (host, port, user, password)
- Schema name prefix (default: `dbb_`)
- Target app directories (where `.env.db-schema` gets written)
- Post-create hooks (SQL/shell scripts to run after schema creation)

Config is stored at `~/.config/dbranch/projects/<project-name>/config.yaml` and auto-detected by matching the git repository. Nothing is added to the project directory.

### 2. Create a schema (by agents or humans)

```bash
dbb create feature_auth
```

This:
1. Creates MySQL schema `dbb_feature_auth`
2. Writes `.env.db-schema` to each configured target app (e.g., `DB_NAME=dbb_feature_auth`)
3. Runs post-create hooks (seed data, admin accounts, etc.)

### 3. Check status

```bash
dbb status
```

Shows which schema the current worktree is using and whether it exists in MySQL.

### 4. List schemas

```bash
dbb ls
dbb ls --older-than 7d
```

### 5. Clone a schema

```bash
dbb clone main feature_auth
```

Copies all tables and data from an existing schema into a new one. Useful when you need a worktree that starts with real data.

## Agent Usage

All commands support `--json` for machine-readable output:

```bash
dbb --json status
dbb --json create feature_auth
dbb --json clone main feature_auth
dbb --json ls
dbb --json config show               # check current configuration
```

### Example CLAUDE.md snippet

```markdown
## DB Management
- New worktree: run `dbb --json status` to check current schema
- No schema: run `dbb --json create <branch_name>` to create one
- Need existing data: run `dbb --json clone main <branch_name>`
- Schema names must use only [a-zA-Z0-9_], no slashes
```

### JSON output examples

**`dbb --json create`**
```json
{
  "status": "ok",
  "message": "Schema 'dbb_feature_auth' created.",
  "data": {
    "schema_name": "dbb_feature_auth",
    "logical_name": "feature_auth",
    "created_at": "2026-03-12T15:30:00",
    "env_files": ["/path/to/apps/my-app/.env.db-schema"]
  }
}
```

**`dbb --json clone`**
```json
{
  "status": "ok",
  "message": "Schema 'dbb_feature_auth' cloned from 'dbb_main_dev'.",
  "data": {
    "schema_name": "dbb_feature_auth",
    "logical_name": "feature_auth",
    "cloned_from": "dbb_main_dev",
    "tables_cloned": 12,
    "views_cloned": 2,
    "routines_cloned": 1,
    "created_at": "2026-03-12T15:30:00",
    "env_files": ["/path/to/apps/my-app/.env.db-schema"]
  }
}
```

**`dbb --json status`**
```json
{
  "worktree_root": "/path/to/worktree",
  "project_name": "my-monorepo",
  "targets": [
    {
      "target_path": "apps/my-app",
      "env_file": "/path/to/apps/my-app/.env.db-schema",
      "configured": true,
      "schema_name": "dbb_feature_auth",
      "exists_in_db": true
    }
  ]
}
```

**`dbb --json ls`**
```json
[
  {
    "schema_name": "dbb_feature_auth",
    "logical_name": "feature_auth",
    "created_at": "2026-03-12T15:30:00",
    "description": ""
  }
]
```

## Commands

| Command | Audience | Description |
|---|---|---|
| `dbb init` | Human | Interactive project setup (one-time or update) |
| `dbb create <name>` | Agent/Human | Create isolated schema + write .env.db-schema |
| `dbb clone <src> <new>` | Agent/Human | Clone schema with all data |
| `dbb status` | Agent/Human | Check current worktree's schema |
| `dbb ls` | Agent/Human | List all managed schemas |
| `dbb config show` | Agent/Human | Show current project config (password masked) |

Run `dbb <command> --help` for detailed usage, JSON output format, and exit codes.

## Configuration

### Config file

Stored at `~/.config/dbranch/projects/<name>/config.yaml`:

```yaml
git_common_dir: /path/to/repo/.git
connection:
  host: localhost
  port: 3306
  user: root
  password: actual_password_here
schema_prefix: dbb_
targets:
  - path: apps/my-app
    env_file: .env.db-schema
    env_key: DB_NAME
hooks:
  post_create:
    - sql: ./hooks/post_create.sql
```

The config is auto-detected by matching `git_common_dir` — works from any worktree of the same repo.

### Post-create hooks

SQL hooks run inside the newly created schema. Use `{schema_name}` as a template variable:

```sql
CREATE TABLE admin_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL
);
INSERT INTO admin_users (username) VALUES ('admin');
```

Shell hooks receive `SCHEMA_NAME` as an environment variable:

```bash
#!/bin/bash
echo "Created schema: $SCHEMA_NAME"
```

### Schema naming rules

- Only `[a-zA-Z0-9_]` allowed
- Must start with a letter or underscore
- No `/` (convert `feature/foo` to `feature_foo`)
- Full name (prefix + name) must be <= 64 characters

## Safety

**DBranch intentionally does not support dropping schemas.** Schemas must be removed manually via MySQL to prevent accidental data loss.

## License

MIT
