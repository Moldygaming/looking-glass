"""Sync and query the central service work list."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.azure_devops import AzureDevOpsConnector, AzureDevOpsError
from app.connectors.freshservice import FreshserviceConnector, FreshserviceError
from app.connectors.registry import connector_secret, credentials_configured, public_config
from app.models import Connection, ServiceWorkItem
from app.services.service_records import ServiceRecord, clip

log = logging.getLogger("looking-glass.service")

SERVICE_PROVIDERS = ("azure_devops", "freshservice")


class ServiceDeskError(RuntimeError):
    pass


def assigned_to_user_clause(emails: list[str]):
    """Items assigned to this user principal name.

    Azure DevOps uniqueName and the Freshservice agent email are matched to the
    signed-in user's UPN and sign-in address. Display names are not used.
    """
    wanted: list[str] = []
    for raw in emails:
        text = (raw or "").strip().lower()
        if text and "@" in text and text not in wanted:
            wanted.append(text)
    if not wanted:
        return false()
    return or_(
        func.lower(ServiceWorkItem.assignee_email).in_(wanted),
        func.lower(ServiceWorkItem.assignee).in_(wanted),
    )


async def list_service_connections(session: AsyncSession) -> list[Connection]:
    rows = (
        await session.execute(
            select(Connection)
            .where(Connection.provider.in_(SERVICE_PROVIDERS))
            .order_by(Connection.name)
        )
    ).scalars().all()
    return list(rows)


async def summary_counts(
    session: AsyncSession,
    *,
    emails: list[str] | None = None,
    assigned_to_me: bool = False,
) -> dict[str, Any]:
    stmt = (
        select(ServiceWorkItem.kind, func.count())
        .where(ServiceWorkItem.is_open.is_(True))
        .group_by(ServiceWorkItem.kind)
    )
    if assigned_to_me:
        stmt = stmt.where(assigned_to_user_clause(emails or []))
    rows = (await session.execute(stmt)).all()
    counts = {str(kind): int(total) for kind, total in rows}
    work_items = counts.get("work_item", 0)
    tickets = counts.get("ticket", 0)
    problems = counts.get("problem", 0)
    changes = counts.get("change", 0)
    last_sync = (await session.execute(select(func.max(ServiceWorkItem.synced_at)))).scalar_one()
    return {
        "open_work_items": work_items,
        "open_tickets": tickets,
        "open_problems": problems,
        "open_changes": changes,
        "open_total": work_items + tickets + problems + changes,
        "last_sync_at": last_sync,
    }


async def query_items(
    session: AsyncSession,
    *,
    source: str | None = None,
    kind: str | None = None,
    connection_id: UUID | None = None,
    open_only: bool = True,
    q: str | None = None,
    limit: int = 1000,
    emails: list[str] | None = None,
    assigned_to_me: bool = False,
) -> list[tuple[ServiceWorkItem, str]]:
    stmt = (
        select(ServiceWorkItem, Connection.name)
        .join(Connection, Connection.id == ServiceWorkItem.connection_id)
        .order_by(ServiceWorkItem.updated_at.desc().nulls_last(), ServiceWorkItem.title)
        .limit(max(1, min(limit, 1000)))
    )
    if source:
        stmt = stmt.where(ServiceWorkItem.source == source)
    if kind:
        stmt = stmt.where(ServiceWorkItem.kind == kind)
    if connection_id is not None:
        stmt = stmt.where(ServiceWorkItem.connection_id == connection_id)
    if open_only:
        stmt = stmt.where(ServiceWorkItem.is_open.is_(True))
    if assigned_to_me:
        stmt = stmt.where(assigned_to_user_clause(emails or []))
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                func.lower(ServiceWorkItem.title).like(like),
                func.lower(ServiceWorkItem.assignee).like(like),
                func.lower(ServiceWorkItem.assignee_email).like(like),
                func.lower(ServiceWorkItem.requester).like(like),
                func.lower(ServiceWorkItem.external_id).like(like),
                func.lower(ServiceWorkItem.state).like(like),
                func.lower(ServiceWorkItem.project_name).like(like),
                func.lower(ServiceWorkItem.item_type).like(like),
                func.lower(Connection.name).like(like),
            )
        )
    return list((await session.execute(stmt)).all())


async def set_service_project(
    session: AsyncSession, connection_id: UUID, project_id: str, project_name: str
) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None or connection.provider != "azure_devops":
        raise ServiceDeskError("Choose an Azure DevOps connection.")
    project_id = project_id.strip()
    project_name = project_name.strip()
    if not project_id or not project_name:
        raise ServiceDeskError("Project id and name are required.")
    config = dict(connection.config or {})
    config["service_project_id"] = project_id
    config["service_project_name"] = project_name
    connection.config = config
    await session.commit()
    await session.refresh(connection)
    return connection


async def list_ado_projects(connection: Connection) -> list:
    if connection.provider != "azure_devops":
        raise ServiceDeskError("Choose an Azure DevOps connection.")
    if not credentials_configured(connection):
        raise ServiceDeskError("This Azure DevOps connection needs an organisation and a personal access token.")
    try:
        return await AzureDevOpsConnector().list_projects(
            public_config(connection.config or {}), connector_secret(connection)
        )
    except AzureDevOpsError as exc:
        raise ServiceDeskError(str(exc)) from exc


async def sync_service_connections(
    session: AsyncSession, connection_id: UUID | None = None
) -> tuple[int, int, list[str]]:
    rows = await _targets(session, connection_id)
    if connection_id is not None and not rows:
        raise ServiceDeskError("That connection is not an Azure DevOps or Freshservice connection.")
    if not rows:
        raise ServiceDeskError("Add a Freshservice connection or an Azure DevOps connection first.")
    written = 0
    synced = 0
    errors: list[str] = []
    ready = [row for row in rows if _ready_to_sync(row)]
    if not ready:
        raise ServiceDeskError(
            "Choose an Azure DevOps project, or add a Freshservice domain and API key, before syncing."
        )
    for connection in ready:
        try:
            notices: list[str] = []
            written += await sync_service_connection(session, connection, notices)
            errors.extend(f"{connection.name}: {note}" for note in notices)
            synced += 1
        except (ServiceDeskError, AzureDevOpsError, FreshserviceError) as exc:
            await _mark_failure(session, connection, exc)
            errors.append(f"{connection.name}: {exc}")
        except Exception as exc:  # noqa: BLE001 — keep the rest of the sync moving
            log.exception("service sync failed for %s", connection.id)
            await _mark_failure(session, connection, exc)
            errors.append(f"{connection.name}: {exc}")
    return written, synced, errors


async def sync_service_connection(
    session: AsyncSession, connection: Connection, notices: list[str] | None = None
) -> int:
    records, notes = await fetch_records(connection)
    await session.execute(delete(ServiceWorkItem).where(ServiceWorkItem.connection_id == connection.id))
    now = datetime.now(UTC)
    for record in records:
        session.add(_row(connection, record, now))
    if connection.provider == "freshservice":
        connection.status = "connected"
        connection.last_error = notes[0][:2000] if notes else None
        connection.last_ingest_at = now
    if notices is not None:
        notices.extend(notes)
    await session.commit()
    return len(records)


async def sync_devops_work(session: AsyncSession) -> dict[str, int]:
    """Refresh work items for Azure DevOps connections that already have a project.

    Health ingest stays a health scan. This runs separately so a missing Work Items
    scope does not fail the pull-request check.
    """
    rows = (
        await session.execute(select(Connection).where(Connection.provider == "azure_devops"))
    ).scalars().all()
    results: dict[str, int] = {}
    for connection in rows:
        config = connection.config or {}
        if not (config.get("service_project_id") or config.get("service_project_name")):
            continue
        if not credentials_configured(connection):
            continue
        try:
            results[str(connection.id)] = await sync_service_connection(session, connection)
        except Exception as exc:  # noqa: BLE001 — one project should not stop the worker
            log.warning("azure devops work item sync failed for %s: %s", connection.id, exc)
            await session.rollback()
            results[str(connection.id)] = 0
    return results


async def fetch_records(connection: Connection) -> tuple[list[ServiceRecord], list[str]]:
    secret = connector_secret(connection)
    config = public_config(connection.config or {})
    if connection.provider == "freshservice":
        try:
            return await FreshserviceConnector().list_records(config, secret)
        except FreshserviceError as exc:
            raise ServiceDeskError(str(exc)) from exc
    if connection.provider == "azure_devops":
        project_id = str((connection.config or {}).get("service_project_id") or "").strip()
        project_name = await _project_name(connection, config, secret)
        try:
            records = await AzureDevOpsConnector().list_work_items(
                config, secret, project_name, project_id=project_id
            )
        except AzureDevOpsError as exc:
            raise ServiceDeskError(str(exc)) from exc
        return records, []
    raise ServiceDeskError(f"Unsupported service provider {connection.provider}.")


async def _project_name(connection: Connection, config: dict, secret: str | None) -> str:
    stored = connection.config or {}
    project_name = str(stored.get("service_project_name") or "").strip()
    project_id = str(stored.get("service_project_id") or "").strip()
    if project_name:
        return project_name
    if not project_id:
        raise ServiceDeskError("Choose an Azure DevOps project on the Service page before syncing work items.")
    try:
        projects = await AzureDevOpsConnector().list_projects(config, secret)
    except AzureDevOpsError as exc:
        raise ServiceDeskError(str(exc)) from exc
    match = next((row for row in projects if row.id == project_id), None)
    if match is None:
        raise ServiceDeskError("The selected Azure DevOps project is no longer visible.")
    return match.name


def _ready_to_sync(connection: Connection) -> bool:
    if not credentials_configured(connection):
        return False
    if connection.provider == "azure_devops":
        config = connection.config or {}
        return bool(config.get("service_project_id") or config.get("service_project_name"))
    return connection.provider == "freshservice"


async def _targets(session: AsyncSession, connection_id: UUID | None) -> list[Connection]:
    if connection_id is None:
        return await list_service_connections(session)
    connection = await session.get(Connection, connection_id)
    if connection is None or connection.provider not in SERVICE_PROVIDERS:
        return []
    return [connection]


async def _mark_failure(session: AsyncSession, connection: Connection, exc: Exception) -> None:
    await session.rollback()
    fresh = await session.get(Connection, connection.id)
    if fresh is None or fresh.provider != "freshservice":
        return
    fresh.status = "error"
    fresh.last_error = str(exc)[:2000]
    await session.commit()


def _row(connection: Connection, record: ServiceRecord, synced_at: datetime) -> ServiceWorkItem:
    return ServiceWorkItem(
        connection_id=connection.id,
        source=record.source,
        kind=record.kind,
        external_id=clip(record.external_id, 64),
        item_type=clip(record.item_type, 64),
        title=clip(record.title, 512) or record.kind,
        state=clip(record.state, 64),
        status_code=clip(record.status_code, 32),
        priority=clip(record.priority, 32),
        assignee=clip(record.assignee, 256),
        assignee_email=clip(record.assignee_email, 320),
        requester=clip(record.requester, 256),
        project_name=clip(record.project_name, 256),
        url=clip(record.url, 1024),
        is_open=record.is_open,
        opened_at=record.opened_at,
        updated_at=record.updated_at,
        synced_at=synced_at,
    )
