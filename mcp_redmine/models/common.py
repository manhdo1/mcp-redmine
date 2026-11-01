from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IdName(BaseModel):
    id: int | None = None
    name: str | None = None


class StatusInfo(BaseModel):
    id: int | None = None
    name: str | None = None
    is_closed: bool = False


class Meta(BaseModel):
    source: str = "redmine"
    fetched_at: str | None = None
    approx_tokens: int = 0
    redmine_calls: int | None = None
    cache: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
