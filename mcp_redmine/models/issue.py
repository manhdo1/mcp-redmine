from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mcp_redmine.models.acceptance import AcceptanceCriteria
from mcp_redmine.models.common import IdName, Meta, StatusInfo

EventKind = Literal[
    "created",
    "status_change",
    "assignment_change",
    "version_change",
    "estimate_change",
    "done_ratio_change",
    "scope_change",
    "note",
    "relation_change",
    "attachment_change",
    "other",
]


class TaskSnapshot(BaseModel):
    id: int
    subject: str = ""
    tracker: str | None = None
    project: IdName | None = None
    status: StatusInfo | None = None
    done_ratio: int = 0
    closed_on: str | None = None
    spent_hours: float | None = None
    estimated_hours: float | None = None
    version: str | None = None
    assigned_to: IdName | None = None
    start_date: str | None = None
    due_date: str | None = None
    updated_on: str | None = None
    has_children: bool = False
    child_count: int = 0
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)


class TaskTimelineEvent(BaseModel):
    journal_id: int
    created_on: str | None = None
    actor: IdName | None = None
    kind: EventKind = "other"
    summary: str = ""
    changes: list[dict[str, Any]] = Field(default_factory=list)
    note_preview: str | None = None
    has_full_note: bool = False


class ChildTaskSummary(BaseModel):
    id: int
    subject: str = ""
    tracker: str | None = None
    status: StatusInfo | None = None
    done_ratio: int = 0
    closed_on: str | None = None
    version: str | None = None
    assignee: IdName | None = None


class TimelineResult(BaseModel):
    issue_id: int
    events: list[TaskTimelineEvent] = Field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    total_returned: int = 0
    meta: Meta = Field(default_factory=Meta)


class TaskRequirements(BaseModel):
    issue_id: int
    task: TaskSnapshot
    description: str | None = None
    description_truncated: bool = False
    acceptance_criteria: AcceptanceCriteria
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)
