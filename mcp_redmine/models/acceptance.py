from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AcStatus = Literal["unknown", "missing", "partial", "verified", "not_applicable"]
ParseStatus = Literal["parsed", "empty", "needs_manual_review"]


class AcceptanceGroup(BaseModel):
    code: str
    title: str = ""
    status: AcStatus = "unknown"
    confidence: Literal["low", "medium", "high"] = "low"
    evidence_refs: list[dict] = Field(default_factory=list)


class AcceptanceCriteria(BaseModel):
    groups: list[AcceptanceGroup] = Field(default_factory=list)
    parse_status: ParseStatus = "empty"
    warnings: list[str] = Field(default_factory=list)
    source_updated_on: str | None = None
