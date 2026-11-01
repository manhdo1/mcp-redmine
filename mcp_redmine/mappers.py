"""Map Redmine JSON payloads to domain models."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from typing import Any

from mcp_redmine.models.common import IdName, StatusInfo
from mcp_redmine.models.issue import (
    ChildTaskSummary,
    TaskSnapshot,
    TaskTimelineEvent,
)

NOTE_PREVIEW_MAX = 280

_DONE_STATUS_NAMES = {
    "closed",
    "done",
    "resolved",
    "rejected",
    "completed",
    "complete",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def approx_tokens(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return (len(text) + 3) // 4


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"offset": offset}).encode("utf-8")
    ).decode("ascii")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return int(data.get("offset", 0))
    except Exception:
        return 0


def _id_name(obj: Any) -> IdName | None:
    if not isinstance(obj, dict):
        return None
    return IdName(id=obj.get("id"), name=obj.get("name"))


def _status(obj: Any) -> StatusInfo | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    is_closed = bool(obj.get("is_closed"))
    if not is_closed and isinstance(name, str):
        is_closed = name.strip().lower() in _DONE_STATUS_NAMES
    return StatusInfo(id=obj.get("id"), name=name, is_closed=is_closed)


def _version_name(issue: dict[str, Any]) -> str | None:
    for key in ("fixed_version", "version"):
        v = issue.get(key)
        if isinstance(v, dict) and v.get("name"):
            return str(v["name"])
        if isinstance(v, str):
            return v
    return None


def map_snapshot(issue: dict[str, Any]) -> TaskSnapshot:
    children = issue.get("children") or []
    if not isinstance(children, list):
        children = []
    status = _status(issue.get("status"))
    closed_on = issue.get("closed_on")
    if closed_on and status and not status.is_closed:
        status = status.model_copy(update={"is_closed": True})

    custom_fields = issue.get("custom_fields") or []
    if not isinstance(custom_fields, list):
        custom_fields = []

    tracker = issue.get("tracker")
    tracker_name = tracker.get("name") if isinstance(tracker, dict) else None

    return TaskSnapshot(
        id=int(issue["id"]),
        subject=str(issue.get("subject") or ""),
        tracker=tracker_name,
        project=_id_name(issue.get("project")),
        status=status,
        done_ratio=int(issue.get("done_ratio") or 0),
        closed_on=closed_on,
        spent_hours=issue.get("spent_hours"),
        estimated_hours=issue.get("estimated_hours"),
        version=_version_name(issue),
        assigned_to=_id_name(issue.get("assigned_to")),
        start_date=issue.get("start_date"),
        due_date=issue.get("due_date"),
        updated_on=issue.get("updated_on"),
        has_children=len(children) > 0,
        child_count=len(children),
        custom_fields=[
            {"id": cf.get("id"), "name": cf.get("name"), "value": cf.get("value")}
            for cf in custom_fields
            if isinstance(cf, dict)
        ],
    )


def map_child(issue: dict[str, Any]) -> ChildTaskSummary:
    tracker = issue.get("tracker")
    return ChildTaskSummary(
        id=int(issue["id"]),
        subject=str(issue.get("subject") or ""),
        tracker=tracker.get("name") if isinstance(tracker, dict) else None,
        status=_status(issue.get("status")),
        done_ratio=int(issue.get("done_ratio") or 0),
        closed_on=issue.get("closed_on"),
        version=_version_name(issue),
        assignee=_id_name(issue.get("assigned_to")),
    )


_FIELD_KIND = {
    "status_id": "status_change",
    "status": "status_change",
    "assigned_to_id": "assignment_change",
    "assigned_to": "assignment_change",
    "fixed_version_id": "version_change",
    "fixed_version": "version_change",
    "estimated_hours": "estimate_change",
    "done_ratio": "done_ratio_change",
    "description": "scope_change",
    "subject": "scope_change",
    "parent_id": "relation_change",
    "relates": "relation_change",
    "blocks": "relation_change",
    "blocked": "relation_change",
    "attachment": "attachment_change",
    "attachments": "attachment_change",
}


def _classify_journal(details: list[dict[str, Any]], notes: str | None) -> str:
    kinds: list[str] = []
    for d in details:
        field = str(d.get("name") or d.get("property") or "")
        kind = _FIELD_KIND.get(field)
        if kind:
            kinds.append(kind)
        elif field:
            kinds.append("other")
    if "scope_change" in kinds and (
        "status_change" in kinds or "estimate_change" in kinds
    ):
        return "scope_change"
    for preferred in (
        "status_change",
        "assignment_change",
        "version_change",
        "estimate_change",
        "done_ratio_change",
        "scope_change",
        "relation_change",
        "attachment_change",
    ):
        if preferred in kinds:
            return preferred
    if notes and notes.strip():
        return "note"
    if not details:
        return "note" if (notes and notes.strip()) else "other"
    return "other"


def _change_summary(details: list[dict[str, Any]], notes: str | None) -> str:
    parts: list[str] = []
    for d in details:
        name = d.get("name") or d.get("property") or "field"
        old = d.get("old_value")
        new = d.get("new_value")
        parts.append(f"{name}: {old} -> {new}")
    if notes and notes.strip() and not parts:
        preview = re.sub(r"\s+", " ", notes.strip())[:80]
        return f"Note: {preview}"
    return "; ".join(parts) if parts else "Journal update"


def map_journal(journal: dict[str, Any], *, include_notes: bool = False) -> TaskTimelineEvent:
    details_raw = journal.get("details") or []
    details = [d for d in details_raw if isinstance(d, dict)]
    notes = journal.get("notes")
    note_str = notes if isinstance(notes, str) else None
    kind = _classify_journal(details, note_str)
    preview = None
    has_full = False
    if note_str and note_str.strip():
        cleaned = note_str.strip()
        has_full = len(cleaned) > NOTE_PREVIEW_MAX
        preview = cleaned[:NOTE_PREVIEW_MAX]
        if include_notes:
            preview = cleaned
            has_full = False

    changes = [
        {
            "field": d.get("name") or d.get("property"),
            "from": d.get("old_value"),
            "to": d.get("new_value"),
        }
        for d in details
    ]
    user = journal.get("user")
    return TaskTimelineEvent(
        journal_id=int(journal.get("id") or 0),
        created_on=journal.get("created_on"),
        actor=_id_name(user) if isinstance(user, dict) else None,
        kind=kind,  # type: ignore[arg-type]
        summary=_change_summary(details, note_str),
        changes=changes,
        note_preview=preview,
        has_full_note=has_full,
    )


def map_journals(
    journals: list[dict[str, Any]],
    *,
    event_kinds: list[str] | None = None,
    include_notes: bool = False,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[TaskTimelineEvent], bool, int]:
    events = [
        map_journal(j, include_notes=include_notes)
        for j in journals
        if isinstance(j, dict)
    ]
    events.sort(key=lambda e: e.created_on or "")
    if event_kinds:
        allowed = set(event_kinds)
        events = [e for e in events if e.kind in allowed]
    sliced = events[offset : offset + limit]
    truncated = offset + limit < len(events)
    next_offset = offset + len(sliced)
    return sliced, truncated, next_offset
