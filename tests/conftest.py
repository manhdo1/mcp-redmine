"""Shared fixtures. Do not require Redmine env at collection time."""
from __future__ import annotations

import pytest

from mcp_redmine.client import RedmineClient
from mcp_redmine.config import Settings

# Synthetic IDs — not real tickets
PARENT_ISSUE_ID = 1001
CHILD_ISSUE_ID = 1002


@pytest.fixture
def settings() -> Settings:
    return Settings(
        redmine_url="https://redmine.example.org/",
        api_key="test-api-key-123",
        read_only=True,
    )


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> RedmineClient:
    c = RedmineClient(settings)
    yield c
    c.close()


SAMPLE_PARENT_DESCRIPTION = """
## Acceptance Criteria

### A. Upload pipeline
- [ ] Compress images before S3
- [ ] Retry failed uploads

### B. Web UI Card
- [ ] No jank on scroll
- [ ] Windowed rendering

### C. Batch S3
- [ ] Batch delete
- [ ] Batch restore

### D. FE Card/Grid/Slide performance
- [ ] Home slide smooth
- [x] Partial host windowed rendering

### E. Regression
- [ ] Smoke on UAT
"""

SAMPLE_PARENT = {
    "id": PARENT_ISSUE_ID,
    "subject": "[Demo] Optimize upload and card rendering",
    "description": SAMPLE_PARENT_DESCRIPTION,
    "tracker": {"id": 2, "name": "User Story"},
    "project": {"id": 12, "name": "Demo Project"},
    "status": {"id": 7, "name": "Ready to Dev", "is_closed": False},
    "done_ratio": 100,
    "closed_on": None,
    "spent_hours": 0,
    "estimated_hours": 18,
    "fixed_version": {"id": 19, "name": "Sprint 2"},
    "assigned_to": {"id": 35, "name": "Test User"},
    "start_date": "2026-10-06",
    "due_date": None,
    "updated_on": "2026-10-31T10:00:00Z",
    "children": [{"id": CHILD_ISSUE_ID, "subject": "Home slide jank"}],
    "custom_fields": [],
    "journals": [
        {
            "id": 9981,
            "created_on": "2026-10-20T09:12:00Z",
            "user": {"id": 8, "name": "Lead"},
            "notes": "Add upload, FE card, batch S3...",
            "details": [
                {"name": "status_id", "old_value": "1", "new_value": "7"},
                {"name": "estimated_hours", "old_value": "8", "new_value": "18"},
                {"name": "description", "old_value": "old", "new_value": "new"},
            ],
        }
    ],
}

SAMPLE_CHILD = {
    "id": CHILD_ISSUE_ID,
    "subject": "Home slide jank",
    "tracker": {"id": 1, "name": "Bug"},
    "project": {"id": 12, "name": "Demo Project"},
    "status": {"id": 9, "name": "Ready for Test", "is_closed": False},
    "done_ratio": 100,
    "closed_on": None,
    "fixed_version": {"id": 18, "name": "Sprint 1"},
    "assigned_to": {"id": 35, "name": "Test User"},
}


@pytest.fixture
def sample_parent() -> dict:
    return dict(SAMPLE_PARENT)


@pytest.fixture
def sample_child() -> dict:
    return dict(SAMPLE_CHILD)
