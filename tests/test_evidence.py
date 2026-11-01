"""Mock sample parent evidence + requirements integration."""
from __future__ import annotations

import json

import pytest

from mcp_redmine.client import RedmineClient
from mcp_redmine.completion.evidence import build_evidence, build_requirements
from mcp_redmine import server
from tests.conftest import CHILD_ISSUE_ID, PARENT_ISSUE_ID, SAMPLE_CHILD, SAMPLE_PARENT


class FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"x" if json_body is not None else b""

    def raise_for_status(self):
        if self.status_code >= 400:
            err = Exception(f"HTTP {self.status_code}")
            err.response = self  # type: ignore[attr-defined]
            raise err

    def json(self):
        return self._json_body


def _install_redmine_mock(client: RedmineClient, monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    parent_path = f"/issues/{PARENT_ISSUE_ID}.json"

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "params": kwargs.get("params")})
        params = kwargs.get("params") or {}
        if url.endswith("/users/current.json"):
            return FakeResponse(json_body={"user": {"login": "tester"}})
        if parent_path in url:
            include = (params.get("include") or "") if isinstance(params, dict) else ""
            body = {"issue": dict(SAMPLE_PARENT)}
            if "journals" not in include:
                body["issue"] = {k: v for k, v in body["issue"].items() if k != "journals"}
            if "children" not in include:
                body["issue"] = {
                    k: v for k, v in body["issue"].items() if k != "children"
                }
            return FakeResponse(json_body=body)
        if url.endswith("/issues.json") and str(params.get("parent_id")) == str(
            PARENT_ISSUE_ID
        ):
            return FakeResponse(
                json_body={"issues": [SAMPLE_CHILD], "total_count": 1}
            )
        if "/issues/9999.json" in url:
            return FakeResponse(status_code=404, json_body={"errors": ["not found"]})
        return FakeResponse(status_code=500, json_body={"error": "unexpected"})

    monkeypatch.setattr(client._http, "request", fake_request)
    return calls


@pytest.fixture
def mock_client(settings, monkeypatch):
    client = RedmineClient(settings)
    calls = _install_redmine_mock(client, monkeypatch)
    yield client, calls, settings
    client.close()


def test_evidence_sample_parent_not_complete(mock_client):
    client, calls, settings = mock_client
    pack = build_evidence(client, PARENT_ISSUE_ID, settings, timeline_limit=10)
    assert pack.signals.completion_signal == "not_complete"
    assert pack.signals.done_ratio_conflict is True
    assert pack.signals.parent_closed is False
    assert pack.signals.all_children_closed is False
    assert pack.signals.all_acceptance_groups_verified is False
    assert CHILD_ISSUE_ID in pack.children_summary.open_ids
    assert pack.children_summary.open >= 1
    assert any(c.id == CHILD_ISSUE_ID for c in pack.children)
    assert pack.meta.redmine_calls is not None
    assert pack.meta.redmine_calls <= 4
    assert len(calls) <= 4


def test_requirements_sample_parent_has_description_and_ac(mock_client):
    client, calls, settings = mock_client
    req = build_requirements(client, PARENT_ISSUE_ID, settings)
    assert req.issue_id == PARENT_ISSUE_ID
    assert req.description and "Acceptance Criteria" in req.description
    assert req.description_truncated is False
    assert req.acceptance_criteria.parse_status == "parsed"
    codes = {g.code for g in req.acceptance_criteria.groups}
    assert {"A", "B", "C", "D", "E"} <= codes
    assert req.meta.approx_tokens >= 0


def test_tool_get_completion_evidence_json(mock_client, monkeypatch):
    client, calls, settings = mock_client
    server.configure(settings)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_settings", settings)
    raw = server.get_completion_evidence(PARENT_ISSUE_ID)
    data = json.loads(raw)
    assert data["signals"]["completion_signal"] == "not_complete"
    assert data["signals"]["done_ratio_conflict"] is True
    assert "test-api-key-123" not in raw


def test_tool_get_task_requirements_wraps_description(mock_client, monkeypatch):
    client, _, settings = mock_client
    server.configure(settings)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_settings", settings)
    raw = server.get_task_requirements(PARENT_ISSUE_ID)
    data = json.loads(raw)
    assert data["issue_id"] == PARENT_ISSUE_ID
    assert data["description"].startswith("<insecure-content-")
    assert data["acceptance_criteria"]["parse_status"] == "parsed"


def test_list_child_tasks_tool(mock_client, monkeypatch):
    client, _, settings = mock_client
    server.configure(settings)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_settings", settings)
    raw = server.list_child_tasks(PARENT_ISSUE_ID)
    data = json.loads(raw)
    assert data["parent_issue_id"] == PARENT_ISSUE_ID
    assert data["total_returned"] == 1
    assert data["items"][0]["id"] == CHILD_ISSUE_ID


def test_timeline_tool(mock_client, monkeypatch):
    client, _, settings = mock_client
    server.configure(settings)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_settings", settings)
    raw = server.get_task_timeline(PARENT_ISSUE_ID, limit=5)
    data = json.loads(raw)
    assert data["issue_id"] == PARENT_ISSUE_ID
    assert data["total_returned"] >= 1
    assert data["events"][0]["kind"] in {
        "scope_change",
        "status_change",
        "estimate_change",
        "note",
        "other",
    }
