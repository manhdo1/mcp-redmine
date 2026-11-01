from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mcp_redmine.models.acceptance import AcceptanceCriteria
from mcp_redmine.models.common import Meta
from mcp_redmine.models.issue import ChildTaskSummary, TaskSnapshot, TaskTimelineEvent

CompletionSignal = Literal[
    "complete",
    "needs_review",
    "ready_to_close",
    "not_complete",
    "unknown",
]


class ChildrenSummary(BaseModel):
    total: int = 0
    closed: int = 0
    open: int = 0
    open_ids: list[int] = Field(default_factory=list)
    open_statuses: dict[str, int] = Field(default_factory=dict)


class CompletionSignals(BaseModel):
    parent_closed: bool = False
    parent_status_is_done: bool = False
    done_ratio_conflict: bool = False
    has_spent_time: bool = False
    all_children_closed: bool = True
    all_children_done_ratio_100: bool = True
    all_acceptance_groups_verified: bool = False
    completion_signal: CompletionSignal = "unknown"
    signal_warnings: list[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
    issue_id: int
    task: TaskSnapshot
    children: list[ChildTaskSummary] = Field(default_factory=list)
    children_summary: ChildrenSummary = Field(default_factory=ChildrenSummary)
    timeline: list[TaskTimelineEvent] = Field(default_factory=list)
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    signals: CompletionSignals = Field(default_factory=CompletionSignals)
    next_actions: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)
