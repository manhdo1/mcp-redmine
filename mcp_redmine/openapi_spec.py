"""Lazy loader for the bundled Redmine OpenAPI document (discovery only)."""
from __future__ import annotations

import functools
import pathlib
from typing import Any

import yaml

_SPEC_PATH = pathlib.Path(__file__).parent / "redmine_openapi.yml"


@functools.lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    with open(_SPEC_PATH, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec, dict):
        return {"paths": {}}
    spec.setdefault("paths", {})
    return spec


def list_paths() -> list[str]:
    return list(load_spec().get("paths", {}).keys())


def path_info(path_templates: list[str]) -> dict[str, Any]:
    paths = load_spec().get("paths", {})
    return {p: paths[p] for p in path_templates if p in paths}
