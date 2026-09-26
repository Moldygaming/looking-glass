"""Entra ID directory administration."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import require_privilege
from app.db import get_session
from app.entra.audit import record_audit
from app.entra.graph import GraphClient, GraphError
from app.entra.provision import (
    DirectoryError,
    actor_from,
    add_group_member,
    create_directory_user as provision_user,
    remove_group_member,
    set_account_enabled,
    update_profile,
)
from app.entra.skus import assigned_from_graph, friendly_sku_name
from app.entra.sync import (
    credentials_configured,
    latest_run,
    sync_directory,
    upsert_group_from_graph,
)
from app.models import EntraAppAssignment, EntraApplication, EntraGroup, EntraMembership, EntraTenant, User
from app.schemas import (
    AssignedLicenseOut,
    CurrentUser,
    DirectorySyncOut,
    EntraAppAssignmentOut,
    EntraAppAssignmentRef,
    EntraAppOut,
    EntraAppRoleOut,
    EntraGroupCreate,
    EntraGroupOut,
    EntraGroupPatch,
    EntraMemberIn,
    EntraMemberOut,
    EntraStatusOut,
    EntraTenantCreate,
    EntraTenantOut,
    EntraTenantPatch,
    EntraUserCreate,
    EntraUserOut,
    EntraUserPatch,
)

router = APIRouter(prefix="/admin/entra", tags=["entra"])

GRAPH_PERMISSIONS = [
    "User.ReadWrite.All",
    "Group.ReadWrite.All",
    "Directory.Read.All",
]


def _sync_out(run) -> DirectorySyncOut | None:
    if run is None:
        return None
    return DirectorySyncOut(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        users_upserted=run.users_upserted,
        groups_upserted=run.groups_upserted,
        memberships_upserted=run.memberships_upserted,
        apps_upserted=getattr(run, "apps_upserted", 0) or 0,
        assignments_upserted=getattr(run, "assignments_upserted", 0) or 0,
        tenant_id=getattr(run, "tenant_id", None),
        error=run.error,
    )


def _assigned_out(user: User) -> list[AssignedLicenseOut]:
    rows: list[AssignedLicenseOut] = []
    for item in assigned_from_graph(getattr(user, "assigned_licenses", None)):
        part = item["sku_part_number"]
        rows.append(
            AssignedLicenseOut(
                sku_id=item["sku_id"],
                sku_part_number=part,
                display_name=friendly_sku_name(part) or part or item["sku_id"],
                disabled_plans=item["disabled_plans"],
            )
        )
    return rows


def _user_out(
    user: User,
    password: str | None = None,
    app_assignments: list[EntraAppAssignmentRef] | None = None,
    warnings: list[str] | None = None,
) -> EntraUserOut:
    return EntraUserOut(
        id=user.id,
        entra_oid=user.entra_oid,
        email=user.email,
        display_name=user.display_name,
        user_principal_name=user.user_principal_name or "",
        job_title=user.job_title or "",
        department=user.department or "",
        usage_location=user.usage_location or "",
        status=user.status or "active",
        source=user.source or "local",
        entra_tenant_id=user.entra_tenant_id,
        last_synced_at=user.last_synced_at,
        last_login_at=user.last_login_at,
        temporary_password=password,
        assigned_licenses=_assigned_out(user),
        warnings=warnings or [],
        app_assignments=app_assignments or [],
    )


async def _app_assignments_for(session: AsyncSession, principal_id: str) -> list[EntraAppAssignmentRef]:
    if not principal_id:
        return []
    rows = (
        await session.execute(
            select(EntraAppAssignment, EntraApplication)
            .join(EntraApplication, EntraAppAssignment.application_id == EntraApplication.id)
            .where(EntraAppAssignment.principal_id == principal_id)
            .order_by(EntraApplication.display_name, EntraAppAssignment.app_role_name)
        )
    ).all()
    return [
        EntraAppAssignmentRef(
            application_id=app.id,
            display_name=app.display_name,
            app_id=app.app_id,
            app_role_id=row.app_role_id,
            app_role_name=row.app_role_name or "Default access",
            assignment_required=bool(app.assignment_required),
            is_microsoft=bool(app.is_microsoft),
            has_app_registration=bool(app.has_app_registration),
        )
        for row, app in rows
    ]


def _app_roles(app: EntraApplication) -> list[EntraAppRoleOut]:
    roles = []
    for role in app.app_roles or []:
        if not isinstance(role, dict):
            continue
        roles.append(
            EntraAppRoleOut(
                id=str(role.get("id") or ""),
                display_name=str(role.get("displayName") or role.get("value") or "Role"),
                value=str(role.get("value") or ""),
                description=str(role.get("description") or ""),
                enabled=bool(role.get("isEnabled", True)),
                allowed_member_types=[str(item) for item in (role.get("allowedMemberTypes") or [])],
            )
        )
    return roles


async def _assignment_counts(session: AsyncSession) -> dict[UUID, dict[str, int]]:
    rows = (
        await session.execute(
            select(EntraAppAssignment.application_id, EntraAppAssignment.principal_type, func.count()).group_by(
                EntraAppAssignment.application_id, EntraAppAssignment.principal_type
            )
        )
    ).all()
    out: dict[UUID, dict[str, int]] = {}
    for application_id, kind, n in rows:
        out.setdefault(application_id, {})[str(kind)] = int(n)
    return out


async def _app_out(
    session: AsyncSession,
    app: EntraApplication,
    with_assignments: bool = False,
    counts: dict[str, int] | None = None,
) -> EntraAppOut:
    if counts is None:
        rows = (
            await session.execute(
                select(EntraAppAssignment.principal_type, func.count())
                .where(EntraAppAssignment.application_id == app.id)
                .group_by(EntraAppAssignment.principal_type)
            )
        ).all()
        by_type = {str(kind): int(n) for kind, n in rows}
    else:
        by_type = counts
    assignments: list[EntraAppAssignmentOut] = []
    if with_assignments:
        rows = (
            await session.execute(
                select(EntraAppAssignment)
                .where(EntraAppAssignment.application_id == app.id)
                .order_by(EntraAppAssignment.principal_type, EntraAppAssignment.principal_display_name)
            )
        ).scalars().all()
        user_ids = [row.user_id for row in rows if row.user_id]
        users = {}
        if user_ids:
            users = {
                u.id: u
                for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            }
        missing_oids = [row.principal_id for row in rows if row.principal_type == "User" and not row.user_id]
        by_oid = {}
        if missing_oids:
            by_oid = {
                u.entra_oid: u
                for u in (await session.execute(select(User).where(User.entra_oid.in_(missing_oids)))).scalars().all()
            }
        for row in rows:
            user = (users.get(row.user_id) if row.user_id else None) or by_oid.get(row.principal_id)
            assignments.append(
                EntraAppAssignmentOut(
                    id=row.id,
                    assignment_id=row.assignment_id,
                    principal_id=row.principal_id,
                    principal_type=row.principal_type,
                    principal_display_name=row.principal_display_name
                    or (user.display_name if user else row.principal_id),
                    app_role_id=row.app_role_id,
                    app_role_name=row.app_role_name or "Default access",
                    user_id=user.id if user else row.user_id,
                    group_id=row.group_id,
                    email=user.email if user else None,
                    user_principal_name=user.user_principal_name if user else None,
                    status=user.status if user else None,
                )
            )
    return EntraAppOut(
        id=app.id,
        tenant_id=app.tenant_id,
        service_principal_id=app.service_principal_id,
        app_id=app.app_id,
        application_object_id=app.application_object_id or "",
        display_name=app.display_name,
        description=app.description or "",
        publisher_name=app.publisher_name or "",
        account_enabled=bool(app.account_enabled),
        assignment_required=bool(app.assignment_required),
        sign_in_audience=app.sign_in_audience or "",
        homepage=app.homepage or "",
        is_microsoft=bool(app.is_microsoft),
        hidden=bool(app.hidden),
        has_app_registration=bool(app.has_app_registration),
        user_assignment_count=by_type.get("User", 0),
        group_assignment_count=by_type.get("Group", 0),
        last_synced_at=app.last_synced_at,
        app_roles=_app_roles(app),
        assignments=assignments,
    )


async def _group_out(
    session: AsyncSession,
    group: EntraGroup,
    with_members: bool = False,
    with_apps: bool = False,
) -> EntraGroupOut:
    members: list[EntraMemberOut] = []
    if with_members:
        rows = (
            await session.execute(
                select(EntraMembership).where(EntraMembership.group_id == group.id)
            )
        ).scalars().all()
        user_ids = [row.user_id for row in rows if row.user_id]
        users = {}
        if user_ids:
            users = {
                u.id: u
                for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            }
        by_oid = {}
        missing = [row.entra_user_id for row in rows if not row.user_id]
        if missing:
            by_oid = {
                u.entra_oid: u
                for u in (await session.execute(select(User).where(User.entra_oid.in_(missing)))).scalars().all()
            }
        for row in rows:
            user = (users.get(row.user_id) if row.user_id else None) or by_oid.get(row.entra_user_id)
            members.append(
                EntraMemberOut(
                    entra_user_id=row.entra_user_id,
                    user_id=user.id if user else row.user_id,
                    display_name=user.display_name if user else None,
                    email=user.email if user else None,
                    user_principal_name=user.user_principal_name if user else None,
                    status=user.status if user else None,
                )
            )
    count = await session.scalar(
        select(func.count()).select_from(EntraMembership).where(EntraMembership.group_id == group.id)
    )
    return EntraGroupOut(
        id=group.id,
        tenant_id=group.tenant_id,
        entra_id=group.entra_id,
        display_name=group.display_name,
        description=group.description or "",
        mail=group.mail or "",
        mail_nickname=group.mail_nickname or "",
        security_enabled=bool(group.security_enabled),
        mail_enabled=bool(group.mail_enabled),
        member_count=int(count or 0),
        last_synced_at=group.last_synced_at,
        members=members,
        app_assignments=await _app_assignments_for(session, group.entra_id) if with_apps else [],
    )


def _graph_http(exc: GraphError) -> HTTPException:
    status = exc.status if exc.status in {400, 401, 403, 404, 409} else 400
    return HTTPException(status_code=status, detail=exc.message)


def _directory_http(exc: DirectoryError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


DIRECTORY_READ = ("admin.entra.read", "admin.entra.helpdesk", "admin.users.read")
DIRECTORY_OPERATE = ("admin.entra.write", "admin.entra.helpdesk")


async def _get_tenant(session: AsyncSession, tenant_id: UUID) -> EntraTenant:
    tenant = await session.get(EntraTenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _client(tenant: EntraTenant) -> GraphClient:
    return GraphClient.from_tenant(tenant)


async def _tenant_out(session: AsyncSession, tenant: EntraTenant) -> EntraTenantOut:
    return EntraTenantOut(
        id=tenant.id,
        name=tenant.name,
        tenant_id=tenant.tenant_id,
        client_id=tenant.client_id or "",
        domain=tenant.domain or "",
        status=tenant.status or "pending",
        enabled=bool(tenant.enabled),
        credentials_configured=credentials_configured(tenant),
        last_error=tenant.last_error,
        last_synced_at=tenant.last_synced_at,
        last_sync=_sync_out(await latest_run(session, tenant.id)),
        created_at=tenant.created_at,
    )


def _primary_domain(org: dict) -> str:
    for item in org.get("verifiedDomains") or []:
        if item.get("isDefault"):
            return str(item.get("name") or "")
    for item in org.get("verifiedDomains") or []:
        if item.get("name"):
            return str(item.get("name"))
    return ""


@router.get("/status", response_model=EntraStatusOut)
async def entra_status(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ)),
):
    tenants = (await session.execute(select(EntraTenant).order_by(EntraTenant.name))).scalars().all()
    payload = [await _tenant_out(session, row) for row in tenants]
    return EntraStatusOut(
        configured=any(row.status == "ready" and row.credentials_configured for row in payload),
        tenant_count=len(tenants),
        last_sync=_sync_out(await latest_run(session)),
        required_permissions=GRAPH_PERMISSIONS,
        tenants=payload,
    )


@router.get("/tenants", response_model=list[EntraTenantOut])
async def list_tenants(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ)),
):
    rows = (await session.execute(select(EntraTenant).order_by(EntraTenant.name))).scalars().all()
    return [await _tenant_out(session, row) for row in rows]


@router.post("/tenants", response_model=EntraTenantOut)
async def create_tenant(
    body: EntraTenantCreate,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant_guid = body.tenant_id.strip()
    name = body.name.strip()
    client_id = body.client_id.strip()
    secret = body.client_secret.strip()
    if not name or not tenant_guid or not client_id or not secret:
        raise HTTPException(status_code=400, detail="Name, tenant ID, client ID and client secret are required")
    existing = (
        await session.execute(select(EntraTenant).where(EntraTenant.tenant_id == tenant_guid))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A connection for this tenant already exists")
    tenant = EntraTenant(
        name=name,
        tenant_id=tenant_guid,
        client_id=client_id,
        domain=body.domain.strip(),
        secrets={"client_secret": secret},
        status="pending",
        enabled=True,
    )
    session.add(tenant)
    await session.flush()
    try:
        org = await GraphClient.from_tenant(tenant).organization()
        tenant.status = "ready"
        tenant.last_error = None
        if not tenant.domain:
            tenant.domain = _primary_domain(org)
        if tenant.name == "Default" or not tenant.name:
            tenant.name = str(org.get("displayName") or tenant.name)
    except GraphError as exc:
        tenant.status = "error"
        tenant.last_error = exc.message
    await session.commit()
    await session.refresh(tenant)
    return await _tenant_out(session, tenant)


@router.get("/tenants/{tenant_id}", response_model=EntraTenantOut)
async def get_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read")),
):
    return await _tenant_out(session, await _get_tenant(session, tenant_id))


@router.patch("/tenants/{tenant_id}", response_model=EntraTenantOut)
async def patch_tenant(
    tenant_id: UUID,
    body: EntraTenantPatch,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, tenant_id)
    if body.name is not None:
        tenant.name = body.name.strip() or tenant.name
    if body.tenant_id is not None:
        tenant.tenant_id = body.tenant_id.strip() or tenant.tenant_id
    if body.client_id is not None:
        tenant.client_id = body.client_id.strip()
    if body.domain is not None:
        tenant.domain = body.domain.strip()
    if body.enabled is not None:
        tenant.enabled = body.enabled
    if body.client_secret is not None and body.client_secret.strip():
        secrets_map = dict(tenant.secrets or {})
        secrets_map["client_secret"] = body.client_secret.strip()
        tenant.secrets = secrets_map
    tenant.status = "ready" if credentials_configured(tenant) else "pending"
    tenant.last_error = None
    await session.commit()
    await session.refresh(tenant)
    return await _tenant_out(session, tenant)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, tenant_id)
    await session.delete(tenant)
    await session.commit()
    return {"ok": True}


@router.post("/tenants/{tenant_id}/test", response_model=EntraTenantOut)
async def test_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, tenant_id)
    try:
        org = await GraphClient.from_tenant(tenant).organization()
        tenant.status = "ready"
        tenant.last_error = None
        if not tenant.domain:
            tenant.domain = _primary_domain(org)
        if org.get("displayName") and tenant.name in {"Default", tenant.tenant_id}:
            tenant.name = str(org.get("displayName"))
    except GraphError as exc:
        tenant.status = "error"
        tenant.last_error = exc.message
        await session.commit()
        raise _graph_http(exc) from exc
    await session.commit()
    await session.refresh(tenant)
    return await _tenant_out(session, tenant)


@router.post("/tenants/{tenant_id}/sync", response_model=DirectorySyncOut)
async def sync_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, tenant_id)
    if not credentials_configured(tenant):
        raise HTTPException(status_code=400, detail="Add a client ID and client secret before syncing.")
    run = await sync_directory(session, tenant)
    if run.status == "error":
        raise HTTPException(status_code=400, detail=run.error or "Directory sync failed")
    return _sync_out(run)


@router.post("/sync", response_model=DirectorySyncOut)
async def run_sync(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.write", "admin.users.write")),
    tenant_id: UUID | None = Query(default=None),
):
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Select a tenant to sync.")
    return await sync_tenant(tenant_id, session, _)


@router.get("/users", response_model=list[EntraUserOut])
async def list_directory_users(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ)),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
):
    stmt = select(User).where(User.source == "entra").order_by(User.display_name)
    if tenant_id:
        stmt = stmt.where(User.entra_tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.display_name.ilike(like),
                User.email.ilike(like),
                User.user_principal_name.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(User.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [_user_out(user) for user in rows]


@router.post("/users", response_model=EntraUserOut)
async def create_directory_user(
    body: EntraUserCreate,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, body.tenant_id)
    try:
        user, password, warnings = await provision_user(
            session,
            tenant,
            actor_from(actor),
            display_name=body.display_name,
            user_principal_name=body.user_principal_name,
            password=body.password,
            job_title=body.job_title,
            department=body.department,
            usage_location=body.usage_location,
            template_id=body.template_id,
        )
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return _user_out(
        user,
        password,
        warnings=warnings,
        app_assignments=await _app_assignments_for(session, user.entra_oid),
    )


@router.get("/users/{user_id}", response_model=EntraUserOut)
async def get_directory_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ)),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_out(user, app_assignments=await _app_assignments_for(session, user.entra_oid))


@router.patch("/users/{user_id}", response_model=EntraUserOut)
async def patch_directory_user(
    user_id: UUID,
    body: EntraUserPatch,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege(*DIRECTORY_OPERATE)),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.source != "entra" or not user.entra_oid or user.entra_oid.startswith("demo-") or user.entra_oid.startswith("pending:"):
        raise HTTPException(status_code=400, detail="This user is not an Entra directory identity")
    profile = any(value is not None for value in (body.display_name, body.job_title, body.department, body.usage_location))
    if not actor.has("admin.entra.write") and (profile or body.status is None):
        raise HTTPException(
            status_code=403,
            detail="Help desk can reset passwords, enable or disable accounts, and edit group membership",
        )
    if not profile and body.status is None:
        return _user_out(user, app_assignments=await _app_assignments_for(session, user.entra_oid))
    try:
        if profile:
            user = await update_profile(
                session,
                user,
                actor_from(actor),
                display_name=body.display_name,
                job_title=body.job_title,
                department=body.department,
                usage_location=body.usage_location,
            )
        if body.status is not None:
            user = await set_account_enabled(session, user, actor_from(actor), body.status == "active")
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return _user_out(user, app_assignments=await _app_assignments_for(session, user.entra_oid))


@router.get("/groups", response_model=list[EntraGroupOut])
async def list_directory_groups(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ, "admin.groups.read")),
    q: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
):
    stmt = select(EntraGroup).order_by(EntraGroup.display_name)
    if tenant_id:
        stmt = stmt.where(EntraGroup.tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(EntraGroup.display_name.ilike(like), EntraGroup.description.ilike(like)))
    rows = (await session.execute(stmt)).scalars().all()
    return [await _group_out(session, group) for group in rows]


@router.post("/groups", response_model=EntraGroupOut)
async def create_directory_group(
    body: EntraGroupCreate,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    tenant = await _get_tenant(session, body.tenant_id)
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    client = _client(tenant)
    try:
        created = await client.create_group(name, body.description)
    except GraphError as exc:
        who = actor_from(actor)
        await record_audit(
            session,
            actor_id=who.id,
            actor_email=who.email,
            actor_name=who.name,
            tenant_id=tenant.id,
            action="group.create",
            target_type="group",
            target_id=name,
            target_label=name,
            status="error",
            error=exc.message,
            graph_request_id=client.last_request_id,
        )
        await session.commit()
        raise _graph_http(exc) from exc
    who = actor_from(actor)
    await record_audit(
        session,
        actor_id=who.id,
        actor_email=who.email,
        actor_name=who.name,
        tenant_id=tenant.id,
        action="group.create",
        target_type="group",
        target_id=str(created.get("id") or name),
        target_label=name,
        after={"description": body.description or ""},
        graph_request_id=client.last_request_id,
    )
    group = await upsert_group_from_graph(session, created, tenant)
    return await _group_out(session, group, with_members=True, with_apps=True)


@router.get("/groups/{group_id}", response_model=EntraGroupOut)
async def get_directory_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege(*DIRECTORY_READ, "admin.groups.read")),
):
    group = await session.get(EntraGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return await _group_out(session, group, with_members=True, with_apps=True)


@router.patch("/groups/{group_id}", response_model=EntraGroupOut)
async def patch_directory_group(
    group_id: UUID,
    body: EntraGroupPatch,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    group = await session.get(EntraGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    payload: dict = {}
    if body.display_name is not None:
        payload["displayName"] = body.display_name.strip()
    if body.description is not None:
        payload["description"] = body.description
    if payload:
        if not group.tenant_id:
            raise HTTPException(status_code=400, detail="This group is not linked to an Entra tenant")
        tenant = await _get_tenant(session, group.tenant_id)
        before = {"display_name": group.display_name, "description": group.description or ""}
        client = _client(tenant)
        try:
            updated = await client.patch_group(group.entra_id, payload)
        except GraphError as exc:
            who = actor_from(actor)
            await record_audit(
                session,
                actor_id=who.id,
                actor_email=who.email,
                actor_name=who.name,
                tenant_id=group.tenant_id,
                action="group.update",
                target_type="group",
                target_id=group.entra_id,
                target_label=group.display_name,
                before=before,
                status="error",
                error=exc.message,
                graph_request_id=client.last_request_id,
            )
            await session.commit()
            raise _graph_http(exc) from exc
        who = actor_from(actor)
        await record_audit(
            session,
            actor_id=who.id,
            actor_email=who.email,
            actor_name=who.name,
            tenant_id=group.tenant_id,
            action="group.update",
            target_type="group",
            target_id=group.entra_id,
            target_label=payload.get("displayName") or group.display_name,
            before=before,
            after={"display_name": payload.get("displayName", group.display_name), "description": payload.get("description", group.description or "")},
            graph_request_id=client.last_request_id,
        )
        group = await upsert_group_from_graph(session, updated, tenant)
    return await _group_out(session, group, with_members=True, with_apps=True)


@router.delete("/groups/{group_id}")
async def delete_directory_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.entra.write")),
):
    group = await session.get(EntraGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if not group.tenant_id:
        raise HTTPException(status_code=400, detail="This group is not linked to an Entra tenant")
    tenant = await _get_tenant(session, group.tenant_id)
    client = _client(tenant)
    who = actor_from(actor)
    try:
        await client.delete_group(group.entra_id)
    except GraphError as exc:
        await record_audit(
            session,
            actor_id=who.id,
            actor_email=who.email,
            actor_name=who.name,
            tenant_id=group.tenant_id,
            action="group.delete",
            target_type="group",
            target_id=group.entra_id,
            target_label=group.display_name,
            status="error",
            error=exc.message,
            graph_request_id=client.last_request_id,
        )
        await session.commit()
        raise _graph_http(exc) from exc
    await record_audit(
        session,
        actor_id=who.id,
        actor_email=who.email,
        actor_name=who.name,
        tenant_id=group.tenant_id,
        action="group.delete",
        target_type="group",
        target_id=group.entra_id,
        target_label=group.display_name,
        before={"display_name": group.display_name, "description": group.description or ""},
        graph_request_id=client.last_request_id,
    )
    await session.delete(group)
    await session.commit()
    return {"ok": True}


@router.post("/groups/{group_id}/members", response_model=EntraGroupOut)
async def add_directory_member(
    group_id: UUID,
    body: EntraMemberIn,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege(*DIRECTORY_OPERATE)),
):
    group = await session.get(EntraGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    user = None
    if body.user_id:
        user = await session.get(User, body.user_id)
    elif body.entra_user_id:
        user = (await session.execute(select(User).where(User.entra_oid == body.entra_user_id))).scalar_one_or_none()
    if user is None or user.source != "entra":
        raise HTTPException(status_code=404, detail="User not found in the directory cache")
    try:
        await add_group_member(session, group, user, actor_from(actor))
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return await _group_out(session, group, with_members=True, with_apps=True)


@router.delete("/groups/{group_id}/members/{entra_user_id}", response_model=EntraGroupOut)
async def remove_directory_member(
    group_id: UUID,
    entra_user_id: str,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege(*DIRECTORY_OPERATE)),
):
    group = await session.get(EntraGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    try:
        await remove_group_member(session, group, entra_user_id, actor_from(actor))
    except DirectoryError as exc:
        raise _directory_http(exc) from exc
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return await _group_out(session, group, with_members=True, with_apps=True)


@router.get("/apps", response_model=list[EntraAppOut])
async def list_directory_apps(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read", "admin.users.read")),
    q: str | None = Query(default=None),
    hide_microsoft: bool = Query(default=True),
    assigned_only: bool = Query(default=False),
    registrations_only: bool = Query(default=False),
    tenant_id: UUID | None = Query(default=None),
):
    stmt = select(EntraApplication).order_by(EntraApplication.display_name)
    if tenant_id:
        stmt = stmt.where(EntraApplication.tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                EntraApplication.display_name.ilike(like),
                EntraApplication.app_id.ilike(like),
                EntraApplication.publisher_name.ilike(like),
                EntraApplication.service_principal_id.ilike(like),
            )
        )
    if registrations_only:
        stmt = stmt.where(EntraApplication.has_app_registration.is_(True))
    rows = (await session.execute(stmt)).scalars().all()
    counts = await _assignment_counts(session)
    payload = [await _app_out(session, app, counts=counts.get(app.id, {})) for app in rows]
    if hide_microsoft:
        payload = [
            app
            for app in payload
            if not app.is_microsoft or app.user_assignment_count or app.group_assignment_count
        ]
    if assigned_only:
        payload = [app for app in payload if app.user_assignment_count or app.group_assignment_count]
    return payload


@router.get("/apps/{app_id}", response_model=EntraAppOut)
async def get_directory_app(
    app_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.entra.read", "admin.users.read")),
):
    app = await session.get(EntraApplication, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return await _app_out(session, app, with_assignments=True)
