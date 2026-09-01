from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_privilege
from app.connectors.registry import (
    credentials_configured,
    merge_secrets,
    public_config,
    run_connection_ingest,
    test_connection,
)
from app.db import get_session
from app.models import Connection
from app.schemas import ConnectionIn, ConnectionOut, ConnectionUpdate, CurrentUser
from app.services.recommend import refresh_recommendations

router = APIRouter(prefix="/connections", tags=["connections"])


def _out(row: Connection) -> ConnectionOut:
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


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.read")),
):
    rows = (await session.execute(select(Connection).order_by(Connection.name))).scalars().all()
    return [_out(row) for row in rows]


@router.post("", response_model=ConnectionOut)
async def create_connection(
    body: ConnectionIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.write")),
):
    secrets = merge_secrets({}, body.secrets.model_dump() if body.secrets else None)
    connection = Connection(
        name=body.name,
        provider=body.provider,
        status="pending",
        config=public_config(body.config),
        secrets=secrets,
        secret_ref=body.secret_ref,
    )
    if credentials_configured(connection):
        connection.status = "ready"
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return _out(connection)


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.read")),
):
    return _out(await _get(session, connection_id))


@router.put("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: UUID,
    body: ConnectionUpdate,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.write")),
):
    connection = await _get(session, connection_id)
    if body.name is not None:
        connection.name = body.name
    if body.config is not None:
        connection.config = public_config(body.config)
    if body.secrets is not None:
        connection.secrets = merge_secrets(connection.secrets, body.secrets.model_dump())
    if body.secret_ref is not None:
        connection.secret_ref = body.secret_ref
    connection.status = "ready" if credentials_configured(connection) else "pending"
    connection.last_error = None
    await session.commit()
    await session.refresh(connection)
    return _out(connection)


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.write")),
):
    connection = await _get(session, connection_id)
    await session.delete(connection)
    await session.commit()
    return {"ok": True}


@router.post("/{connection_id}/test")
async def test_existing_connection(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.write")),
):
    connection = await _get(session, connection_id)
    try:
        message = await test_connection(connection)
        connection.status = "ready"
        connection.last_error = None
        await session.commit()
        return {"ok": True, "message": message}
    except Exception as exc:  # noqa: BLE001 — return connector validation errors to the UI
        connection.status = "error"
        connection.last_error = str(exc)
        await session.commit()
        return {"ok": False, "message": str(exc)}


@router.post("/{connection_id}/ingest")
async def ingest_connection(
    connection_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("connections.write")),
):
    connection = await _get(session, connection_id)
    if not credentials_configured(connection):
        raise HTTPException(
            status_code=400,
            detail="This connection is missing credentials or required settings.",
        )
    try:
        written = await run_connection_ingest(session, connection_id)
    except Exception as exc:  # noqa: BLE001 — return Azure/AWS/GCP ingest errors to the UI
        raise HTTPException(status_code=400, detail=str(exc)[:2000]) from exc
    try:
        await refresh_recommendations(session)
    except Exception:  # noqa: BLE001 — cost rows are already stored
        pass
    return {"written": written}


async def _get(session: AsyncSession, connection_id: UUID) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection
