"""Directory audit rows for Entra writes performed by Looking Glass."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EntraAuditEvent

_SECRET_KEYS = {"password", "passwordprofile", "client_secret", "temporary_password", "secret"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                cleaned[key] = "***"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


async def record_audit(
    session: AsyncSession,
    *,
    actor_id: UUID | None,
    actor_email: str,
    actor_name: str,
    tenant_id: UUID | None,
    action: str,
    target_type: str,
    target_id: str,
    target_label: str,
    before: dict | None = None,
    after: dict | None = None,
    graph_request_id: str | None = None,
    status: str = "ok",
    error: str | None = None,
) -> None:
    session.add(
        EntraAuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            actor_email=actor_email or "",
            actor_name=actor_name or "",
            action=action,
            target_type=target_type,
            target_id=str(target_id or ""),
            target_label=target_label or "",
            before=redact(before) if before is not None else None,
            after=redact(after) if after is not None else None,
            graph_request_id=graph_request_id or None,
            status=status,
            error=(error or "")[:4000] or None,
        )
    )
