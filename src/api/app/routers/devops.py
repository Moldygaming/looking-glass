from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_privilege
from app.connectors.azure_devops import AzureDevOpsError
from app.connectors.registry import credentials_configured, public_config
from app.db import get_session
from app.models import Connection
from app.schemas import (
    ConnectionOut,
    CurrentUser,
    DevOpsProjectOut,
    DevOpsProjectSelectIn,
    DevOpsReportOut,
    DevOpsScanOut,
)
from app.services.devops import (
    build_report,
    list_ado_connections,
    refresh_projects,
    run_devops_scan,
    set_monitored_projects,
)

router = APIRouter(prefix="/devops", tags=["devops"])


def _connection_out(row: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        status=row.status,
        config=public_config(row.config),
        credentials_configured=credentials_configured(row),
        last_ingest_at=row.last_ingest_at,
        last_error=row.last_error,
        created_at=row.created_at,
    )


@router.get("/connections", response_model=list[ConnectionOut])
async def devops_connections(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.read")),
):
    return [_connection_out(row) for row in await list_ado_connections(session)]


@router.get("/report", response_model=DevOpsReportOut)
async def devops_report(
    connection_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.read")),
):
    connection = await _pick_connection(session, connection_id)
    return await build_report(session, connection)


@router.get("/projects", response_model=list[DevOpsProjectOut])
async def devops_projects(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.read")),
):
    connection = await _pick_connection(session, connection_id)
    report = await build_report(session, connection)
    return report.projects


@router.post("/projects/refresh", response_model=list[DevOpsProjectOut])
async def devops_refresh_projects(
    connection_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.write", "connections.write")),
):
    try:
        rows = await refresh_projects(session, connection_id)
    except AzureDevOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        DevOpsProjectOut(
            id=row.id,
            ado_project_id=row.ado_project_id,
            name=row.name,
            description=row.description,
            url=row.url,
            state=row.state,
            monitored=row.monitored,
            last_scan_at=row.last_scan_at,
        )
        for row in rows
    ]


@router.put("/projects", response_model=list[DevOpsProjectOut])
async def devops_select_projects(
    body: DevOpsProjectSelectIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.write", "connections.write")),
):
    try:
        rows = await set_monitored_projects(session, body.connection_id, body.project_ids)
    except AzureDevOpsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        DevOpsProjectOut(
            id=row.id,
            ado_project_id=row.ado_project_id,
            name=row.name,
            description=row.description,
            url=row.url,
            state=row.state,
            monitored=row.monitored,
            last_scan_at=row.last_scan_at,
        )
        for row in rows
    ]


@router.post("/scan", response_model=DevOpsScanOut)
async def devops_scan(
    connection_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("devops.write", "connections.write")),
):
    try:
        return await run_devops_scan(session, connection_id)
    except AzureDevOpsError as exc:
        connection = await session.get(Connection, connection_id)
        if connection is not None and connection.provider == "azure_devops":
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _pick_connection(session: AsyncSession, connection_id: UUID | None) -> Connection:
    if connection_id is not None:
        connection = await session.get(Connection, connection_id)
        if connection is None or connection.provider != "azure_devops":
            raise HTTPException(status_code=404, detail="Azure DevOps connection not found")
        return connection
    rows = await list_ado_connections(session)
    if not rows:
        raise HTTPException(status_code=404, detail="No Azure DevOps organisation is connected yet.")
    return rows[0]
