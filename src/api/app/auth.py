from datetime import UTC, datetime
from uuid import UUID
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_session
from app.models import (
    AccessGroup,
    AccessGroupMember,
    AccessGroupScope,
    AccessRole,
    GroupRole,
    RolePrivilege,
    User,
    UserRole,
)
from app.privileges import PLATFORM_ADMIN_KEY, PLATFORM_ADMIN_ROLE_NAME
from app.schemas import CurrentUser, GroupRef, RoleRef, ScopeOut


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
    x_user_oid: str | None = Header(default=None, alias="X-User-Oid"),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    x_user_name: str | None = Header(default=None, alias="X-User-Name"),
    x_user_roles: str | None = Header(default=None, alias="X-User-Roles"),
    x_user_groups: str | None = Header(default=None, alias="X-User-Groups"),
) -> CurrentUser:
    if not x_internal_key or x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid internal key")
    if not x_user_oid:
        raise HTTPException(status_code=401, detail="Missing user identity")

    header_roles = [r.strip() for r in (x_user_roles or "").split(",") if r.strip()]
    header_groups = [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]
    header_admin = "platform_admin" in header_roles or settings.entra_admin_role in header_roles

    user = (
        await session.execute(select(User).where(User.entra_oid == x_user_oid))
    ).scalar_one_or_none()
    if user is None and x_user_email:
        user = (
            await session.execute(select(User).where(func.lower(User.email) == x_user_email.lower()))
        ).scalar_one_or_none()
        if user:
            user.entra_oid = x_user_oid

    if user is None:
        user = User(
            entra_oid=x_user_oid,
            email=x_user_email or f"{x_user_oid}@unknown",
            display_name=x_user_name or x_user_email or x_user_oid,
            roles=["platform_admin"] if header_admin else ["analyst"],
            entra_group_ids=header_groups,
            status="active",
            last_login_at=datetime.now(UTC),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        if (user.status or "active") == "disabled":
            raise HTTPException(status_code=403, detail="This account has been disabled")
        user.email = x_user_email or user.email
        user.display_name = x_user_name or user.display_name
        if header_admin and "platform_admin" not in (user.roles or []):
            user.roles = list({*(user.roles or []), "platform_admin"})
        user.entra_group_ids = header_groups or user.entra_group_ids
        user.last_login_at = datetime.now(UTC)
        await session.commit()

    if header_admin:
        await _ensure_in_platform_admins(session, user)

    access = await load_user_access(session, user)
    is_admin = PLATFORM_ADMIN_KEY in access.privileges or "platform_admin" in (user.roles or [])
    return CurrentUser(
        id=user.id,
        entra_oid=user.entra_oid,
        email=user.email,
        display_name=user.display_name,
        roles=user.roles or [],
        entra_group_ids=user.entra_group_ids or [],
        status=user.status or "active",
        is_admin=is_admin,
        group_ids=access.group_ids,
        groups=access.groups,
        privileges=sorted(access.privileges),
        direct_privileges=sorted(access.direct_privileges),
        access_roles=access.access_roles,
        scopes=access.scopes,
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_privilege(*keys: str) -> Callable:
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.has(*keys):
            return user
        raise HTTPException(
            status_code=403,
            detail=f"Missing privilege: {', '.join(keys)}",
        )

    return _check


def require_admin_area(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.is_admin or any(p.startswith("admin.") for p in user.privileges):
        return user
    raise HTTPException(status_code=403, detail="Admin access required")


class UserAccess:
    def __init__(
        self,
        group_ids: list[UUID],
        groups: list[GroupRef],
        scopes: list[ScopeOut],
        privileges: set[str],
        direct_privileges: set[str],
        group_privilege_map: dict[UUID, set[str]],
        access_roles: list[RoleRef],
        group_role_map: dict[UUID, list[RoleRef]],
        direct_roles: list[RoleRef],
        role_privilege_map: dict[UUID, set[str]],
    ):
        self.group_ids = group_ids
        self.groups = groups
        self.scopes = scopes
        self.privileges = privileges
        self.direct_privileges = direct_privileges
        self.group_privilege_map = group_privilege_map
        self.access_roles = access_roles
        self.group_role_map = group_role_map
        self.direct_roles = direct_roles
        self.role_privilege_map = role_privilege_map


def _role_keys(role: AccessRole) -> set[str]:
    return {row.privilege_key for row in role.privilege_grants}


def _role_ref(role: AccessRole) -> RoleRef:
    return RoleRef(id=role.id, name=role.name, is_system=bool(role.is_system))


async def load_user_access(session: AsyncSession, user: User) -> UserAccess:
    conditions = []
    if user.id:
        conditions.append(AccessGroupMember.user_id == user.id)
    if user.entra_oid:
        conditions.append(AccessGroupMember.entra_oid == user.entra_oid)
    if user.email:
        conditions.append(func.lower(AccessGroupMember.email) == user.email.lower())
    if user.entra_group_ids:
        conditions.append(AccessGroupMember.entra_group_id.in_(user.entra_group_ids))

    group_ids: list[UUID] = []
    if conditions:
        member_rows = await session.execute(
            select(AccessGroupMember.group_id).where(or_(*conditions)).distinct()
        )
        group_ids = [row[0] for row in member_rows.all()]

    groups: list[GroupRef] = []
    group_privilege_map: dict[UUID, set[str]] = {gid: set() for gid in group_ids}
    group_role_map: dict[UUID, list[RoleRef]] = {gid: [] for gid in group_ids}
    privileges: set[str] = set()
    scopes: list[ScopeOut] = []
    role_privilege_map: dict[UUID, set[str]] = {}
    seen_roles: dict[UUID, RoleRef] = {}

    if group_ids:
        group_rows = (
            await session.execute(
                select(AccessGroup)
                .options(
                    selectinload(AccessGroup.role_links)
                    .selectinload(GroupRole.role)
                    .selectinload(AccessRole.privilege_grants),
                    selectinload(AccessGroup.scopes),
                )
                .where(AccessGroup.id.in_(group_ids))
            )
        ).scalars().all()
        groups = [GroupRef(id=g.id, name=g.name) for g in sorted(group_rows, key=lambda g: g.name.lower())]
        for group in group_rows:
            keys: set[str] = set()
            role_refs: list[RoleRef] = []
            for link in group.role_links:
                role = link.role
                role_keys = _role_keys(role)
                role_privilege_map[role.id] = role_keys
                keys |= role_keys
                ref = _role_ref(role)
                role_refs.append(ref)
                seen_roles[role.id] = ref
            group_privilege_map[group.id] = keys
            group_role_map[group.id] = sorted(role_refs, key=lambda r: r.name.lower())
            privileges.update(keys)
        scope_rows = (
            await session.execute(select(AccessGroupScope).where(AccessGroupScope.group_id.in_(group_ids)))
        ).scalars().all()
        scopes = [
            ScopeOut(
                id=s.id,
                tag_key=s.tag_key,
                tag_value=s.tag_value,
                provider=s.provider,
                connection_id=s.connection_id,
            )
            for s in scope_rows
        ]

    direct_roles, direct, direct_map = await _direct_role_access(session, user.id)
    role_privilege_map.update(direct_map)
    for role in direct_roles:
        seen_roles[role.id] = role
    privileges.update(direct)
    if "platform_admin" in (user.roles or []):
        privileges.add(PLATFORM_ADMIN_KEY)
    access_roles = sorted(seen_roles.values(), key=lambda r: r.name.lower())
    return UserAccess(
        group_ids,
        groups,
        scopes,
        privileges,
        set(direct),
        group_privilege_map,
        access_roles,
        group_role_map,
        direct_roles,
        role_privilege_map,
    )


async def _direct_role_access(
    session: AsyncSession, user_id: UUID
) -> tuple[list[RoleRef], list[str], dict[UUID, set[str]]]:
    links = (
        await session.execute(
            select(UserRole)
            .options(selectinload(UserRole.role).selectinload(AccessRole.privilege_grants))
            .where(UserRole.user_id == user_id)
        )
    ).scalars().all()
    roles = [_role_ref(link.role) for link in links]
    keys: list[str] = []
    mapping: dict[UUID, set[str]] = {}
    for link in links:
        role_keys = _role_keys(link.role)
        mapping[link.role.id] = role_keys
        keys.extend(role_keys)
    return sorted(roles, key=lambda r: r.name.lower()), sorted(set(keys)), mapping


async def _ensure_in_platform_admins(session: AsyncSession, user: User) -> None:
    group = (
        await session.execute(select(AccessGroup).where(AccessGroup.name == "Platform Admins"))
    ).scalar_one_or_none()
    if group is None:
        return
    existing = (
        await session.execute(
            select(AccessGroupMember).where(
                AccessGroupMember.group_id == group.id,
                AccessGroupMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            AccessGroupMember(
                group_id=group.id,
                user_id=user.id,
                email=user.email,
                entra_oid=user.entra_oid,
            )
        )
    role = (
        await session.execute(select(AccessRole).where(AccessRole.name == PLATFORM_ADMIN_ROLE_NAME))
    ).scalar_one_or_none()
    if role is None:
        role = AccessRole(
            name=PLATFORM_ADMIN_ROLE_NAME,
            description="Full control of Looking Glass.",
            is_system=True,
        )
        session.add(role)
        await session.flush()
        session.add(RolePrivilege(role_id=role.id, privilege_key=PLATFORM_ADMIN_KEY))
    linked = (
        await session.execute(
            select(GroupRole).where(GroupRole.group_id == group.id, GroupRole.role_id == role.id)
        )
    ).scalar_one_or_none()
    if linked is None:
        session.add(GroupRole(group_id=group.id, role_id=role.id))
    await session.commit()


async def load_user_scopes(session: AsyncSession, user: User) -> tuple[list[ScopeOut], list[UUID]]:
    access = await load_user_access(session, user)
    return access.scopes, access.group_ids
