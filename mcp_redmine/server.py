"""Domain Redmine MCP server — 4 read-only tools for requirements + completion."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.logging import get_logger

from mcp_redmine.client import RedmineClient, scrub_key
from mcp_redmine.completion.evidence import build_evidence, build_requirements
from mcp_redmine.config import Settings, load_dotenv
from mcp_redmine.errors import ToolError
from mcp_redmine.mappers import (
    approx_tokens,
    decode_cursor,
    encode_cursor,
    map_child,
    map_journals,
    utc_now_iso,
)
from mcp_redmine.models.common import Meta
from mcp_redmine.models.issue import TimelineResult
from mcp_redmine.openapi_spec import list_paths, path_info

VERSION = "2026.10.31"

mcp = MCPServer(
    "Redmine task MCP",
    version=VERSION,
    instructions=(
        "Read-only Redmine access. Prefer helpers when they fit: "
        "get_completion_evidence (done / ready to close?), "
        "get_task_requirements (read/analyze requirements or AC), "
        "list_child_tasks (breakdown), get_task_timeline (history). "
        "For any other Redmine read use redmine_get(path, params); call "
        "redmine_paths_list / redmine_paths_info first if the endpoint is unknown. "
        "Never use curl or external HTTP for Redmine."
    ),
)
logger = get_logger(__name__)

_settings: Settings | None = None
_client: RedmineClient | None = None


def configure(settings: Settings | None = None) -> Settings:
    """Load settings and (re)create HTTP client. Safe to call from tests."""
    global _settings, _client
    if _client is not None:
        _client.close()
        _client = None
    _settings = settings or Settings.from_env(require=True)
    _client = RedmineClient(_settings)
    return _settings


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        configure()
    assert _settings is not None
    return _settings


def get_client() -> RedmineClient:
    global _client
    if _client is None:
        configure()
    assert _client is not None
    return _client


def wrap_insecure_content(content: str) -> str:
    tag_id = uuid.uuid4().hex[:16]
    return f"<insecure-content-{tag_id}>\n{content}\n</insecure-content-{tag_id}>"


def format_result(obj: Any) -> str:
    settings = get_settings()
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return scrub_key(text, settings.api_key, headers=settings.headers)


def _tool_error(exc: Exception) -> str:
    if isinstance(exc, ToolError):
        return format_result(exc.to_dict())
    settings = get_settings()
    return format_result(
        {
            "error": {
                "code": "REDMINE_UNAVAILABLE",
                "message": scrub_key(
                    f"{exc.__class__.__name__}: {exc}",
                    settings.api_key,
                    headers=settings.headers,
                ),
                "retryable": True,
                "details": {},
            }
        }
    )


def _clamp_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


@mcp.tool(
    description=(
        "Read and analyze task requirements / acceptance criteria. "
        "Call this FIRST when the user asks to read, summarize, or analyze an issue's "
        "requirements or AC. Returns metadata, description (wrapped), and parsed AC groups."
    )
)
def get_task_requirements(issue_id: int) -> str:
    try:
        client = get_client()
        settings = get_settings()
        pack = build_requirements(client, int(issue_id), settings)
        data = pack.model_dump()
        if data.get("description"):
            data["description"] = wrap_insecure_content(data["description"])
        data["meta"]["approx_tokens"] = approx_tokens(data)
        return format_result(data)
    except Exception as e:
        return _tool_error(e)


@mcp.tool(
    description=(
        "Get a typed timeline of journal events for an issue (status/scope/assignment changes). "
        "Use when analyzing how requirements or status changed over time, or to dig deeper after "
        "get_completion_evidence / get_task_requirements."
    )
)
def get_task_timeline(
    issue_id: int,
    limit: int | None = None,
    cursor: str | None = None,
    event_kinds: list[str] | None = None,
    include_notes: bool = False,
) -> str:
    try:
        client = get_client()
        settings = get_settings()
        lim = _clamp_limit(
            limit, settings.timeline_default_limit, settings.timeline_max_limit
        )
        offset = decode_cursor(cursor)
        started = client.call_count
        issue = client.get_issue(int(issue_id), include="journals")
        journals = issue.get("journals") or []
        events, truncated, next_offset = map_journals(
            [j for j in journals if isinstance(j, dict)],
            event_kinds=event_kinds,
            include_notes=include_notes,
            limit=lim,
            offset=offset,
        )
        # Wrap note previews
        out_events = []
        for ev in events:
            d = ev.model_dump()
            if d.get("note_preview"):
                d["note_preview"] = wrap_insecure_content(d["note_preview"])
            out_events.append(d)
        result = TimelineResult(
            issue_id=int(issue_id),
            events=events,
            next_cursor=encode_cursor(next_offset) if truncated else None,
            truncated=truncated,
            total_returned=len(events),
            meta=Meta(
                fetched_at=utc_now_iso(),
                redmine_calls=client.call_count - started,
            ),
        )
        data = result.model_dump()
        data["events"] = out_events
        data["meta"]["approx_tokens"] = approx_tokens(data)
        return format_result(data)
    except Exception as e:
        return _tool_error(e)


@mcp.tool(
    description=(
        "List child tasks of a parent issue (summaries only). "
        "Use when analyzing scope breakdown or when completion evidence reports open children."
    )
)
def list_child_tasks(
    parent_issue_id: int,
    limit: int | None = None,
    cursor: str | None = None,
    status_filter: str = "all",
) -> str:
    try:
        client = get_client()
        settings = get_settings()
        lim = _clamp_limit(limit, settings.default_page_size, settings.max_page_size)
        offset = decode_cursor(cursor)
        status_map = {"all": "*", "open": "open", "closed": "closed"}
        status_id = status_map.get((status_filter or "all").lower(), "*")
        started = client.call_count
        # Ensure parent exists
        client.get_issue(int(parent_issue_id), include="children")
        body = client.list_children(
            int(parent_issue_id), status_id=status_id, limit=lim, offset=offset
        )
        issues = body.get("issues") or []
        items = [map_child(i).model_dump() for i in issues if isinstance(i, dict)]
        total_count = body.get("total_count")
        truncated = False
        next_cursor = None
        if isinstance(total_count, int):
            truncated = offset + len(items) < total_count
        elif len(items) >= lim:
            truncated = True
        if truncated:
            next_cursor = encode_cursor(offset + len(items))
        data = {
            "parent_issue_id": int(parent_issue_id),
            "items": items,
            "next_cursor": next_cursor,
            "truncated": truncated,
            "total_returned": len(items),
            "meta": {
                "source": "redmine",
                "fetched_at": utc_now_iso(),
                "redmine_calls": client.call_count - started,
            },
        }
        data["meta"]["approx_tokens"] = approx_tokens(data)
        return format_result(data)
    except Exception as e:
        return _tool_error(e)


@mcp.tool(
    description=(
        "Recheck whether a Redmine task is complete. "
        "Call this FIRST when the user asks if an issue is done / finished / ready to close. "
        "Returns children_summary (open_ids), signals.completion_signal, "
        "done_ratio_conflict (flag only), short timeline, parsed AC, next_actions. "
        "Trust open_ids / status.is_closed over booleans. Does not close or modify the issue."
    )
)
def get_completion_evidence(
    issue_id: int,
    include_acceptance_criteria: bool = True,
    include_child_evidence: bool = True,
    timeline_limit: int = 10,
) -> str:
    try:
        client = get_client()
        settings = get_settings()
        pack = build_evidence(
            client,
            int(issue_id),
            settings,
            include_acceptance_criteria=include_acceptance_criteria,
            include_child_evidence=include_child_evidence,
            timeline_limit=timeline_limit,
        )
        data = pack.model_dump()
        for ev in data.get("timeline") or []:
            if ev.get("note_preview"):
                ev["note_preview"] = wrap_insecure_content(ev["note_preview"])
        data["meta"]["approx_tokens"] = approx_tokens(data)
        return format_result(data)
    except Exception as e:
        return _tool_error(e)


@mcp.tool(
    description=(
        "Read any Redmine REST endpoint with GET (read-only). "
        "Use this for everything not covered by the domain helpers: other issue fields, "
        "projects, users, time entries, versions, wiki, search, attachments metadata, ... "
        "path is relative to REDMINE_URL, e.g. '/issues.json?status_id=*' or "
        "'/issues/2774.json' with params={'include': 'journals,relations'}. "
        "Returns {status_code, body, error}; body is JSON or text (redacted + wrapped)."
    )
)
def redmine_get(path: str, params: dict[str, Any] | None = None) -> str:
    try:
        client = get_client()
        result = client.get_raw(path, params=params)
        body = result.get("body")
        out: dict[str, Any] = {
            "status_code": result.get("status_code", 0),
            "path": path,
            "body": body,
            "error": result.get("error") or "",
        }
        if isinstance(body, (bytes, bytearray)):
            out["body"] = f"<binary {len(body)} bytes>"
        elif isinstance(body, str):
            out["body"] = wrap_insecure_content(body)
        return format_result(out)
    except Exception as e:
        return _tool_error(e)


@mcp.tool(
    description=(
        "List available Redmine API paths from the bundled OpenAPI spec. "
        "Use before redmine_get when you do not know the endpoint."
    )
)
def redmine_paths_list() -> str:
    return format_result(list_paths())


@mcp.tool(
    description=(
        "Get full OpenAPI specs (methods, params, schemas) for given path templates, "
        "e.g. ['/issues.json', '/time_entries.json']."
    )
)
def redmine_paths_info(path_templates: list[str]) -> str:
    return format_result(path_info(path_templates))


# Reject unknown tool arguments (#52 behaviour)
for _tool in mcp._tool_manager.list_tools():
    _tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    _tool.fn_metadata.arg_model.model_rebuild(force=True)
    _tool.parameters["additionalProperties"] = False


def run_check() -> int:
    """Validate env + ping Redmine. Returns process exit code."""
    load_dotenv()
    try:
        settings = Settings.from_env(require=True)
    except ValueError as e:
        key = (os.environ.get("REDMINE_API_KEY") or "").strip()
        print(scrub_key(f"FAIL: {e}", key))
        return 1
    client = RedmineClient(settings)
    try:
        body = client.check()
        user = body.get("user") or {}
        login = user.get("login") or user.get("firstname") or "ok"
        print(f"OK: connected to {settings.redmine_url} as {login}")
        return 0
    except ToolError as e:
        print(
            scrub_key(
                f"FAIL: [{e.code}] {e.message}",
                settings.api_key,
                headers=settings.headers,
            )
        )
        return 1
    except Exception as e:
        print(
            scrub_key(
                f"FAIL: {e}",
                settings.api_key,
                headers=settings.headers,
            )
        )
        return 1
    finally:
        client.close()


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MCP Redmine domain server (stdio)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate REDMINE_URL/API_KEY and ping Redmine, then exit",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="Transport (stdio only)",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to .env (default: ./.env if present)",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file)

    if args.check:
        sys.exit(run_check())

    configure()
    logger.info(f"Starting MCP Redmine domain server version {VERSION}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
