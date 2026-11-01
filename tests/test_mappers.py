"""Mapper unit tests."""
from __future__ import annotations

from mcp_redmine.mappers import (
    approx_tokens,
    decode_cursor,
    encode_cursor,
    map_child,
    map_journals,
    map_snapshot,
)
from tests.conftest import CHILD_ISSUE_ID, PARENT_ISSUE_ID


def test_map_snapshot_children(sample_parent):
    snap = map_snapshot(sample_parent)
    assert snap.id == PARENT_ISSUE_ID
    assert snap.has_children is True
    assert snap.child_count == 1
    assert snap.done_ratio == 100
    assert snap.status and snap.status.is_closed is False
    assert snap.version == "Sprint 2"


def test_map_child(sample_child):
    child = map_child(sample_child)
    assert child.id == CHILD_ISSUE_ID
    assert child.status and child.status.is_closed is False


def test_map_journals_kinds(sample_parent):
    events, truncated, next_offset = map_journals(sample_parent["journals"], limit=10)
    assert len(events) == 1
    assert events[0].kind == "scope_change"
    assert truncated is False
    assert events[0].note_preview is not None
    assert len(events[0].note_preview) <= 280


def test_cursor_roundtrip():
    c = encode_cursor(30)
    assert decode_cursor(c) == 30
    assert decode_cursor(None) == 0


def test_approx_tokens():
    assert approx_tokens({"a": "hello"}) > 0
