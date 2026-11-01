"""Runtime settings. Loaded at startup / factory — not at import time."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw:
        return headers
    for part in raw.split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE pairs into os.environ if not already set."""
    env_path = Path(path) if path else Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    redmine_url: str
    api_key: str
    read_only: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    ca_bundle: str = ""
    dangerously_accept_invalid_certs: bool = False
    default_page_size: int = 20
    max_page_size: int = 50
    timeline_default_limit: int = 30
    timeline_max_limit: int = 100
    http_timeout_seconds: float = 30.0
    http_max_response_bytes: int = 131072
    description_max_chars: int = 8000

    @property
    def base_url(self) -> str:
        return self.redmine_url

    @property
    def ssl_verify(self) -> bool | str:
        if self.dangerously_accept_invalid_certs:
            return False
        if self.ca_bundle:
            return self.ca_bundle
        return True

    @classmethod
    def from_env(cls, *, require: bool = True) -> Settings:
        url = (os.environ.get("REDMINE_URL") or "").strip()
        key = (os.environ.get("REDMINE_API_KEY") or "").strip()
        if require:
            missing = []
            if not url:
                missing.append("REDMINE_URL")
            if not key:
                missing.append("REDMINE_API_KEY")
            if missing:
                raise ValueError(
                    "Missing required environment variable(s): " + ", ".join(missing)
                )
        if url:
            url = url.rstrip("/") + "/"
        return cls(
            redmine_url=url,
            api_key=key,
            read_only=_env_bool("REDMINE_READ_ONLY", True),
            headers=_parse_headers(os.environ.get("REDMINE_HEADERS", "")),
            ca_bundle=os.environ.get("REDMINE_CA_BUNDLE", "").strip(),
            dangerously_accept_invalid_certs=os.environ.get(
                "REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS"
            )
            == "1",
            default_page_size=_env_int("DEFAULT_PAGE_SIZE", 20),
            max_page_size=_env_int("MAX_PAGE_SIZE", 50),
            timeline_default_limit=_env_int("TIMELINE_DEFAULT_LIMIT", 30),
            timeline_max_limit=_env_int("TIMELINE_MAX_LIMIT", 100),
            http_timeout_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30")),
            http_max_response_bytes=_env_int("HTTP_MAX_RESPONSE_BYTES", 131072),
            description_max_chars=_env_int("DESCRIPTION_MAX_CHARS", 8000),
        )
