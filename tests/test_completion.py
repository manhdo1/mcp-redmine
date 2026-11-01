"""Completion rules + AC parser."""
from __future__ import annotations

from mcp_redmine.completion.acceptance import parse_acceptance_criteria
from mcp_redmine.completion.rules import evaluate_completion
from mcp_redmine.models.acceptance import AcceptanceCriteria, AcceptanceGroup
from mcp_redmine.models.common import StatusInfo
from mcp_redmine.models.issue import ChildTaskSummary, TaskSnapshot


def _task(**kwargs) -> TaskSnapshot:
    base = dict(
        id=1,
        subject="t",
        status=StatusInfo(id=1, name="New", is_closed=False),
        done_ratio=0,
        closed_on=None,
    )
    base.update(kwargs)
    return TaskSnapshot(**base)


def test_ac_parser_letter_groups():
    text = """
### A. Upload
- [ ] one
### B. UI
- [x] two
"""
    ac = parse_acceptance_criteria(description=text)
    assert ac.parse_status == "parsed"
    codes = [g.code for g in ac.groups]
    assert "A" in codes and "B" in codes


def test_ac_parser_empty():
    ac = parse_acceptance_criteria(description="")
    assert ac.parse_status == "empty"


def test_ac_from_custom_field():
    ac = parse_acceptance_criteria(
        description="ignored",
        custom_fields=[
            {
                "name": "Acceptance Criteria",
                "value": "### A. Foo\n- [ ] bar\n### B. Baz\n- [ ] qux",
            }
        ],
    )
    assert ac.parse_status == "parsed"
    assert len(ac.groups) >= 2
    assert "parsed_from_custom_field" in ac.warnings


def test_complete_signal():
    task = _task(
        status=StatusInfo(id=5, name="Closed", is_closed=True),
        closed_on="2026-01-01",
        done_ratio=100,
    )
    children = [
        ChildTaskSummary(
            id=2,
            status=StatusInfo(id=5, name="Closed", is_closed=True),
            closed_on="2026-01-01",
            done_ratio=100,
        )
    ]
    ac = AcceptanceCriteria(
        groups=[
            AcceptanceGroup(code="A", status="verified"),
            AcceptanceGroup(code="B", status="verified"),
        ],
        parse_status="parsed",
    )
    result = evaluate_completion(task, children, ac)
    assert result.signals.completion_signal == "complete"


def test_ready_to_close():
    task = _task(done_ratio=100)
    ac = AcceptanceCriteria(
        groups=[AcceptanceGroup(code="A", status="verified")],
        parse_status="parsed",
    )
    result = evaluate_completion(task, [], ac)
    assert result.signals.completion_signal == "ready_to_close"
    assert "consider_closing_parent_issue" in result.next_actions


def test_needs_review_when_closed_but_ac_open():
    task = _task(
        status=StatusInfo(id=5, name="Closed", is_closed=True),
        closed_on="2026-01-01",
    )
    ac = AcceptanceCriteria(
        groups=[AcceptanceGroup(code="A", status="missing")],
        parse_status="parsed",
    )
    result = evaluate_completion(task, [], ac)
    assert result.signals.completion_signal == "needs_review"


def test_parent_open_children_closed_ac_unverified_is_needs_review():
    task = _task(done_ratio=50)
    children = [
        ChildTaskSummary(
            id=2,
            status=StatusInfo(id=5, name="Closed", is_closed=True),
            done_ratio=100,
        )
    ]
    ac = AcceptanceCriteria(
        groups=[AcceptanceGroup(code="A", status="unknown")],
        parse_status="needs_manual_review",
    )
    result = evaluate_completion(task, children, ac)
    assert result.signals.completion_signal == "needs_review"
    assert result.signals.all_acceptance_groups_verified is False


def test_not_complete_and_done_ratio_conflict_flag():
    task = _task(done_ratio=100)
    children = [
        ChildTaskSummary(
            id=1002,
            status=StatusInfo(id=9, name="Ready for Test", is_closed=False),
            done_ratio=100,
        )
    ]
    ac = AcceptanceCriteria(
        groups=[
            AcceptanceGroup(code="A", status="missing"),
            AcceptanceGroup(code="D", status="partial"),
        ],
        parse_status="parsed",
    )
    result = evaluate_completion(task, children, ac)
    assert result.signals.completion_signal == "not_complete"
    assert result.signals.done_ratio_conflict is True
    assert result.signals.parent_closed is False
    assert result.signals.all_children_closed is False
    assert "review_done_ratio_conflict" in result.next_actions
    assert 1002 in result.children_summary.open_ids


def test_stale_closed_on_does_not_count_as_closed():
    """Parent New 100%; 5 Closed children; 1 Ready for Test with stale closed_on."""
    open_child_id = 2007
    task = _task(
        id=2001,
        status=StatusInfo(id=1, name="New", is_closed=False),
        done_ratio=100,
        closed_on=None,
    )
    children = [
        ChildTaskSummary(
            id=i,
            status=StatusInfo(id=5, name="Closed", is_closed=True),
            done_ratio=100,
            closed_on="2026-01-01",
        )
        for i in range(2002, 2007)
    ]
    children.append(
        ChildTaskSummary(
            id=open_child_id,
            status=StatusInfo(id=9, name="Ready for Test", is_closed=False),
            done_ratio=100,
            closed_on="2025-12-01T00:00:00Z",  # stale; must NOT imply closed
        )
    )
    ac = AcceptanceCriteria(
        groups=[AcceptanceGroup(code="A", status="unknown")],
        parse_status="needs_manual_review",
    )
    result = evaluate_completion(task, children, ac)
    s = result.signals
    assert s.all_children_closed is False
    assert s.all_children_done_ratio_100 is True
    assert result.children_summary.open_ids == [open_child_id]
    assert result.children_summary.open == 1
    assert result.children_summary.closed == 5
    assert result.children_summary.total == 6
    assert result.children_summary.open_statuses.get("Ready for Test") == 1
    assert s.completion_signal == "not_complete"
    assert s.done_ratio_conflict is True
    assert s.all_acceptance_groups_verified is False
    assert "done_ratio_conflict" not in (
        s.completion_signal,
    )  # flag only, not signal enum value
    assert any(str(open_child_id) in a for a in result.next_actions)
    assert any("manual_review_ac" in a for a in result.next_actions)


def test_parent_closed_on_alone_does_not_count_as_closed():
    task = _task(
        status=StatusInfo(id=1, name="New", is_closed=False),
        closed_on="2025-01-01",
        done_ratio=100,
    )
    ac = AcceptanceCriteria(
        groups=[AcceptanceGroup(code="A", status="verified")],
        parse_status="parsed",
    )
    result = evaluate_completion(task, [], ac)
    assert result.signals.parent_closed is False
    assert result.signals.completion_signal == "ready_to_close"


def test_ac_description_checkbox_not_auto_verified():
    ac = parse_acceptance_criteria(
        description="### A. Upload\n- [x] done\n### B. UI\n- [ ] todo"
    )
    assert ac.parse_status == "parsed"
    assert all(g.status != "verified" for g in ac.groups)


def test_ac_custom_field_checkbox_can_verified():
    ac = parse_acceptance_criteria(
        custom_fields=[
            {
                "name": "Acceptance Criteria",
                "value": "### A. Foo\n- [x] bar\n### B. Baz\n- [ ] qux",
            }
        ],
    )
    statuses = {g.code: g.status for g in ac.groups}
    assert statuses.get("A") == "verified"
    assert statuses.get("B") in ("missing", "unknown", "partial")
