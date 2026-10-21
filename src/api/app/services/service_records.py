"""Normalized service-desk rows shared by Azure DevOps and Freshservice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ServiceRecord:
    source: str
    kind: str
    external_id: str
    title: str
    item_type: str = ""
    state: str = ""
    status_code: str = ""
    priority: str = ""
    assignee: str = ""
    assignee_email: str = ""
    requester: str = ""
    project_name: str = ""
    url: str = ""
    is_open: bool = True
    opened_at: datetime | None = None
    updated_at: datetime | None = None


def clip(value: object, limit: int) -> str:
    text = "" if value is None else str(value).strip()
    return text[:limit]
