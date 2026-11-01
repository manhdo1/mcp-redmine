"""Completion signals derived strictly from payload (status.is_closed, done_ratio, AC)."""
from __future__ import annotations

from dataclasses import dataclass

from mcp_redmine.models.acceptance import AcceptanceCriteria
from mcp_redmine.models.completion import (
    ChildrenSummary,
    CompletionSignal,
    CompletionSignals,
)
from mcp_redmine.models.issue import ChildTaskSummary, TaskSnapshot

_DONE_NAMES = {
    "closed",
    "done",
    "resolved",
    "rejected",
    "completed",
    "complete",
}


@dataclass
class CompletionResult:
    signals: CompletionSignals
    next_actions: list[str]
    children_summary: ChildrenSummary


def _child_is_closed(child: ChildTaskSummary) -> bool:
    return bool(child.status and child.status.is_closed)


def _parent_closed(task: TaskSnapshot) -> bool:
    # Strict: only Redmine status.is_closed (ignore stale closed_on).
    return bool(task.status and task.status.is_closed)


def _parent_status_is_done(task: TaskSnapshot) -> bool:
    if not task.status or not task.status.name:
        return False
    return task.status.name.strip().lower() in _DONE_NAMES or bool(
        task.status.is_closed
    )


def build_children_summary(children: list[ChildTaskSummary]) -> ChildrenSummary:
    open_ids: list[int] = []
    open_statuses: dict[str, int] = {}
    closed = 0
    for c in children:
        if _child_is_closed(c):
            closed += 1
            continue
        open_ids.append(c.id)
        name = (c.status.name if c.status and c.status.name else "unknown")
        open_statuses[name] = open_statuses.get(name, 0) + 1
    return ChildrenSummary(
        total=len(children),
        closed=closed,
        open=len(open_ids),
        open_ids=open_ids,
        open_statuses=open_statuses,
    )


def _ac_verified(acceptance: AcceptanceCriteria) -> bool:
    if acceptance.parse_status != "parsed":
        return False
    actionable = [g for g in acceptance.groups if g.status != "not_applicable"]
    if not actionable:
        return False
    return all(g.status == "verified" for g in actionable)


def _pick_signal(
    *,
    parent_closed: bool,
    all_children_closed: bool,
    all_ac_verified: bool,
) -> CompletionSignal:
    # Hard priority (done_ratio_conflict is a separate flag, never the signal).
    if not all_children_closed:
        return "not_complete"
    if parent_closed and all_ac_verified:
        return "complete"
    if parent_closed and not all_ac_verified:
        return "needs_review"
    # Parent open, all children closed
    if all_ac_verified:
        return "ready_to_close"
    return "needs_review"


def _apply_invariants(
    *,
    task: TaskSnapshot,
    summary: ChildrenSummary,
    signals: CompletionSignals,
) -> CompletionSignals:
    warnings: list[str] = list(signals.signal_warnings)
    signal = signals.completion_signal

    if summary.open > 0 and signals.all_children_closed:
        warnings.append("invariant_open_child_but_all_children_closed")
        signals.all_children_closed = False
        signal = "not_complete"

    if summary.open_ids and signals.all_children_closed:
        warnings.append("invariant_open_ids_nonzero")
        signals.all_children_closed = False
        signal = "not_complete"

    parent_open = not signals.parent_closed
    if (
        parent_open
        and summary.open > 0
        and signal in ("complete", "ready_to_close")
    ):
        warnings.append("invariant_parent_open_with_open_children")
        signal = "not_complete"

    expect_conflict = task.done_ratio >= 100 and (
        not signals.parent_closed or summary.open > 0
    )
    # Also conflict when %Done 100 but AC not verified (matches prior semantics)
    expect_conflict = expect_conflict or (
        task.done_ratio >= 100 and not signals.all_acceptance_groups_verified
    )
    if expect_conflict and not signals.done_ratio_conflict:
        warnings.append("invariant_missing_done_ratio_conflict")
        signals.done_ratio_conflict = True

    if warnings and signal in ("complete", "ready_to_close"):
        signal = "needs_review"
        warnings.append("signal_downgraded_after_invariant")

    signals.completion_signal = signal
    signals.signal_warnings = warnings
    return signals


def evaluate_completion(
    task: TaskSnapshot,
    children: list[ChildTaskSummary],
    acceptance: AcceptanceCriteria,
) -> CompletionResult:
    parent_closed = _parent_closed(task)
    parent_done = _parent_status_is_done(task)
    has_spent = bool(task.spent_hours and float(task.spent_hours) > 0)

    summary = build_children_summary(children)
    if children:
        all_children_closed = summary.open == 0
        all_children_done_ratio_100 = all(c.done_ratio >= 100 for c in children)
    else:
        all_children_closed = True
        all_children_done_ratio_100 = True

    all_ac_verified = _ac_verified(acceptance)

    done_ratio_conflict = task.done_ratio >= 100 and (
        not parent_closed or not all_ac_verified or not all_children_closed
    )

    signal = _pick_signal(
        parent_closed=parent_closed,
        all_children_closed=all_children_closed,
        all_ac_verified=all_ac_verified,
    )

    signals = CompletionSignals(
        parent_closed=parent_closed,
        parent_status_is_done=parent_done,
        done_ratio_conflict=done_ratio_conflict,
        has_spent_time=has_spent,
        all_children_closed=all_children_closed,
        all_children_done_ratio_100=all_children_done_ratio_100,
        all_acceptance_groups_verified=all_ac_verified,
        completion_signal=signal,
        signal_warnings=[],
    )
    signals = _apply_invariants(task=task, summary=summary, signals=signals)

    next_actions: list[str] = []
    if summary.open_ids:
        next_actions.append(
            f"close_or_test_open_children: {summary.open_ids[:20]}"
        )
    if signals.done_ratio_conflict:
        next_actions.append("review_done_ratio_conflict")
    if not all_ac_verified:
        if acceptance.parse_status != "parsed":
            next_actions.append(
                f"manual_review_ac (parse_status={acceptance.parse_status})"
            )
        else:
            pending = [
                g.code
                for g in acceptance.groups
                if g.status in ("missing", "partial", "unknown")
                and g.status != "not_applicable"
            ]
            if pending:
                next_actions.append(
                    "inspect_evidence_for_groups_" + "_".join(pending[:8])
                )
            else:
                next_actions.append(
                    f"manual_review_ac (parse_status={acceptance.parse_status})"
                )
    if signals.completion_signal == "ready_to_close":
        next_actions.append("consider_closing_parent_issue")
    if signals.completion_signal == "complete":
        next_actions.append("no_action_needed")

    return CompletionResult(
        signals=signals,
        next_actions=next_actions,
        children_summary=summary,
    )
