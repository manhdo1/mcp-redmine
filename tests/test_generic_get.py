"""Generic read tools: redmine_get + OpenAPI discovery."""
from __future__ import annotations

import json

import pytest

from mcp_redmine import server
from mcp_redmine.client import RedmineClient
from tests.conftest import PARENT_ISSUE_ID, SAMPLE_CHILD, SAMPLE_PARENT


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


@pytest.fixture
def wired(settings, monkeypatch):
    client = RedmineClient(settings)
    calls: list[dict] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "params": kwargs.get("params")})
        params = kwargs.get("params") or {}
        if url.endswith("/users/current.json"):
            return FakeResponse(json_body={"user": {"login": "tester"}})
        if f"/issues/{PARENT_ISSUE_ID}.json" in url:
            return FakeResponse(json_body={"issue": dict(SAMPLE_PARENT)})
        if url.endswith("/issues.json") and str(params.get("parent_id")) == str(
            PARENT_ISSUE_ID
        ):
            return FakeResponse(json_body={"issues": [SAMPLE_CHILD], "total_count": 1})
        if "/issues/9999.json" in url:
            return FakeResponse(status_code=404, json_body={"errors": ["not found"]})
        return FakeResponse(status_code=200, json_body={"ok": True})

    monkeypatch.setattr(client._http, "request", fake_request)
    server.configure(settings)
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_settings", settings)
    yield client, calls
    client.close()


def test_redmine_get_happy_path(wired):
    _, calls = wired
    raw = server.redmine_get("/users/current.json")
    data = json.loads(raw)
    assert data["status_code"] == 200
    assert data["body"]["user"]["login"] == "tester"
    assert data["error"] == ""
    assert calls[-1]["url"].endswith("/users/current.json")


def test_redmine_get_passes_params(wired):
    _, calls = wired
    server.redmine_get(
        f"/issues/{PARENT_ISSUE_ID}.json", params={"include": "journals"}
    )
    assert calls[-1]["params"] == {"include": "journals"}


def test_redmine_get_refuses_ssrf(wired):
    _, calls = wired
    before = len(calls)
    data = json.loads(server.redmine_get("https://attacker.example/collect"))
    assert data["error"]["code"] == "INVALID_ARGUMENT"
    assert len(calls) == before


def test_redmine_get_surfaces_404(wired):
    data = json.loads(server.redmine_get("/issues/9999.json"))
    assert data["status_code"] == 404
    assert data["body"] == {"errors": ["not found"]}


def test_redmine_get_wraps_text_body(monkeypatch, wired):
    client, _ = wired
    resp = FakeResponse(status_code=200, json_body=None)
    resp.content = b"<p>hello from wiki</p>"

    def fake_request(method, url, **kwargs):
        return resp

    monkeypatch.setattr(client._http, "request", fake_request)
    raw = server.redmine_get("/projects/1/wiki/Foo")
    assert "<insecure-content-" in raw
    assert "hello from wiki" in raw


def test_read_only_still_blocks_writes(wired):
    client, _ = wired
    result = client.request("issues.json", method="post", data={"issue": {}})
    assert result["status_code"] == 0
    assert "REDMINE_READ_ONLY" in result["error"]


def test_paths_list_and_info(wired):
    from mcp_redmine.openapi_spec import load_spec

    paths = json.loads(server.redmine_paths_list())
    assert isinstance(paths, list) and "/issues.json" in paths
    # GET-only: write-only endpoints must not appear
    assert "/uploads.json" not in paths
    assert "/issues/{issue_id}/watchers.json" not in paths
    info = json.loads(server.redmine_paths_info(["/issues.json"]))
    assert "/issues.json" in info
    methods = {
        m.lower()
        for m in info["/issues.json"]
        if m.lower() in {"get", "post", "put", "delete", "patch"}
    }
    assert methods == {"get"}

    # Cap at 10 templates; extra templates ignored
    all_get = [p for p, ops in load_spec()["paths"].items() if "get" in ops]
    many = all_get[:15]
    capped = json.loads(server.redmine_paths_info(many))
    assert len(capped) <= 10
    assert set(capped).issubset(set(many[:10]))


def test_no_write_tools_exposed():
    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert names == {
        "get_task_requirements",
        "get_completion_evidence",
        "list_child_tasks",
        "get_task_timeline",
        "redmine_get",
        "redmine_paths_list",
        "redmine_paths_info",
    }
