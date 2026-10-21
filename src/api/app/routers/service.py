import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_privilege
from app.connectors.registry import credentials_configured
from app.db import get_session
from app.models import Connection, User
from app.schemas import (
    CurrentUser,
    ServiceAdoProjectOut,
    ServiceConnectionOut,
    ServiceProjectIn,
    ServiceSummaryOut,
    ServiceSyncOut,
    ServiceWorkItemOut,
)
from app.services.service_desk import (
    ServiceDeskError,
    list_ado_projects,
    list_service_connections,
    query_items,
    set_service_project,
    summary_counts,
    sync_service_connections,
)

log = logging.getLogger("looking-glass.service")
router = APIRouter(prefix="/service", tags=["service"])


def _connection_out(row: Connection) -> ServiceConnectionOut:
    config = row.config or {}
    return ServiceConnectionOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        status=row.status,
        credentials_configured=credentials_configured(row),
        last_ingest_at=row.last_ingest_at,
        last_error=row.last_error,
        service_project_id=str(config.get("service_project_id") or ""),
        service_project_name=str(config.get("service_project_name") or ""),
        domain=str(config.get("domain") or ""),
    )


@router.get("/summary", response_model=ServiceSummaryOut)
async def service_summary(
    assigned_to_me: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("service.read")),
):
    emails = await _viewer(session, user)
    return ServiceSummaryOut(**await summary_counts(session, emails=emails, assigned_to_me=assigned_to_me))


@router.get("/items", response_model=list[ServiceWorkItemOut])
async def service_items(
    source: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    connection_id: UUID | None = Query(default=None),
    open_only: bool = Query(default=True),
    assigned_to_me: bool = Query(default=True),
    q: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("service.read")),
):
    emails = await _viewer(session, user)
    rows = await query_items(
        session,
        source=source or None,
        kind=kind or None,
        connection_id=connection_id,
        open_only=open_only,
        q=q,
        emails=emails,
        assigned_to_me=assigned_to_me,
    )
    return [
        ServiceWorkItemOut(
            id=item.id,
            connection_id=item.connection_id,
            connection_name=name,
            source=item.source,
            kind=item.kind,
            item_type=item.item_type,
            external_id=item.external_id,
            title=item.title,
            state=item.state,
            priority=item.priority,
            assignee=item.assignee_email or item.assignee,
            requester=item.requester,
            project_name=item.project_name,
            url=item.url,
            is_open=item.is_open,
            opened_at=item.opened_at,
            updated_at=item.updated_at,
        )
        for item, name in rows
    ]


@router.get("/connections", response_model=list[ServiceConnectionOut])
async def service_connections(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("service.read")),
):
    return [_connection_out(row) for row in await list_service_connections(session)]


@router.get("/projects", response_model=list[ServiceAdoProjectOut])
async def service_projects(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("service.read")),
):
    connection = await _connection(session, connection_id)
    try:
        rows = await list_ado_projects(connection)
    except ServiceDeskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        ServiceAdoProjectOut(id=row.id, name=row.name, description=row.description, state=row.state)
        for row in rows
    ]


@router.put("/project", response_model=ServiceConnectionOut)
async def service_select_project(
    body: ServiceProjectIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("service.write", "connections.write")),
):
    try:
        connection = await set_service_project(session, body.connection_id, body.project_id, body.project_name)
    except ServiceDeskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _connection_out(connection)


@router.post("/sync", response_model=ServiceSyncOut)
async def service_sync(
    connection_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("service.write", "connections.write")),
):
    try:
        written, count, errors = await sync_service_connections(session, connection_id)
    except ServiceDeskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("service sync failed")
        await session.rollback()
        detail = str(exc).strip()[:500] or "Service sync failed."
        raise HTTPException(status_code=400, detail=detail) from exc
    return ServiceSyncOut(written=written, connections=count, errors=errors)


async def _viewer(session: AsyncSession, user: CurrentUser) -> list[str]:
    """Addresses that identify the signed-in user. UPN comes before the mail alias."""
    emails: list[str] = []
    row = await session.get(User, user.id)
    if row is not None and row.user_principal_name:
        emails.append(row.user_principal_name)
    if user.email:
        emails.append(user.email)
    return emails


async def _connection(session: AsyncSession, connection_id: UUID) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection
