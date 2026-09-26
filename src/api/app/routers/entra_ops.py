"""Licenses, templates, CSV bulk changes, password reset, and the directory audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_privilege
from app.db import get_session
from app.entra.audit import record_audit
from app.entra.bulk import parse_bulk_csv, validate_usage_location
from app.entra.graph import GraphClient, GraphError
from app.entra.provision import (
    DirectoryError,
    actor_from,
    apply_bulk_row,
    change_licenses,
    reset_password,
)
from app.entra.skus import friendly_sku_name
from app.entra.sync import upsert_license_skus
from app.models import EntraAuditEvent, EntraLicenseSku, EntraUserTemplate, User
from app.routers.entra import DIRECTORY_OPERATE, _app_assignments_for, _directory_http, _get_tenant, _graph_http, _user_out
from app.schemas import (
    CurrentUser,
    EntraAuditOut,
    EntraBulkIn,
    EntraBulkOut,
    EntraBulkRowOut,
    EntraLicenseOut,
    EntraTemplateIn,
    EntraTemplateOut,
    EntraTemplatePatch,
    EntraUserOut,
    LicenseChangeIn,
    PasswordResetIn,
)

router = APIRouter(prefix="/admin/entra", tags=["entra"])


def _plans(raw) -> list[str]:
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str) and item:
            names.append(item)
    return names


def _license_out(row: EntraLicenseSku) -> EntraLicenseOut:
    part = row.sku_part_number or ""
    enabled = int(row.enabled_units or 0)
    consumed = int(row.consumed_units or 0)
    return EntraLicenseOut(
        id=row.id,
        tenant_id=row.tenant_id,
        sku_id=row.sku_id,
        sku_part_number=part,
        display_name=friendly_sku_name(part) or part or row.sku_id,
        consumed_units=consumed,
        enabled_units=enabled,
        suspended_units=int(row.suspended_units or 0),
        warning_units=int(row.warning_units or 0),
        available_units=max(enabled - consumed, 0),
        capability_status=row.capability_status or "",
        service_plans=_plans(row.service_plans),
    )


def _template_out(row: EntraUserTemplate) -> EntraTemplateOut:
    return EntraTemplateOut(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description or "",
        department=row.department or "",
        job_title=row.job_title or "",
        usage_location=row.usage_location or "",
        group_ids=list(row.group_ids or []),
        license_sku_ids=list(row.license_sku_ids or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _location(value: str) -> str:
    try:
        return validate_usage_location(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ids(values: list[str] | None) -> list[str]:
    return [item.strip() for item in (values or []) if item and item.strip()]


async def _audit(session, actor: CurrentUser, **kwargs) -> None:
    who = actor_from(actor)
    await record_audit(session, actor_id=who.id, actor_email=who.email, actor_name=who.name, **kwargs)


@router.get("/licenses", response_model=list[EntraLicenseOut])
async def list_licenses(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read")),
):
    rows = (
        await session.execute(
            select(EntraLicenseSku).where(EntraLicenseSku.tenant_id == tenant_id).order_by(EntraLicenseSku.sku_part_number)
        )
    ).scalars().all()
    return [_license_out(row) for row in rows]


@router.post("/licenses/refresh", response_model=list[EntraLicenseOut])
async def refresh_licenses(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, tenant_id)
    try:
        skus = await GraphClient.from_tenant(tenant).list_subscribed_skus()
    except GraphError as exc:
        raise _graph_http(exc) from exc
    await upsert_license_skus(session, skus, tenant)
    await session.commit()
    return await list_licenses(tenant_id, session, _)


@router.post("/users/{user_id}/password", response_model=EntraUserOut)
async def reset_directory_password(
    user_id: UUID,
    body: PasswordResetIn,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege(*DIRECTORY_OPERATE)),
):
    user = await session.get(User, user_id)
    if user is None or user.source != "entra":
        raise HTTPException(status_code=404, detail="User not found")
    force = body.force_change if actor.has("admin.entra.write") else True
    try:
        password = await reset_password(session, user, actor_from(actor), body.password, force_change=force)
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return _user_out(user, password, app_assignments=await _app_assignments_for(session, user.entra_oid))


@router.post("/users/{user_id}/licenses", response_model=EntraUserOut)
async def update_directory_licenses(
    user_id: UUID,
    body: LicenseChangeIn,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    user = await session.get(User, user_id)
    if user is None or user.source != "entra":
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = await change_licenses(
            session,
            user,
            actor_from(actor),
            body.add_sku_ids,
            body.remove_sku_ids,
            body.usage_location,
        )
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return _user_out(user, app_assignments=await _app_assignments_for(session, user.entra_oid))


@router.get("/templates", response_model=list[EntraTemplateOut])
async def list_templates(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read", "admin.entra.write")),
):
    rows = (
        await session.execute(
            select(EntraUserTemplate).where(EntraUserTemplate.tenant_id == tenant_id).order_by(EntraUserTemplate.name)
        )
    ).scalars().all()
    return [_template_out(row) for row in rows]


@router.post("/templates", response_model=EntraTemplateOut)
async def create_template(
    body: EntraTemplateIn,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    await _get_tenant(session, body.tenant_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Template name is required")
    row = EntraUserTemplate(
        tenant_id=body.tenant_id,
        name=name,
        description=body.description.strip(),
        department=body.department.strip(),
        job_title=body.job_title.strip(),
        usage_location=_location(body.usage_location),
        group_ids=_ids(body.group_ids),
        license_sku_ids=_ids(body.license_sku_ids),
    )
    session.add(row)
    await _audit(
        session,
        actor,
        tenant_id=body.tenant_id,
        action="template.create",
        target_type="template",
        target_id=name,
        target_label=name,
        after={"department": row.department, "job_title": row.job_title, "usage_location": row.usage_location},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A template with that name already exists") from exc
    await session.refresh(row)
    return _template_out(row)


@router.patch("/templates/{template_id}", response_model=EntraTemplateOut)
async def patch_template(
    template_id: UUID,
    body: EntraTemplatePatch,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    row = await session.get(EntraUserTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    before = {"name": row.name, "department": row.department, "job_title": row.job_title, "usage_location": row.usage_location}
    if body.name is not None:
        cleaned = body.name.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Template name is required")
        row.name = cleaned
    if body.description is not None:
        row.description = body.description.strip()
    if body.department is not None:
        row.department = body.department.strip()
    if body.job_title is not None:
        row.job_title = body.job_title.strip()
    if body.usage_location is not None:
        row.usage_location = _location(body.usage_location)
    if body.group_ids is not None:
        row.group_ids = _ids(body.group_ids)
    if body.license_sku_ids is not None:
        row.license_sku_ids = _ids(body.license_sku_ids)
    flag_modified(row, "group_ids")
    flag_modified(row, "license_sku_ids")
    row.updated_at = datetime.now(UTC)
    await _audit(
        session,
        actor,
        tenant_id=row.tenant_id,
        action="template.update",
        target_type="template",
        target_id=str(row.id),
        target_label=row.name,
        before=before,
        after={"name": row.name, "department": row.department, "job_title": row.job_title, "usage_location": row.usage_location},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A template with that name already exists") from exc
    await session.refresh(row)
    return _template_out(row)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    row = await session.get(EntraUserTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await _audit(
        session,
        actor,
        tenant_id=row.tenant_id,
        action="template.delete",
        target_type="template",
        target_id=str(row.id),
        target_label=row.name,
        before={"name": row.name},
    )
    await session.delete(row)
    await session.commit()
    return {"ok": True}


@router.post("/bulk", response_model=EntraBulkOut)
async def bulk_directory(
    body: EntraBulkIn,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, body.tenant_id)
    try:
        rows = parse_bulk_csv(body.csv)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    results: list[EntraBulkRowOut] = []
    ok = 0
    failed = 0
    who = actor_from(actor)
    for row in rows:
        try:
            detail = await apply_bulk_row(session, tenant, who, row)
            results.append(
                EntraBulkRowOut(row=row.line, action=row.action, user_principal_name=row.user_principal_name, status="ok", detail=detail)
            )
            ok += 1
        except (DirectoryError, GraphError) as exc:
            message = exc.message if isinstance(exc, (DirectoryError, GraphError)) else str(exc)
            results.append(
                EntraBulkRowOut(
                    row=row.line,
                    action=row.action,
                    user_principal_name=row.user_principal_name,
                    status="error",
                    detail=message,
                )
            )
            failed += 1
    return EntraBulkOut(ok=ok, failed=failed, results=results)


@router.get("/audit", response_model=list[EntraAuditOut])
async def list_audit(
    tenant_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read")),
):
    stmt = select(EntraAuditEvent).order_by(EntraAuditEvent.created_at.desc()).limit(limit)
    if tenant_id is not None:
        stmt = stmt.where(EntraAuditEvent.tenant_id == tenant_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        EntraAuditOut(
            id=row.id,
            tenant_id=row.tenant_id,
            actor_email=row.actor_email or "",
            actor_name=row.actor_name or "",
            action=row.action,
            target_type=row.target_type or "",
            target_id=row.target_id or "",
            target_label=row.target_label or "",
            before=row.before,
            after=row.after,
            graph_request_id=row.graph_request_id,
            status=row.status,
            error=row.error,
            created_at=row.created_at,
        )
        for row in rows
    ]
