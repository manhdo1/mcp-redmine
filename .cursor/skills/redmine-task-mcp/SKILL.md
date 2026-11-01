---
name: redmine-task-mcp
description: >-
  Read any Redmine data through mcp-redmine tools: helpers (get_completion_evidence, get_task_requirements,
  list_child_tasks, get_task_timeline) plus redmine_get for any GET endpoint and OpenAPI discovery.
  Use for Redmine issues/tasks/bugs, completion checks (xong chưa / done), requirements/AC analysis,
  parent-child scope, journals, projects, users, time entries, versions, wiki, search, attachments metadata,
  or issue IDs like #1234; never curl Redmine directly.
---

# Redmine Task MCP

Server is **read-only** (GET only). **Never** use curl, shell, or external HTTP for Redmine.
Every Redmine read goes through a tool below.

## Tool selection

1. **Helper fits?** Use it — fewer calls, normalized output:
   | Intent | Tool |
   |---|---|
   | Done? / finished? / ready to close? / recheck completion | `get_completion_evidence` |
   | Read/analyze requirements, AC, bug description | `get_task_requirements` |
   | Child tasks / breakdown | `list_child_tasks` |
   | History / journals / status changes over time | `get_task_timeline` |
2. **Anything else → `redmine_get(path, params)`.** Examples: issue fields not in the helper, projects,
   users, memberships, time entries, versions, categories, wiki, search, attachments metadata, relations.
3. **Unknown endpoint →** `redmine_paths_list`, then `redmine_paths_info` with **1–2** path templates, then `redmine_get`.

Do not force a question into "completion" or "requirements". If the two helpers do not fit, go straight to
`redmine_get`.

Extract `issue_id` from `#1234`, `issue 1234`, or `id=1234`. Ask once if missing.

## Workflows

### A — Completion recheck

1. `get_completion_evidence(issue_id=…)`
2. **Trust payload first:** prefer `children[].status.is_closed` and `children_summary.open_ids` over
   aggregate booleans; `completion_signal` is only a hint; `done_ratio_conflict` is a flag, not a signal.
3. Dig only if needed: `list_child_tasks(..., status_filter="open")`, `get_task_timeline(...)`,
   `get_task_requirements(...)`.
4. Answer with open child ids/statuses, signal, conflicts, next steps.
5. **Do not** close or edit the issue.

### B — Read / analyze requirements or bug report

1. `get_task_requirements(issue_id=…)` — works for Bug, User Story, Task, any tracker.
2. If the description lacks structure, use `redmine_get("/issues/{id}.json",
   params={"include": "journals,relations,attachments"})` for raw fields.
3. If `has_children` → `list_child_tasks`.
4. If scope drifted → `get_task_timeline`.
5. Summarize: goal, repro/expected/actual for bugs, AC groups, gaps, open questions.

### C — Arbitrary read

1. Known path → `redmine_get("/issues.json", params={"project_id": 12, "status_id": "open", "limit": 20})`.
2. Unknown path → discovery tools first.
3. Paginate with `limit`/`offset` (Redmine default 25); check `total_count`.

## Tool contracts (short)

### `redmine_get(path, params=None)`

- `path` relative to `REDMINE_URL`, e.g. `/issues.json`, `/issues/{id}.json`, `/projects.json`.
- Returns `{status_code, path, body, error}`. Non-2xx status is returned, not raised.
- JSON body is parsed and credentials redacted; text body is wrapped in `<insecure-content-…>`.

### `redmine_paths_list()` / `redmine_paths_info(path_templates)`

- Bundled OpenAPI spec, **GET-only**. Prefer 1–2 templates per `paths_info` call (max 10).

### `get_task_requirements(issue_id)`

- Metadata, description (wrapped if user content), AC groups, `parse_status`, `meta.approx_tokens`.
- `verified` AC only from custom-field checklists.

### `get_completion_evidence(issue_id, include_acceptance_criteria=true, include_child_evidence=true, timeline_limit=10)`

- `task`, `children`, `children_summary`, short `timeline`, AC groups, `signals`, `next_actions`.
- `children_summary.open_ids` counts only `status.is_closed == false`.

### `list_child_tasks(parent_issue_id, limit?, cursor?, status_filter="all")`

- `status_filter`: `all` | `open` | `closed`; paginate with `next_cursor`.

### `get_task_timeline(issue_id, limit?, cursor?, event_kinds?, include_notes=false)`

- Typed events, short `note_preview`; `include_notes=true` only when needed.

## Answer rules

- Prefer tool data over memory. Cite issue id and what the tool returned.
- On `{ "error": { "code", "message" } }`: report code/message; retry once only if `retryable`.
- Never claim the issue was modified; MCP cannot write.
- Do not dump raw JSON; summarize.

## More detail

- Signals, AC statuses, event kinds, errors, common paths: [reference.md](reference.md)
