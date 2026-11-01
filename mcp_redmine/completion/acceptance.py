"""Rule-based acceptance criteria parser (shared by requirements + evidence)."""
from __future__ import annotations

import re
from typing import Any

from mcp_redmine.models.acceptance import AcceptanceCriteria, AcceptanceGroup

_AC_FIELD_NAMES = {
    "acceptance criteria",
    "acceptance_criteria",
    "ac",
    "criteria",
    "điều kiện chấp nhận",
}

_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:nhóm\s+)?([A-Za-z0-9]+)[\.\):\-\s]+(.+)$",
    re.IGNORECASE,
)
_LETTER_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?([A-Z])\s*[\.\):\-]\s*(.+)$",
)
_CHECKLIST_RE = re.compile(r"^[\-\*]\s*\[[ xX]\]\s*(.+)$")
_BULLET_RE = re.compile(r"^[\-\*]\s+(.+)$")


def _cf_ac_text(custom_fields: list[dict[str, Any]] | None) -> str | None:
    if not custom_fields:
        return None
    for cf in custom_fields:
        name = str(cf.get("name") or "").strip().lower()
        if name in _AC_FIELD_NAMES:
            value = cf.get("value")
            if value is None:
                return None
            if isinstance(value, list):
                return "\n".join(str(v) for v in value)
            return str(value)
    return None


def _status_from_checkbox(line: str, *, allow_verified: bool) -> str:
    """Description bullets never become verified; only custom-field checklists may."""
    if re.search(r"\[[xX]\]", line):
        return "verified" if allow_verified else "unknown"
    if re.search(r"\[\s\]", line):
        return "missing"
    return "unknown"


def parse_acceptance_criteria(
    *,
    description: str | None = None,
    custom_fields: list[dict[str, Any]] | None = None,
    updated_on: str | None = None,
) -> AcceptanceCriteria:
    warnings: list[str] = []
    source = _cf_ac_text(custom_fields)
    from_custom_field = bool(source)
    if source:
        warnings.append("parsed_from_custom_field")
    else:
        source = description or ""

    text = source.strip()
    if not text:
        return AcceptanceCriteria(
            groups=[],
            parse_status="empty",
            warnings=warnings or ["no_description_or_ac_field"],
            source_updated_on=updated_on,
        )

    groups: list[AcceptanceGroup] = []
    current: AcceptanceGroup | None = None
    checklist_items = 0
    allow_verified = from_custom_field

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lowered = re.sub(r"^#+\s*", "", line).lower()
        if lowered.startswith("acceptance") or lowered.startswith("điều kiện"):
            continue

        # Letter-style headings: "A.", "### B)", "Nhóm C - ..."
        group_match = None
        if re.match(
            r"^(?:#{1,6}\s*)?(?:nhóm\s+)?[A-Z](?:[\.\):\-]|\s+\-)",
            line,
            re.IGNORECASE,
        ):
            group_match = _LETTER_HEADING_RE.match(line) or _HEADING_RE.match(line)

        if group_match:
            code = group_match.group(1).upper()
            if len(code) > 3:
                continue
            title = group_match.group(2).strip()
            current = AcceptanceGroup(
                code=code,
                title=title,
                status="unknown",
                confidence="low",
            )
            groups.append(current)
            continue

        check = _CHECKLIST_RE.match(line)
        if check:
            checklist_items += 1
            item_status = _status_from_checkbox(line, allow_verified=allow_verified)
            if current is None:
                current = AcceptanceGroup(
                    code=str(len(groups) + 1),
                    title=check.group(1).strip()[:120],
                    status=item_status,  # type: ignore[arg-type]
                    confidence="medium" if allow_verified else "low",
                )
                groups.append(current)
                current = None
            else:
                if item_status == "verified" and current.status in (
                    "unknown",
                    "verified",
                ):
                    current.status = "verified"
                    current.confidence = "medium"
                elif item_status == "missing":
                    if current.status == "verified":
                        current.status = "partial"
                    elif current.status == "unknown":
                        current.status = "missing"
                elif item_status == "verified" and current.status == "missing":
                    current.status = "partial"
            continue

        bullet = _BULLET_RE.match(line)
        if bullet and current is not None and not current.title:
            current.title = bullet.group(1).strip()[:120]

    if not groups:
        # Fallback: treat markdown sections / numbered lines as soft groups
        soft: list[AcceptanceGroup] = []
        for i, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or len(line) < 8:
                continue
            if line.startswith("#") or _BULLET_RE.match(line) or _CHECKLIST_RE.match(
                line
            ):
                title = re.sub(r"^[#\-\*\s\[]+[xX]?\]?\s*", "", line).strip()[:120]
                if title:
                    soft.append(
                        AcceptanceGroup(
                            code=chr(64 + min(i, 26)) if i <= 26 else str(i),
                            title=title,
                            status="unknown",
                            confidence="low",
                        )
                    )
            if len(soft) >= 8:
                break
        if soft:
            return AcceptanceCriteria(
                groups=soft,
                parse_status="needs_manual_review",
                warnings=warnings + ["heuristic_section_fallback"],
                source_updated_on=updated_on,
            )
        return AcceptanceCriteria(
            groups=[],
            parse_status="needs_manual_review",
            warnings=warnings + ["unstructured_description"],
            source_updated_on=updated_on,
        )

    return AcceptanceCriteria(
        groups=groups,
        parse_status="parsed",
        warnings=warnings,
        source_updated_on=updated_on,
    )
