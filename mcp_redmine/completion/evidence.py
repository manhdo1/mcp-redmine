"""Build completion evidence packs (≤ ~3–4 Redmine GETs)."""
from __future__ import annotations

from mcp_redmine.client import RedmineClient
from mcp_redmine.completion.acceptance import parse_acceptance_criteria
from mcp_redmine.completion.rules import evaluate_completion
from mcp_redmine.config import Settings
from mcp_redmine.errors import ToolError
from mcp_redmine.mappers import (
    approx_tokens,
    map_child,
    map_journals,
    map_snapshot,
    utc_now_iso,
)
from mcp_redmine.models.common import Meta
from mcp_redmine.models.completion import EvidencePack
from mcp_redmine.models.issue import TaskRequirements


def build_requirements(
    client: RedmineClient, issue_id: int, settings: Settings
) -> TaskRequirements:
    started = client.call_count
    issue = client.get_issue(issue_id, include="children")

    task = map_snapshot(issue)
    description = issue.get("description")
    desc_str = description if isinstance(description, str) else None
    truncated = False
    if desc_str and len(desc_str) > settings.description_max_chars:
        desc_str = None
        truncated = True

    ac = parse_acceptance_criteria(
        description=issue.get("description")
        if isinstance(issue.get("description"), str)
        else None,
        custom_fields=task.custom_fields,
        updated_on=task.updated_on,
    )

    payload = TaskRequirements(
        issue_id=issue_id,
        task=task,
        description=desc_str,
        description_truncated=truncated,
        acceptance_criteria=ac,
        custom_fields=task.custom_fields,
        meta=Meta(
            fetched_at=utc_now_iso(),
            redmine_calls=client.call_count - started,
        ),
    )
    data = payload.model_dump()
    payload.meta.approx_tokens = approx_tokens(data)
    return payload


def build_evidence(
    client: RedmineClient,
    issue_id: int,
    settings: Settings,
    *,
    include_acceptance_criteria: bool = True,
    include_child_evidence: bool = True,
    timeline_limit: int = 10,
) -> EvidencePack:
    started = client.call_count
    # Prefer one call with children+journals when possible
    try:
        issue = client.get_issue(issue_id, include="children,journals")
    except ToolError:
        issue = client.get_issue(issue_id, include="children")
        journals_issue = client.get_issue(issue_id, include="journals")
        issue["journals"] = journals_issue.get("journals") or []

    task = map_snapshot(issue)

    children = []
    if include_child_evidence:
        body = client.list_children(
            issue_id,
            status_id="*",
            limit=min(settings.max_page_size, 50),
            offset=0,
        )
        for raw in body.get("issues") or []:
            if isinstance(raw, dict):
                children.append(map_child(raw))

    journals = issue.get("journals") or []
    if not isinstance(journals, list):
        journals = []
    timeline, _, _ = map_journals(
        [j for j in journals if isinstance(j, dict)],
        limit=max(1, min(timeline_limit, settings.timeline_max_limit)),
        offset=0,
    )

    if include_acceptance_criteria:
        ac = parse_acceptance_criteria(
            description=issue.get("description")
            if isinstance(issue.get("description"), str)
            else None,
            custom_fields=task.custom_fields,
            updated_on=task.updated_on,
        )
    else:
        from mcp_redmine.models.acceptance import AcceptanceCriteria

        ac = AcceptanceCriteria(parse_status="empty")

    result = evaluate_completion(task, children, ac)
    pack = EvidencePack(
        issue_id=issue_id,
        task=task,
        children=children,
        children_summary=result.children_summary,
        timeline=timeline,
        acceptance_criteria=ac,
        signals=result.signals,
        next_actions=result.next_actions,
        meta=Meta(
            fetched_at=utc_now_iso(),
            redmine_calls=client.call_count - started,
        ),
    )
    pack.meta.approx_tokens = approx_tokens(pack.model_dump())
    return pack
