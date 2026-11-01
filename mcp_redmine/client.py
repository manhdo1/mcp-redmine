"""HTTP client for Redmine REST (GET-focused, SSRF-safe)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from mcp_redmine.config import Settings
from mcp_redmine.errors import ToolError

_REDACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "x_redmine_api_key",
        "password",
        "passwd",
        "passwd_confirmation",
        "token",
        "secret",
        "access_token",
        "private_key",
    }
)

def _normalize_key(key: str) -> str:
    return key.lower().replace("-", "_")


def redact(obj: Any) -> Any:
    """Redact credential values from parsed API responses."""
    if isinstance(obj, dict):
        return {
            k: (
                "[REDACTED]"
                if _normalize_key(str(k)) in _REDACT_KEYS
                else redact(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def scrub_key(
    text: str,
    api_key: str,
    headers: dict[str, str] | None = None,
) -> str:
    """Scrub literal API key and optional header values from text."""
    if not isinstance(text, str):
        return text
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    if headers:
        for value in headers.values():
            if value:
                text = text.replace(value, "[REDACTED]")
    return text


def _default_port(scheme: str) -> int | None:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


def _origin_parts(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port if parsed.port is not None else _default_port(scheme)
    return scheme, host, port


def same_origin(url: str, base_url: str) -> bool:
    """True when url shares scheme, hostname, and port with base_url."""
    return _origin_parts(url) == _origin_parts(base_url)


class RedmineClient:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self.settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=settings.http_timeout_seconds,
            verify=settings.ssl_verify,
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=120),
        )
        self.call_count = 0

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> RedmineClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _scrub(self, text: str) -> str:
        return scrub_key(
            text, self.settings.api_key, headers=self.settings.headers
        )

    def request(
        self,
        path: str,
        *,
        method: str = "get",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        method_l = method.lower()
        if self.settings.read_only and method_l != "get":
            return {
                "status_code": 0,
                "body": None,
                "error": f"REDMINE_READ_ONLY is enabled: refusing {method.upper()} request",
            }

        key = self.settings.api_key
        if not key:
            return {
                "status_code": 0,
                "body": None,
                "error": "No API key: set REDMINE_API_KEY",
            }

        headers = {
            "X-Redmine-API-Key": key,
            "Content-Type": "application/json",
            **self.settings.headers,
        }

        url = urljoin(self.settings.redmine_url, path.lstrip("/"))
        if not same_origin(url, self.settings.redmine_url):
            return {
                "status_code": 0,
                "body": None,
                "error": f"Path escapes REDMINE_URL, refusing to send API key to: {url}",
            }

        try:
            self.call_count += 1
            response = self._http.request(
                method=method_l,
                url=url,
                json=data,
                params=params,
                headers=headers,
            )
            content = response.content or b""
            max_bytes = self.settings.http_max_response_bytes
            if len(content) > max_bytes:
                return {
                    "status_code": 0,
                    "body": None,
                    "error": (
                        f"RESPONSE_TOO_LARGE: response body "
                        f"{len(content)} bytes exceeds limit {max_bytes}"
                    ),
                }
            response.raise_for_status()
            body: Any = None
            if content:
                try:
                    body = response.json()
                    if body is None:
                        raise ValueError("empty json body")
                except ValueError:
                    try:
                        body = content.decode("utf-8", errors="replace")
                    except Exception:
                        body = content
            return {"status_code": response.status_code, "body": body, "error": ""}
        except Exception as e:
            status_code = 0
            body = None
            resp = getattr(e, "response", None)
            if resp is not None:
                status_code = getattr(resp, "status_code", 0) or 0
                try:
                    err_content = getattr(resp, "content", None) or b""
                    max_bytes = self.settings.http_max_response_bytes
                    if len(err_content) > max_bytes:
                        return {
                            "status_code": 0,
                            "body": None,
                            "error": (
                                f"RESPONSE_TOO_LARGE: response body "
                                f"{len(err_content)} bytes exceeds limit {max_bytes}"
                            ),
                        }
                    body = resp.json()
                except Exception:
                    try:
                        body = resp.text
                    except Exception:
                        body = None
            return {
                "status_code": status_code,
                "body": body,
                "error": self._scrub(f"{e.__class__.__name__}: {e}"),
            }

    def get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = self.request(path, method="get", params=params)
        if result["error"] and "escapes REDMINE_URL" in result["error"]:
            raise ToolError(
                "INVALID_ARGUMENT",
                result["error"],
                details={"path": path},
            )
        if result["error"] and "RESPONSE_TOO_LARGE" in result["error"]:
            raise ToolError(
                "RESPONSE_TOO_LARGE",
                result["error"],
                details={"path": path},
            )
        if result["error"] and "REDMINE_READ_ONLY" in result["error"]:
            raise ToolError("INVALID_ARGUMENT", result["error"])
        status = result["status_code"]
        if status == 404:
            raise ToolError(
                "TASK_NOT_FOUND",
                "Issue or resource not found",
                details={"status_code": status, "path": path},
            )
        if status in (401, 403):
            code = (
                "REDMINE_UNAUTHORIZED" if status == 401 else "REDMINE_FORBIDDEN"
            )
            raise ToolError(
                code,
                self._scrub(result["error"] or f"HTTP {status}"),
                details={"status_code": status},
            )
        if status == 429:
            raise ToolError(
                "REDMINE_RATE_LIMITED",
                "Redmine rate limited the request",
                retryable=True,
                details={"status_code": status},
            )
        if status == 0 or status >= 500:
            raise ToolError(
                "REDMINE_UNAVAILABLE",
                self._scrub(result["error"] or f"HTTP {status}"),
                retryable=True,
                details={"status_code": status},
            )
        if status != 200 or result["body"] is None:
            raise ToolError(
                "REDMINE_UNAVAILABLE",
                self._scrub(result["error"] or f"Unexpected HTTP {status}"),
                retryable=status >= 500,
                details={"status_code": status},
            )
        return redact(result["body"])

    def get_raw(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Raw GET result {status_code, body, error} with SSRF/read-only guards.

        Unlike get_json this does not raise on 404/5xx: the caller (generic
        redmine_get tool) returns the status to the model as-is.
        """
        result = self.request(path, method="get", params=params)
        if result["error"] and "escapes REDMINE_URL" in result["error"]:
            raise ToolError(
                "INVALID_ARGUMENT",
                result["error"],
                details={"path": path},
            )
        if result["error"] and "RESPONSE_TOO_LARGE" in result["error"]:
            raise ToolError(
                "RESPONSE_TOO_LARGE",
                result["error"],
                details={"path": path},
            )
        if result["error"] and "REDMINE_READ_ONLY" in result["error"]:
            raise ToolError("INVALID_ARGUMENT", result["error"])
        if result["error"] and result["status_code"] == 0:
            raise ToolError(
                "REDMINE_UNAVAILABLE",
                self._scrub(result["error"]),
                retryable=True,
                details={"path": path},
            )
        body = result["body"]
        if isinstance(body, (bytes, bytearray)):
            body = bytes(body).decode("utf-8", errors="replace")
        result["body"] = redact(body)
        return result

    def get_issue(
        self, issue_id: int, *, include: str | None = None
    ) -> dict[str, Any]:
        params = {"include": include} if include else None
        body = self.get_json(f"issues/{issue_id}.json", params=params)
        issue = body.get("issue")
        if not isinstance(issue, dict):
            raise ToolError(
                "TASK_NOT_FOUND",
                f"Issue {issue_id} not found in response",
                details={"issue_id": issue_id},
            )
        return issue

    def list_children(
        self,
        parent_id: int,
        *,
        status_id: str = "*",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.get_json(
            "issues.json",
            params={
                "parent_id": parent_id,
                "status_id": status_id,
                "limit": limit,
                "offset": offset,
            },
        )

    def check(self) -> dict[str, Any]:
        """Ping Redmine with current user endpoint."""
        return self.get_json("users/current.json")
