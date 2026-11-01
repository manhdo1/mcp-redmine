"""SSRF, read-only, and credential scrubbing."""
from __future__ import annotations

import json

import pytest

from mcp_redmine.client import RedmineClient, redact, scrub_key
from mcp_redmine.config import Settings
from mcp_redmine import server


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, content=b""):
        self.status_code = status_code
        self._json_body = json_body
        self.content = content if not json_body else b"x"

    def raise_for_status(self):
        pass

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


@pytest.fixture
def capture_requests(settings, monkeypatch):
    client = RedmineClient(settings)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(json_body={"ok": True})

    monkeypatch.setattr(client._http, "request", fake_request)
    yield client, calls
    client.close()


def test_normal_path_stays_on_redmine(capture_requests):
    client, calls = capture_requests
    result = client.request("issues.json")
    assert result["status_code"] == 200
    assert calls[0]["url"] == "https://redmine.example.org/issues.json"


def test_leading_slash_path_stays_on_redmine(capture_requests):
    client, calls = capture_requests
    client.request("/issues.json")
    assert calls[0]["url"] == "https://redmine.example.org/issues.json"


@pytest.mark.parametrize(
    "path",
    [
        "https://attacker.example/collect",
        "http://attacker.example/collect",
        "https://redmine.example.org.attacker.example/collect",
        "ftp://attacker.example/collect",
    ],
)
def test_escaping_paths_are_refused(capture_requests, path):
    client, calls = capture_requests
    result = client.request(path)
    assert result["status_code"] == 0
    assert "escapes REDMINE_URL" in result["error"]
    assert calls == []


@pytest.mark.parametrize(
    "path",
    [
        "//attacker.example/collect",
        "../../../collect",
        "/../collect",
    ],
)
def test_tricky_paths_stay_on_redmine_host(capture_requests, path):
    client, calls = capture_requests
    client.request(path)
    assert len(calls) == 1
    assert calls[0]["url"].startswith("https://redmine.example.org/")


def test_read_only_blocks_writes(capture_requests):
    client, calls = capture_requests
    for method in ["post", "put", "PATCH", "delete"]:
        result = client.request("issues.json", method=method)
        assert result["status_code"] == 0
        assert "REDMINE_READ_ONLY" in result["error"]
    assert calls == []


def test_read_only_allows_get(capture_requests):
    client, calls = capture_requests
    result = client.request("issues.json", method="get")
    assert result["status_code"] == 200
    assert len(calls) == 1


def test_writes_allowed_when_read_only_false(monkeypatch):
    settings = Settings(
        redmine_url="https://redmine.example.org/",
        api_key="test-api-key-123",
        read_only=False,
    )
    client = RedmineClient(settings)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(method)
        return FakeResponse(json_body={"ok": True})

    monkeypatch.setattr(client._http, "request", fake_request)
    result = client.request("issues.json", method="post", data={"issue": {}})
    assert result["status_code"] == 200
    assert calls == ["post"]
    client.close()


def test_api_key_fields_redacted():
    out = redact(
        {
            "user": {"login": "admin", "api_key": "sekrit-abc"},
            "memberships": [{"apiKey": "sekrit-too"}],
        }
    )
    assert out["user"]["api_key"] == "[REDACTED]"
    assert out["memberships"][0]["apiKey"] == "[REDACTED]"


def test_password_token_and_header_keys_redacted():
    out = redact(
        {
            "password": "p@ss",
            "token": "tok-1",
            "X-Redmine-API-Key": "header-key",
            "access_token": "at-1",
            "passwd_confirmation": "p@ss",
            "nested": {"secret": "shh", "private_key": "pk"},
        }
    )
    assert out["password"] == "[REDACTED]"
    assert out["token"] == "[REDACTED]"
    assert out["X-Redmine-API-Key"] == "[REDACTED]"
    assert out["access_token"] == "[REDACTED]"
    assert out["passwd_confirmation"] == "[REDACTED]"
    assert out["nested"]["secret"] == "[REDACTED]"
    assert out["nested"]["private_key"] == "[REDACTED]"


def test_configured_key_is_scrubbed():
    assert "test-api-key-123" not in scrub_key(
        "the key is test-api-key-123", "test-api-key-123"
    )


def test_scrub_key_scrubs_header_values():
    text = scrub_key(
        "leak custom-header-secret and test-api-key-123",
        "test-api-key-123",
        headers={"X-Custom": "custom-header-secret"},
    )
    assert "custom-header-secret" not in text
    assert "test-api-key-123" not in text
    assert text.count("[REDACTED]") >= 2


def test_format_result_scrubs_key(settings, monkeypatch):
    server.configure(settings)
    out = server.format_result({"note": "leak test-api-key-123 here"})
    assert "test-api-key-123" not in out
    assert "[REDACTED]" in out


def test_client_disables_redirects(settings):
    client = RedmineClient(settings)
    assert client._http.follow_redirects is False
    client.close()


def test_oversized_response_rejected(monkeypatch):
    from mcp_redmine.errors import ToolError

    settings = Settings(
        redmine_url="https://redmine.example.org/",
        api_key="test-api-key-123",
        read_only=True,
        http_max_response_bytes=64,
    )
    client = RedmineClient(settings)

    def fake_request(method, url, **kwargs):
        return FakeResponse(content=b"x" * 128)

    monkeypatch.setattr(client._http, "request", fake_request)
    with pytest.raises(ToolError) as ei:
        client.get_json("issues.json")
    assert ei.value.code == "RESPONSE_TOO_LARGE"
    with pytest.raises(ToolError) as ei2:
        client.get_raw("issues.json")
    assert ei2.value.code == "RESPONSE_TOO_LARGE"
    client.close()


def test_same_origin_allows_matching_host():
    from mcp_redmine.client import same_origin

    base = "https://redmine.example.org/"
    assert same_origin("https://redmine.example.org/issues.json", base)
    assert same_origin("https://redmine.example.org:443/issues.json", base)
    assert not same_origin("https://attacker.example/collect", base)
    assert not same_origin("http://redmine.example.org/issues.json", base)
    assert not same_origin("https://redmine.example.org.evil/x", base)


def test_import_server_without_env(monkeypatch):
    monkeypatch.delenv("REDMINE_URL", raising=False)
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    # Re-import path already loaded; ensure configure fails clearly without crashing import
    with pytest.raises(ValueError, match="REDMINE_URL"):
        Settings.from_env(require=True)


def test_exposed_tools_are_all_read_only():
    names = sorted(t.name for t in server.mcp._tool_manager.list_tools())
    assert names == [
        "get_completion_evidence",
        "get_task_requirements",
        "get_task_timeline",
        "list_child_tasks",
        "redmine_get",
        "redmine_paths_info",
        "redmine_paths_list",
    ]


def test_schema_forbids_additional_properties():
    import anyio
    from mcp.client import Client

    async def go():
        async with Client(server.mcp) as client:
            tools = (await client.list_tools()).tools
            return {t.name: t.input_schema.get("additionalProperties") for t in tools}

    assert all(v is False for v in anyio.run(go).values())
