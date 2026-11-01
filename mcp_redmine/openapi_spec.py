"""Lazy loader for the bundled Redmine OpenAPI document (discovery only)."""
from __future__ import annotations

import functools
import pathlib
from typing import Any

import yaml

_SPEC_PATH = pathlib.Path(__file__).parent / "redmine_openapi.yml"
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)
_MAX_PATH_INFO = 10


@functools.lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    with open(_SPEC_PATH, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec, dict):
        return {"paths": {}}
    spec.setdefault("paths", {})
    return spec


def list_paths() -> list[str]:
    """Return path templates that expose a GET operation."""
    paths = load_spec().get("paths", {})
    out: list[str] = []
    for path, ops in paths.items():
        if isinstance(ops, dict) and "get" in ops:
            out.append(path)
    return out


def path_info(path_templates: list[str]) -> dict[str, Any]:
    """Return GET-only operation details for up to 10 path templates."""
    paths = load_spec().get("paths", {})
    result: dict[str, Any] = {}
    for template in path_templates[:_MAX_PATH_INFO]:
        ops = paths.get(template)
        if not isinstance(ops, dict) or "get" not in ops:
            continue
        filtered = {
            key: value
            for key, value in ops.items()
            if key not in _HTTP_METHODS or key == "get"
        }
        result[template] = filtered
    return result
