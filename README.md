# mcp-redmine

Local stdio, read-only MCP that can **read any Redmine GET endpoint**. Helpers for daily questions,
plus `redmine_get` for everything else — no curl needed.

| Ask | Call first |
|---|---|
| “Is this task done?” | `get_completion_evidence` |
| “Read / analyze requirements, AC or bug report” | `get_task_requirements` |
| “Child tasks / breakdown” | `list_child_tasks` |
| “History / journals” | `get_task_timeline` |
| Anything else (projects, users, time entries, wiki, search, …) | `redmine_get` (+ `redmine_paths_*` if path unknown) |

Read-only by default. No Docker.

## Setup

```bash
cp .env.example .env
# edit REDMINE_URL + REDMINE_API_KEY

uv sync
make check   # or: uv run mcp-redmine --check
```

## Cursor (stdio)

```json
{
  "mcpServers": {
    "redmine": {
      "command": "uv",
      "args": ["run", "--directory", "your-path-project", "mcp-redmine"],
      "env": {
        "REDMINE_URL": "https://redmine.example.com",
        "REDMINE_API_KEY": "..."
      }
    }
  }
}
```

## Tools

1. `get_task_requirements` — metadata + description + parsed AC (any tracker, incl. Bug)
2. `get_completion_evidence` — `children_summary`, signals / `completion_signal` / `next_actions`
3. `list_child_tasks` — child summaries
4. `get_task_timeline` — typed journal events
5. `redmine_get` — any GET endpoint, e.g. `/issues.json?project_id=12`, `/time_entries.json`
6. `redmine_paths_list` / 7. `redmine_paths_info` — OpenAPI discovery

## Dev

```bash
make tests-run
make run
```

Env: `REDMINE_URL` and `REDMINE_API_KEY` required. `REDMINE_READ_ONLY=true` by default.
