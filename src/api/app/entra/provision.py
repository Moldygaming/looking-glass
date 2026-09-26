"""Entra directory writes shared by the API and CSV bulk import."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entra.audit import record_audit
from app.entra.bulk import ACTIONS, BulkRow, validate_usage_location
from app.entra.graph import GraphClient, GraphError
from app.entra.skus import assigned_from_graph
from app.entra.sync import upsert_license_skus, upsert_user_from_graph
from app.models import EntraGroup, EntraLicenseSku, EntraMembership, EntraTenant, EntraUserTemplate, User


class DirectoryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Actor:
    id: UUID | None
    email: str
    name: str


def actor_from(user) -> Actor:
    return Actor(id=user.id, email=user.email or "", name=user.display_name or "")


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "Lg-" + "".join(secrets.choice(alphabet) for _ in range(16))


def _profile_after(before: dict, payload: dict) -> dict:
    after = dict(before)
    if "displayName" in payload:
        after["display_name"] = payload["displayName"]
    if "jobTitle" in payload:
        after["job_title"] = payload["jobTitle"]
    if "department" in payload:
        after["department"] = payload["department"]
    if "usageLocation" in payload:
        after["usage_location"] = payload["usageLocation"]
    return after


def user_snapshot(user: User) -> dict:
    return {
        "display_name": user.display_name,
        "user_principal_name": user.user_principal_name or "",
        "job_title": user.job_title or "",
        "department": user.department or "",
        "status": user.status,
        "usage_location": getattr(user, "usage_location", "") or "",
        "assigned_licenses": assigned_from_graph(getattr(user, "assigned_licenses", None)),
    }


def _location(value: str) -> str:
    try:
        return validate_usage_location(value)
    except ValueError as exc:
        raise DirectoryError(400, str(exc)) from exc


async def _audit_error(session, actor: Actor, tenant_id, action, target_type, target_id, target_label, message, request_id=None):
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=tenant_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id or ""),
        target_label=target_label,
        graph_request_id=request_id,
        status="error",
        error=message,
    )
    await session.commit()


def _already_member(exc: GraphError) -> bool:
    text = exc.message.lower()
    return "already exist" in text or "added object references already exist" in text


async def _find_group(session: AsyncSession, tenant_id: UUID, ref: str) -> EntraGroup:
    cleaned = ref.strip()
    if not cleaned:
        raise DirectoryError(400, "Group name is empty")
    by_id = (
        await session.execute(
            select(EntraGroup).where(EntraGroup.tenant_id == tenant_id, EntraGroup.entra_id == cleaned)
        )
    ).scalars().all()
    if len(by_id) == 1:
        return by_id[0]
    named = (
        await session.execute(
            select(EntraGroup).where(
                EntraGroup.tenant_id == tenant_id,
                func.lower(EntraGroup.display_name) == cleaned.lower(),
            )
        )
    ).scalars().all()
    if len(named) > 1:
        raise DirectoryError(400, f"More than one group is named {cleaned}")
    if not named:
        raise DirectoryError(404, f"Group not found: {cleaned}")
    return named[0]


async def _find_sku(session: AsyncSession, tenant_id: UUID, ref: str) -> EntraLicenseSku:
    cleaned = ref.strip()
    if not cleaned:
        raise DirectoryError(400, "License SKU is empty")
    row = (
        await session.execute(
            select(EntraLicenseSku).where(
                EntraLicenseSku.tenant_id == tenant_id,
                or_(EntraLicenseSku.sku_id == cleaned, func.lower(EntraLicenseSku.sku_part_number) == cleaned.lower()),
            )
        )
    ).scalars().first()
    if row is None:
        raise DirectoryError(404, f"License not found: {cleaned}. Refresh licenses, then try again.")
    return row


async def find_directory_user(session: AsyncSession, tenant_id: UUID, upn: str) -> User | None:
    cleaned = upn.strip()
    if not cleaned:
        return None
    return (
        await session.execute(
            select(User).where(
                User.entra_tenant_id == tenant_id,
                User.source == "entra",
                func.lower(User.user_principal_name) == cleaned.lower(),
            )
        )
    ).scalars().first()


async def add_group_member(session: AsyncSession, group: EntraGroup, user: User, actor: Actor) -> None:
    if not group.tenant_id:
        raise DirectoryError(400, "This group is not linked to an Entra tenant")
    if user.entra_tenant_id and user.entra_tenant_id != group.tenant_id:
        raise DirectoryError(400, "That user belongs to a different tenant")
    tenant = await session.get(EntraTenant, group.tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    label = user.user_principal_name or user.display_name
    client = GraphClient.from_tenant(tenant)
    try:
        await client.add_member(group.entra_id, user.entra_oid)
    except GraphError as exc:
        if not _already_member(exc):
            await _audit_error(
                session, actor, group.tenant_id, "group.member.add", "group", group.entra_id, group.display_name, exc.message, client.last_request_id
            )
            raise
    existing = (
        await session.execute(
            select(EntraMembership).where(
                EntraMembership.group_id == group.id,
                EntraMembership.entra_user_id == user.entra_oid,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(EntraMembership(group_id=group.id, entra_user_id=user.entra_oid, user_id=user.id))
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=group.tenant_id,
        action="group.member.add",
        target_type="group",
        target_id=group.entra_id,
        target_label=group.display_name,
        after={"user": label},
        graph_request_id=client.last_request_id,
    )
    await session.commit()


async def remove_group_member(session: AsyncSession, group: EntraGroup, entra_user_id: str, actor: Actor) -> None:
    if not group.tenant_id:
        raise DirectoryError(400, "This group is not linked to an Entra tenant")
    tenant = await session.get(EntraTenant, group.tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    user = (
        await session.execute(select(User).where(User.entra_oid == entra_user_id))
    ).scalar_one_or_none()
    label = (user.user_principal_name or user.display_name) if user else entra_user_id
    client = GraphClient.from_tenant(tenant)
    try:
        await client.remove_member(group.entra_id, entra_user_id)
    except GraphError as exc:
        await _audit_error(
            session, actor, group.tenant_id, "group.member.remove", "group", group.entra_id, group.display_name, exc.message, client.last_request_id
        )
        raise
    rows = (
        await session.execute(
            select(EntraMembership).where(
                EntraMembership.group_id == group.id,
                EntraMembership.entra_user_id == entra_user_id,
            )
        )
    ).scalars().all()
    for row in rows:
        await session.delete(row)
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=group.tenant_id,
        action="group.member.remove",
        target_type="group",
        target_id=group.entra_id,
        target_label=group.display_name,
        before={"user": label},
        graph_request_id=client.last_request_id,
    )
    await session.commit()


async def reset_password(
    session: AsyncSession,
    user: User,
    actor: Actor,
    password: str | None = None,
    *,
    force_change: bool = True,
) -> str:
    if not user.entra_tenant_id:
        raise DirectoryError(400, "This user is not linked to an Entra tenant")
    tenant = await session.get(EntraTenant, user.entra_tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    chosen = (password or "").strip() or generate_password()
    if len(chosen) < 8:
        raise DirectoryError(400, "Password must be at least 8 characters")
    client = GraphClient.from_tenant(tenant)
    label = user.user_principal_name or user.display_name
    try:
        await client.reset_password(user.entra_oid, chosen, force_change=force_change)
    except GraphError as exc:
        await _audit_error(
            session, actor, user.entra_tenant_id, "user.password_reset", "user", user.entra_oid, label, exc.message, client.last_request_id
        )
        raise
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=user.entra_tenant_id,
        action="user.password_reset",
        target_type="user",
        target_id=user.entra_oid,
        target_label=label,
        after={"generated": not bool((password or "").strip()), "force_change": force_change},
        graph_request_id=client.last_request_id,
    )
    await session.commit()
    return chosen


async def set_account_enabled(session: AsyncSession, user: User, actor: Actor, enabled: bool) -> User:
    if not user.entra_tenant_id or not user.entra_oid:
        raise DirectoryError(400, "This user is not linked to an Entra tenant")
    tenant = await session.get(EntraTenant, user.entra_tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    before = user_snapshot(user)
    client = GraphClient.from_tenant(tenant)
    action = "user.enable" if enabled else "user.disable"
    try:
        updated = await client.patch_user(user.entra_oid, {"accountEnabled": enabled})
    except GraphError as exc:
        await _audit_error(
            session, actor, user.entra_tenant_id, action, "user", user.entra_oid, user.display_name, exc.message, client.last_request_id
        )
        raise
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=user.entra_tenant_id,
        action=action,
        target_type="user",
        target_id=user.entra_oid,
        target_label=user.user_principal_name or user.display_name,
        before=before,
        after={**before, "status": "active" if enabled else "disabled"},
        graph_request_id=client.last_request_id,
    )
    return await upsert_user_from_graph(session, updated, tenant)


async def change_licenses(
    session: AsyncSession,
    user: User,
    actor: Actor,
    add_sku_ids: list[str],
    remove_sku_ids: list[str],
    usage_location: str | None = None,
) -> User:
    if not user.entra_tenant_id or not user.entra_oid:
        raise DirectoryError(400, "This user is not linked to an Entra tenant")
    tenant = await session.get(EntraTenant, user.entra_tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    current = {item["sku_id"] for item in assigned_from_graph(user.assigned_licenses)}
    adds = [sku for sku in dict.fromkeys(add_sku_ids) if sku and sku not in current]
    removes = [sku for sku in dict.fromkeys(remove_sku_ids) if sku]
    location = _location(usage_location or "") if usage_location is not None else None
    if location and location == (user.usage_location or ""):
        location = None
    if not adds and not removes and not location:
        return user
    if adds and not (location or user.usage_location):
        raise DirectoryError(400, "Set a usage location before assigning a license")
    before = user_snapshot(user)
    client = GraphClient.from_tenant(tenant)
    label = user.user_principal_name or user.display_name
    try:
        if location:
            await client.patch_user(user.entra_oid, {"usageLocation": location})
        assigned = None
        if adds or removes:
            assigned = await client.assign_license(user.entra_oid, adds, removes)
        refreshed = await client.get_user(user.entra_oid)
        if isinstance(assigned, dict) and "assignedLicenses" in assigned and "assignedLicenses" not in refreshed:
            refreshed = {**refreshed, "assignedLicenses": assigned["assignedLicenses"]}
        skus = await client.list_subscribed_skus()
    except GraphError as exc:
        await _audit_error(
            session, actor, user.entra_tenant_id, "license.update", "user", user.entra_oid, label, exc.message, client.last_request_id
        )
        raise
    await upsert_license_skus(session, skus, tenant)
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=user.entra_tenant_id,
        action="license.update",
        target_type="user",
        target_id=user.entra_oid,
        target_label=label,
        before=before,
        after={"add_sku_ids": adds, "remove_sku_ids": removes, "usage_location": location or user.usage_location or ""},
        graph_request_id=client.last_request_id,
    )
    return await upsert_user_from_graph(session, refreshed, tenant)


async def create_directory_user(
    session: AsyncSession,
    tenant: EntraTenant,
    actor: Actor,
    *,
    display_name: str,
    user_principal_name: str,
    password: str | None = None,
    job_title: str = "",
    department: str = "",
    usage_location: str = "",
    template_id: UUID | None = None,
    template_name: str = "",
) -> tuple[User, str, list[str]]:
    name = display_name.strip()
    upn = user_principal_name.strip()
    if not name or not upn or "@" not in upn:
        raise DirectoryError(400, "Display name and a user principal name (user@domain) are required")
    template = await _load_template(session, tenant.id, template_id, template_name)
    title = job_title.strip() or (template.job_title if template else "")
    dept = department.strip() or (template.department if template else "")
    location = _location(usage_location or (template.usage_location if template else ""))
    chosen = (password or "").strip() or generate_password()
    if len(chosen) < 8:
        raise DirectoryError(400, "Password must be at least 8 characters")
    client = GraphClient.from_tenant(tenant)
    try:
        created = await client.create_user(name, upn, chosen, title, dept, location)
    except GraphError as exc:
        await _audit_error(session, actor, tenant.id, "user.create", "user", upn, name, exc.message, client.last_request_id)
        raise
    request_id = client.last_request_id
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=tenant.id,
        action="user.create",
        target_type="user",
        target_id=str(created.get("id") or upn),
        target_label=upn,
        after={
            "display_name": name,
            "job_title": title,
            "department": dept,
            "usage_location": location,
            "template": template.name if template else "",
        },
        graph_request_id=request_id,
    )
    user = await upsert_user_from_graph(session, created, tenant)
    warnings: list[str] = []
    if template:
        warnings.extend(await _apply_template_access(session, tenant, user, template, actor))
        user = await session.get(User, user.id) or user
    return user, chosen, warnings


async def _load_template(session, tenant_id: UUID, template_id: UUID | None, template_name: str) -> EntraUserTemplate | None:
    if template_id is not None:
        template = await session.get(EntraUserTemplate, template_id)
        if template is None or template.tenant_id != tenant_id:
            raise DirectoryError(404, "Template not found")
        return template
    cleaned = template_name.strip()
    if not cleaned:
        return None
    rows = (
        await session.execute(
            select(EntraUserTemplate).where(
                EntraUserTemplate.tenant_id == tenant_id,
                func.lower(EntraUserTemplate.name) == cleaned.lower(),
            )
        )
    ).scalars().all()
    if len(rows) > 1:
        raise DirectoryError(400, f"More than one template is named {cleaned}")
    if not rows:
        raise DirectoryError(404, f"Template not found: {cleaned}")
    return rows[0]


async def _apply_template_access(session, tenant: EntraTenant, user: User, template: EntraUserTemplate, actor: Actor) -> list[str]:
    warnings: list[str] = []
    for ref in template.group_ids or []:
        try:
            group = await _find_group(session, tenant.id, ref)
            await add_group_member(session, group, user, actor)
        except (DirectoryError, GraphError) as exc:
            message = exc.message if isinstance(exc, (DirectoryError, GraphError)) else str(exc)
            warnings.append(f"Group {ref}: {message}")
    if template.license_sku_ids:
        try:
            await change_licenses(session, user, actor, list(template.license_sku_ids), [], user.usage_location or template.usage_location or None)
        except (DirectoryError, GraphError) as exc:
            message = exc.message if isinstance(exc, (DirectoryError, GraphError)) else str(exc)
            warnings.append(f"Licenses: {message}")
    return warnings


async def update_profile(
    session: AsyncSession,
    user: User,
    actor: Actor,
    *,
    display_name: str | None = None,
    job_title: str | None = None,
    department: str | None = None,
    usage_location: str | None = None,
) -> User:
    if not user.entra_tenant_id or not user.entra_oid:
        raise DirectoryError(400, "This user is not an Entra directory identity")
    tenant = await session.get(EntraTenant, user.entra_tenant_id)
    if tenant is None:
        raise DirectoryError(404, "Tenant not found")
    payload: dict = {}
    if display_name is not None:
        payload["displayName"] = display_name.strip()
    if job_title is not None:
        payload["jobTitle"] = job_title
    if department is not None:
        payload["department"] = department
    if usage_location is not None:
        payload["usageLocation"] = _location(usage_location)
    if not payload:
        return user
    before = user_snapshot(user)
    client = GraphClient.from_tenant(tenant)
    try:
        updated = await client.patch_user(user.entra_oid, payload)
    except GraphError as exc:
        await _audit_error(
            session, actor, user.entra_tenant_id, "user.update", "user", user.entra_oid, user.display_name, exc.message, client.last_request_id
        )
        raise
    await record_audit(
        session,
        actor_id=actor.id,
        actor_email=actor.email,
        actor_name=actor.name,
        tenant_id=user.entra_tenant_id,
        action="user.update",
        target_type="user",
        target_id=user.entra_oid,
        target_label=user.user_principal_name or user.display_name,
        before=before,
        after=_profile_after(before, payload),
        graph_request_id=client.last_request_id,
    )
    return await upsert_user_from_graph(session, updated, tenant)


async def apply_bulk_row(session: AsyncSession, tenant: EntraTenant, actor: Actor, row: BulkRow) -> str:
    action = row.action.strip().lower()
    if action not in ACTIONS:
        raise DirectoryError(400, f"Unknown action '{row.action or ''}'")
    upn = row.user_principal_name.strip()
    if "@" not in upn:
        raise DirectoryError(400, "user_principal_name must look like user@domain")
    if action == "create":
        user, password, warnings = await create_directory_user(
            session,
            tenant,
            actor,
            display_name=row.display_name,
            user_principal_name=upn,
            password=row.password or None,
            job_title=row.job_title,
            department=row.department,
            usage_location=row.usage_location,
            template_name=row.template,
        )
        detail = f"Created {user.user_principal_name or upn}"
        if not row.password:
            detail += f". Temporary password: {password}"
        if warnings:
            detail += ". " + " ".join(warnings)
        return detail

    user = await find_directory_user(session, tenant.id, upn)
    if user is None:
        raise DirectoryError(404, "User not found in this tenant")
    if action == "update":
        if not any((row.display_name, row.job_title, row.department, row.usage_location)):
            raise DirectoryError(400, "Nothing to update")
        await update_profile(
            session,
            user,
            actor,
            display_name=row.display_name or None,
            job_title=row.job_title or None,
            department=row.department or None,
            usage_location=row.usage_location or None,
        )
        return f"Updated {upn}"
    if action == "enable":
        await set_account_enabled(session, user, actor, True)
        return f"Enabled {upn}"
    if action == "disable":
        await set_account_enabled(session, user, actor, False)
        return f"Disabled {upn}"
    if action == "reset_password":
        password = await reset_password(session, user, actor, row.password or None, force_change=True)
        if row.password:
            return f"Reset password for {upn}"
        return f"Reset password for {upn}. Temporary password: {password}"
    if action in {"add_groups", "remove_groups"}:
        if not row.groups:
            raise DirectoryError(400, "groups is required")
        for ref in row.groups:
            group = await _find_group(session, tenant.id, ref)
            if action == "add_groups":
                await add_group_member(session, group, user, actor)
            else:
                await remove_group_member(session, group, user.entra_oid, actor)
        verb = "Added" if action == "add_groups" else "Removed"
        return f"{verb} groups for {upn}"
    if action in {"assign_licenses", "remove_licenses"}:
        if not row.licenses:
            raise DirectoryError(400, "licenses is required")
        sku_ids = [(await _find_sku(session, tenant.id, ref)).sku_id for ref in row.licenses]
        if action == "assign_licenses":
            await change_licenses(session, user, actor, sku_ids, [], row.usage_location or None)
            return f"Assigned licenses to {upn}"
        await change_licenses(session, user, actor, [], sku_ids, None)
        return f"Removed licenses from {upn}"
    raise DirectoryError(400, f"Unknown action '{action}'")
