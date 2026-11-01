# Redmine Task MCP — reference

## Trust order (completion)

1. `children_summary.open_ids` / each child `status.is_closed`
2. Parent `task.status.is_closed` (ignore stale `closed_on` alone)
3. `signals.*` booleans (must match the lists above)
4. `completion_signal` — hint only

`done_ratio_conflict` is a **boolean flag**, never a `completion_signal` value.

## `completion_signal` values

| Signal | Meaning |
|---|---|
| `complete` | Parent `is_closed`, actionable AC verified, no open children |
| `needs_review` | Parent closed but AC not verified, or parent open + children closed but AC unclear |
| `ready_to_close` | Parent open, all children `is_closed`, AC verified |
| `not_complete` | At least one child with `is_closed=false` |
| `unknown` | Could not evaluate |

## `children_summary`

```json
{"total": 6, "closed": 5, "open": 1, "open_ids": [1002], "open_statuses": {"Ready for Test": 1}}
```

`closed` / `open` count only `status.is_closed` (not `done_ratio`, not `closed_on`).

## AC `parse_status`

| Status | Meaning |
|---|---|
| `parsed` | Structured groups extracted |
| `needs_manual_review` | Unclear structure → never treat AC as verified |
| `empty` | No AC source |

`verified` only from **custom-field** checklists `[x]`, never from description bullets alone.

## Timeline `event_kinds`

`created` | `status_change` | `assignment_change` | `version_change` | `estimate_change` |
`done_ratio_change` | `scope_change` | `note` | `relation_change` | `attachment_change` | `other`

## `redmine_get` — common paths

| Need | Path + params |
|---|---|
| One issue, all extras | `/issues/{id}.json`, `{"include": "journals,relations,attachments,watchers,children"}` |
| Bug list by tracker | `/issues.json`, `{"tracker_id": 1, "status_id": "*", "limit": 25}` |
| Search issues | `/issues.json`, `{"project_id": 12, "assigned_to_id": 35, "status_id": "open", "subject": "~upload"}` |
| Projects | `/projects.json`, `{"limit": 100}` |
| One project | `/projects/{id}.json?include=trackers,issue_categories,time_entry_activities` |
| Users / me | `/users.json`, `/users/current.json` |
| Time entries | `/time_entries.json`, `{"user_id": 35, "from": "2026-10-01", "to": "2026-10-31"}` |
| Versions | `/projects/{id}/versions.json` |
| Issue categories | `/projects/{id}/issue_categories.json` |
| Memberships | `/projects/{id}/memberships.json` |
| Statuses / trackers | `/issue_statuses.json`, `/trackers.json` |
| Issue relations | `/issues/{id}/relations.json` |
| Search | `/search.json`, `{"q": "upload", "scope": "issues"}` |
| Attachment metadata | `/attachments/{id}.json` |

Redmine paginates at 25 by default: pass `limit`/`offset` and read `total_count`.

## Common error codes

| Code | Retry? | Action |
|---|---|---|
| `INVALID_ARGUMENT` | No | Fix params / path |
| `TASK_NOT_FOUND` | No | Confirm issue id |
| `RESPONSE_TOO_LARGE` | No | Narrow query / pagination |
| `REDMINE_UNAUTHORIZED` / `REDMINE_FORBIDDEN` | No | Check API key / rights |
| `REDMINE_RATE_LIMITED` / `REDMINE_UNAVAILABLE` | Yes | Wait / retry once |
| `AC_PARSE_FAILED` | No | Manual AC review |

## OpenAPI discovery

- `redmine_paths_list` returns **GET-only** paths from the bundled spec.
- `redmine_paths_info` returns **GET** operation details only; pass **1–2** path templates (hard cap 10).

## Prompt → tool examples

| User says | Call |
|---|---|
| `#1234 đã xong chưa?` | `get_completion_evidence(1234)` |
| `Đọc #1234 và phân tích yêu cầu` | `get_task_requirements(1234)` |
| `Đọc bug #1001` | `get_task_requirements(1001)` (or `redmine_get` for raw fields) |
| `Bug đang mở của project 12` | `redmine_get("/issues.json", {"tracker_id": 1, "project_id": 12, "status_id": "open"})` |
| `Tôi đã log giờ tuần này chưa?` | `redmine_get("/time_entries.json", {...})` |
