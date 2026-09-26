"""Pull Entra users, groups, enterprise apps and memberships into Looking Glass."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.entra.graph import GraphClient, GraphError
from app.entra.skus import assigned_from_graph
from app.models import (
    DirectorySyncRun,
    EntraAppAssignment,
    EntraApplication,
    EntraGroup,
    EntraLicenseSku,
    EntraMembership,
    EntraTenant,
    User,
)

log = logging.getLogger("looking-glass.entra")

DEFAULT_APP_ROLE_ID = "00000000-0000-0000-0000-000000000000"
MICROSOFT_TENANT_IDS = {
    "f8cdef31-a31e-4b4a-93e4-5f571e91255a",  # Microsoft Services (first-party apps)
    "72f988bf-86f1-41af-91ab-2d7cd011db47",  # Microsoft
}
ASSIGNMENT_CONCURRENCY = 8


def credentials_configured(tenant: EntraTenant) -> bool:
    secret = ""
    if isinstance(tenant.secrets, dict):
        secret = str(tenant.secrets.get("client_secret") or "")
    return bool(tenant.tenant_id and tenant.client_id and secret)


async def ensure_env_tenant(session: AsyncSession) -> EntraTenant | None:
    if not settings.entra_graph_configured:
        return None
    existing = (
        await session.execute(select(EntraTenant).where(EntraTenant.tenant_id == settings.entra_tenant_id))
    ).scalar_one_or_none()
    if existing:
        return existing
    tenant = EntraTenant(
        name="Default",
        tenant_id=settings.entra_tenant_id,
        client_id=settings.entra_client_id,
        secrets={"client_secret": settings.entra_client_secret},
        status="ready",
        enabled=True,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def sync_directory(session: AsyncSession, tenant: EntraTenant) -> DirectorySyncRun:
    tenant_pk = tenant.id
    run = DirectorySyncRun(status="running", started_at=datetime.now(UTC), tenant_id=tenant_pk)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    try:
        client = GraphClient.from_tenant(tenant)
        sku_parts: dict[str, str] = {}
        try:
            sku_parts = await upsert_license_skus(session, await client.list_subscribed_skus(), tenant)
        except GraphError:
            sku_parts = {}
        users = await client.list_users()
        groups = await client.list_groups()
        user_count = await _upsert_users(session, users, tenant, sku_parts)
        group_count = await _upsert_groups(session, groups, tenant)
        member_count = 0
        local_groups = (
            await session.execute(select(EntraGroup).where(EntraGroup.tenant_id == tenant.id))
        ).scalars().all()
        oid_to_user = {
            u.entra_oid: u
            for u in (await session.execute(select(User))).scalars().all()
        }
        for group in local_groups:
            members = await client.list_members(group.entra_id)
            member_count += await _replace_memberships(session, group, members, oid_to_user)
        sps = await client.list_service_principals()
        registrations = await client.list_app_registrations()
        app_count = await _upsert_applications(session, sps, registrations, tenant)
        local_apps = (
            await session.execute(select(EntraApplication).where(EntraApplication.tenant_id == tenant.id))
        ).scalars().all()
        oid_to_group = {g.entra_id: g for g in local_groups}
        assignment_rows = await _fetch_assignments(client, [app.service_principal_id for app in local_apps])
        assignment_count = 0
        for app in local_apps:
            assignment_count += await _replace_assignments(
                session,
                app,
                assignment_rows.get(app.service_principal_id) or [],
                oid_to_user,
                oid_to_group,
            )
        now = datetime.now(UTC)
        run.users_upserted = user_count
        run.groups_upserted = group_count
        run.memberships_upserted = member_count
        run.apps_upserted = app_count
        run.assignments_upserted = assignment_count
        run.status = "ok"
        run.finished_at = now
        run.error = None
        tenant.status = "ready"
        tenant.last_error = None
        tenant.last_synced_at = now
        await session.commit()
        await session.refresh(run)
        return run
    except Exception as exc:  # noqa: BLE001 — persist sync failure
        message = str(exc)[:4000]
        await session.rollback()
        failed = await session.get(DirectorySyncRun, run_id)
        if failed is None:
            failed = DirectorySyncRun(id=run_id, status="error", started_at=datetime.now(UTC), tenant_id=tenant_pk)
            session.add(failed)
        failed.status = "error"
        failed.finished_at = datetime.now(UTC)
        failed.error = message
        row = await session.get(EntraTenant, tenant_pk)
        if row:
            row.status = "error"
            row.last_error = message
        await session.commit()
        await session.refresh(failed)
        return failed


async def sync_all_tenants(session: AsyncSession) -> list[DirectorySyncRun]:
    tenants = (
        await session.execute(select(EntraTenant).where(EntraTenant.enabled.is_(True)).order_by(EntraTenant.name))
    ).scalars().all()
    runs: list[DirectorySyncRun] = []
    for tenant in tenants:
        if not credentials_configured(tenant):
            continue
        runs.append(await sync_directory(session, tenant))
    return runs


async def upsert_license_skus(session: AsyncSession, rows: list[dict], tenant: EntraTenant) -> dict[str, str]:
    """Store subscribed SKUs. Returns sku id to part number. Does not commit."""
    now = datetime.now(UTC)
    parts: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        sku_id = str(row.get("skuId") or "")
        if not sku_id:
            continue
        seen.add(sku_id)
        part = str(row.get("skuPartNumber") or "")
        parts[sku_id] = part
        prepaid = row.get("prepaidUnits") if isinstance(row.get("prepaidUnits"), dict) else {}
        plans = []
        for plan in row.get("servicePlans") or []:
            if not isinstance(plan, dict):
                continue
            name = str(plan.get("servicePlanName") or "")
            if name:
                plans.append({"name": name, "status": str(plan.get("provisioningStatus") or "")})
        existing = (
            await session.execute(
                select(EntraLicenseSku).where(EntraLicenseSku.tenant_id == tenant.id, EntraLicenseSku.sku_id == sku_id)
            )
        ).scalar_one_or_none()
        values = dict(
            sku_part_number=part,
            consumed_units=int(row.get("consumedUnits") or 0),
            enabled_units=int(prepaid.get("enabled") or 0),
            suspended_units=int(prepaid.get("suspended") or 0),
            warning_units=int(prepaid.get("warning") or 0),
            capability_status=str(row.get("capabilityStatus") or ""),
            service_plans=plans,
            last_synced_at=now,
        )
        if existing is None:
            session.add(EntraLicenseSku(tenant_id=tenant.id, sku_id=sku_id, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
    if seen:
        stale = (
            await session.execute(
                select(EntraLicenseSku).where(
                    EntraLicenseSku.tenant_id == tenant.id,
                    EntraLicenseSku.sku_id.notin_(seen),
                )
            )
        ).scalars().all()
        for row in stale:
            await session.delete(row)
    await session.flush()
    return parts


async def _upsert_users(
    session: AsyncSession,
    rows: list[dict],
    tenant: EntraTenant,
    sku_parts: dict[str, str] | None = None,
) -> int:
    now = datetime.now(UTC)
    count = 0
    sku_parts = sku_parts or {}
    for row in rows:
        entra_id = str(row.get("id") or "")
        if not entra_id:
            continue
        upn = str(row.get("userPrincipalName") or "")
        email = str(row.get("mail") or upn or f"{entra_id}@unknown")
        enabled = bool(row.get("accountEnabled", True))
        licenses = assigned_from_graph(row.get("assignedLicenses"), sku_parts) if "assignedLicenses" in row else None
        location = str(row.get("usageLocation") or "") if "usageLocation" in row else None
        user = (await session.execute(select(User).where(User.entra_oid == entra_id))).scalar_one_or_none()
        if user is None and email:
            user = (
                await session.execute(
                    select(User).where(
                        User.email.ilike(email),
                        or_(User.entra_tenant_id == tenant.id, User.entra_tenant_id.is_(None)),
                    )
                )
            ).scalar_one_or_none()
        if user is None:
            user = User(
                entra_oid=entra_id,
                email=email.lower(),
                display_name=str(row.get("displayName") or email),
                roles=["analyst"],
                status="active" if enabled else "disabled",
                user_principal_name=upn,
                job_title=str(row.get("jobTitle") or ""),
                department=str(row.get("department") or ""),
                usage_location=location or "",
                assigned_licenses=licenses or [],
                source="entra",
                entra_tenant_id=tenant.id,
                last_synced_at=now,
            )
            session.add(user)
        else:
            user.entra_oid = entra_id
            user.email = email.lower() or user.email
            user.display_name = str(row.get("displayName") or user.display_name)
            user.user_principal_name = upn
            user.job_title = str(row.get("jobTitle") or "")
            user.department = str(row.get("department") or "")
            if location is not None:
                user.usage_location = location
            if licenses is not None:
                user.assigned_licenses = licenses
            user.source = "entra"
            user.entra_tenant_id = tenant.id
            user.status = "active" if enabled else "disabled"
            user.last_synced_at = now
        count += 1
    await session.flush()
    return count


async def _upsert_groups(session: AsyncSession, rows: list[dict], tenant: EntraTenant) -> int:
    now = datetime.now(UTC)
    count = 0
    for row in rows:
        entra_id = str(row.get("id") or "")
        if not entra_id:
            continue
        group = (
            await session.execute(
                select(EntraGroup).where(EntraGroup.tenant_id == tenant.id, EntraGroup.entra_id == entra_id)
            )
        ).scalar_one_or_none()
        if group is None:
            group = EntraGroup(
                tenant_id=tenant.id,
                entra_id=entra_id,
                display_name=str(row.get("displayName") or entra_id),
            )
            session.add(group)
        group.tenant_id = tenant.id
        group.display_name = str(row.get("displayName") or group.display_name)
        group.description = str(row.get("description") or "")
        group.mail = str(row.get("mail") or "")
        group.mail_nickname = str(row.get("mailNickname") or "")
        group.security_enabled = bool(row.get("securityEnabled", True))
        group.mail_enabled = bool(row.get("mailEnabled", False))
        group.last_synced_at = now
        count += 1
    await session.flush()
    return count


async def _replace_memberships(
    session: AsyncSession,
    group: EntraGroup,
    members: list[dict],
    oid_to_user: dict[str, User],
) -> int:
    existing = (
        await session.execute(select(EntraMembership).where(EntraMembership.group_id == group.id))
    ).scalars().all()
    have = {row.entra_user_id: row for row in existing}
    seen: set[str] = set()
    count = 0
    for member in members:
        entra_user_id = str(member.get("id") or "")
        if not entra_user_id:
            continue
        seen.add(entra_user_id)
        user = oid_to_user.get(entra_user_id)
        if entra_user_id in have:
            have[entra_user_id].user_id = user.id if user else have[entra_user_id].user_id
        else:
            session.add(
                EntraMembership(
                    group_id=group.id,
                    entra_user_id=entra_user_id,
                    user_id=user.id if user else None,
                )
            )
            count += 1
    for entra_user_id, row in have.items():
        if entra_user_id not in seen:
            await session.delete(row)
    await session.flush()
    return count


def _is_microsoft(row: dict[str, Any]) -> bool:
    owner = str(row.get("appOwnerOrganizationId") or "").lower()
    if owner in MICROSOFT_TENANT_IDS:
        return True
    publisher = str(row.get("publisherName") or "").strip().lower()
    return publisher in {"microsoft", "microsoft services", "microsoft corporation"}


def _app_roles(row: dict[str, Any]) -> list[dict[str, Any]]:
    roles = []
    for role in row.get("appRoles") or []:
        roles.append(
            {
                "id": str(role.get("id") or ""),
                "displayName": str(role.get("displayName") or ""),
                "value": str(role.get("value") or ""),
                "description": str(role.get("description") or ""),
                "isEnabled": bool(role.get("isEnabled", True)),
                "allowedMemberTypes": [str(item) for item in (role.get("allowedMemberTypes") or [])],
            }
        )
    return roles


def _role_name(roles: list[dict[str, Any]], role_id: str) -> str:
    if not role_id or role_id == DEFAULT_APP_ROLE_ID:
        return "Default access"
    for role in roles:
        if str(role.get("id") or "") == role_id:
            return str(role.get("displayName") or role.get("value") or role_id)
    return role_id


async def _upsert_applications(
    session: AsyncSession,
    principals: list[dict[str, Any]],
    registrations: list[dict[str, Any]],
    tenant: EntraTenant,
) -> int:
    now = datetime.now(UTC)
    by_app_id = {str(row.get("appId") or ""): row for row in registrations if row.get("appId")}
    seen: set[str] = set()
    count = 0
    for row in principals:
        sp_id = str(row.get("id") or "")
        app_id = str(row.get("appId") or "")
        if not sp_id:
            continue
        seen.add(sp_id)
        tags = [str(tag) for tag in (row.get("tags") or [])]
        registration = by_app_id.get(app_id)
        app = (
            await session.execute(
                select(EntraApplication).where(
                    EntraApplication.tenant_id == tenant.id,
                    EntraApplication.service_principal_id == sp_id,
                )
            )
        ).scalar_one_or_none()
        if app is None:
            app = EntraApplication(
                tenant_id=tenant.id,
                service_principal_id=sp_id,
                app_id=app_id or sp_id,
                display_name=str(row.get("displayName") or sp_id),
            )
            session.add(app)
        app.tenant_id = tenant.id
        app.app_id = app_id or app.app_id
        app.application_object_id = str((registration or {}).get("id") or "")
        app.display_name = str(row.get("displayName") or app.display_name)
        app.description = str(row.get("notes") or (registration or {}).get("description") or (registration or {}).get("notes") or "")
        app.publisher_name = str(row.get("publisherName") or (registration or {}).get("publisherDomain") or "")
        app.service_principal_type = str(row.get("servicePrincipalType") or "Application")
        app.account_enabled = bool(row.get("accountEnabled", True))
        app.assignment_required = bool(row.get("appRoleAssignmentRequired", False))
        app.sign_in_audience = str(row.get("signInAudience") or (registration or {}).get("signInAudience") or "")
        app.homepage = str(row.get("homepage") or "")[:512]
        app.tags = tags
        app.is_microsoft = _is_microsoft(row)
        app.hidden = "HideApp" in tags
        app.has_app_registration = registration is not None
        app.app_roles = _app_roles(row)
        app.last_synced_at = now
        count += 1
    stale = (
        await session.execute(select(EntraApplication).where(EntraApplication.tenant_id == tenant.id))
    ).scalars().all()
    for app in stale:
        if app.service_principal_id not in seen:
            await session.delete(app)
    await session.flush()
    return count


async def _fetch_assignments(client: GraphClient, sp_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    sem = asyncio.Semaphore(ASSIGNMENT_CONCURRENCY)
    results: dict[str, list[dict[str, Any]]] = {}

    async def one(sp_id: str) -> None:
        async with sem:
            try:
                results[sp_id] = await client.list_app_role_assigned_to(sp_id)
            except GraphError as exc:
                log.warning("app assignments %s failed: %s", sp_id, exc)
                results[sp_id] = []

    if sp_ids:
        await asyncio.gather(*(one(sp_id) for sp_id in sp_ids))
    return results


async def _replace_assignments(
    session: AsyncSession,
    app: EntraApplication,
    rows: list[dict[str, Any]],
    oid_to_user: dict[str, User],
    oid_to_group: dict[str, EntraGroup],
) -> int:
    existing = (
        await session.execute(select(EntraAppAssignment).where(EntraAppAssignment.application_id == app.id))
    ).scalars().all()
    for row in existing:
        await session.delete(row)
    await session.flush()
    roles = list(app.app_roles or [])
    seen: set[tuple[str, str, str]] = set()
    count = 0
    for row in rows:
        assignment_id = str(row.get("id") or "")
        principal_id = str(row.get("principalId") or "")
        if not assignment_id or not principal_id:
            continue
        principal_type = str(row.get("principalType") or "")
        app_role_id = str(row.get("appRoleId") or DEFAULT_APP_ROLE_ID)
        key = (app.service_principal_id, principal_id, app_role_id)
        if key in seen:
            continue
        seen.add(key)
        user = oid_to_user.get(principal_id) if principal_type == "User" else None
        group = oid_to_group.get(principal_id) if principal_type == "Group" else None
        session.add(
            EntraAppAssignment(
                application_id=app.id,
                assignment_id=assignment_id,
                service_principal_id=app.service_principal_id,
                app_role_id=app_role_id,
                app_role_name=_role_name(roles, app_role_id),
                principal_id=principal_id,
                principal_type=principal_type or "User",
                principal_display_name=str(row.get("principalDisplayName") or ""),
                user_id=user.id if user else None,
                group_id=group.id if group else None,
            )
        )
        count += 1
    await session.flush()
    return count


async def latest_run(session: AsyncSession, tenant_id=None) -> DirectorySyncRun | None:
    stmt = select(DirectorySyncRun).order_by(DirectorySyncRun.started_at.desc()).limit(1)
    if tenant_id is not None:
        stmt = stmt.where(DirectorySyncRun.tenant_id == tenant_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_user_from_graph(session: AsyncSession, payload: dict, tenant: EntraTenant) -> User:
    sku_parts = {
        row.sku_id: row.sku_part_number or ""
        for row in (
            await session.execute(select(EntraLicenseSku).where(EntraLicenseSku.tenant_id == tenant.id))
        ).scalars().all()
    }
    await _upsert_users(session, [payload], tenant, sku_parts)
    user = (
        await session.execute(select(User).where(User.entra_oid == str(payload.get("id"))))
    ).scalar_one()
    await session.commit()
    await session.refresh(user)
    return user


async def upsert_group_from_graph(session: AsyncSession, payload: dict, tenant: EntraTenant) -> EntraGroup:
    await _upsert_groups(session, [payload], tenant)
    group = (
        await session.execute(
            select(EntraGroup)
            .options(selectinload(EntraGroup.members))
            .where(EntraGroup.tenant_id == tenant.id, EntraGroup.entra_id == str(payload.get("id")))
        )
    ).scalar_one()
    await session.commit()
    await session.refresh(group)
    return group
