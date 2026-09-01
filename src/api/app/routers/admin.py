from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import load_user_access, require_admin_area, require_privilege
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
from app.privileges import (
    ALL_KEYS,
    CATALOG,
    PLATFORM_ADMIN_KEY,
    catalog_payload,
    unknown_privileges,
)
from app.schemas import (
    AdminOverview,
    CurrentUser,
    GroupIn,
    GroupOut,
    GroupRef,
    MemberIn,
    MemberOut,
    PrivilegeAssignmentOut,
    PrivilegeCatalogOut,
    PrivilegeDefOut,
    PrivilegeGrantSource,
    PrivilegeSet,
    PrivilegeSourceOut,
    RecentLoginOut,
    RoleIdSet,
    RoleIn,
    RoleOut,
    RoleRef,
    ScopeIn,
    ScopeOut,
    UserCreate,
    UserDetailOut,
    UserListOut,
    UserPatch,
    UserRef,
)
from app.services.recommend import refresh_recommendations

router = APIRouter(prefix="/admin", tags=["admin"])


def _role_load():
    return selectinload(AccessRole.privilege_grants), selectinload(AccessRole.group_links), selectinload(
        AccessRole.user_links
    )


def _group_loads():
    return (
        selectinload(AccessGroup.members),
        selectinload(AccessGroup.scopes),
        selectinload(AccessGroup.role_links).selectinload(GroupRole.role).selectinload(AccessRole.privilege_grants),
    )


def _role_keys(role: AccessRole) -> set[str]:
    return {row.privilege_key for row in role.privilege_grants}


def _role_ref(role: AccessRole) -> RoleRef:
    return RoleRef(id=role.id, name=role.name, is_system=bool(role.is_system))


@router.get("/overview", response_model=AdminOverview)
async def overview(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_admin_area),
):
    users = (await session.execute(select(User).order_by(User.display_name))).scalars().all()
    groups = (
        await session.execute(select(AccessGroup).options(selectinload(AccessGroup.role_links)))
    ).scalars().all()
    role_count = await session.scalar(select(func.count()).select_from(AccessRole)) or 0
    members = (await session.execute(select(AccessGroupMember))).scalars().all()
    users_in_groups: set[UUID] = set()
    for member in members:
        if member.user_id:
            users_in_groups.add(member.user_id)
        if member.email:
            for user in users:
                if user.email and user.email.lower() == member.email.lower():
                    users_in_groups.add(user.id)
    without_groups = [
        UserRef(id=u.id, display_name=u.display_name, email=u.email)
        for u in users
        if u.id not in users_in_groups and (u.status or "active") == "active"
    ]
    without_roles = [GroupRef(id=g.id, name=g.name) for g in groups if not g.role_links and not g.is_system]
    recent = sorted(users, key=lambda u: u.last_login_at or u.created_at, reverse=True)[:8]
    active = [u for u in users if (u.status or "active") == "active"]
    disabled = [u for u in users if (u.status or "active") == "disabled"]
    return AdminOverview(
        user_count=len(users),
        active_user_count=len(active),
        disabled_user_count=len(disabled),
        group_count=len(groups),
        role_count=int(role_count),
        users_without_groups=without_groups,
        groups_without_roles=without_roles,
        recent_logins=[
            RecentLoginOut(
                id=u.id,
                display_name=u.display_name,
                email=u.email,
                last_login_at=u.last_login_at,
                status=u.status or "active",
            )
            for u in recent
        ],
    )


@router.get("/privileges", response_model=PrivilegeCatalogOut)
async def list_privilege_catalog(_: CurrentUser = Depends(require_admin_area)):
    return PrivilegeCatalogOut(catalog=[PrivilegeDefOut(**item) for item in catalog_payload()])


@router.get("/privileges/assignments", response_model=list[PrivilegeAssignmentOut])
async def list_privilege_assignments(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_admin_area),
):
    roles = (await session.execute(select(AccessRole).options(*_role_load()))).scalars().all()
    groups = (await session.execute(select(AccessGroup).options(selectinload(AccessGroup.role_links)))).scalars().all()
    users = (await session.execute(select(User))).scalars().all()
    user_roles = (
        await session.execute(select(UserRole).options(selectinload(UserRole.role).selectinload(AccessRole.privilege_grants)))
    ).scalars().all()
    members = (await session.execute(select(AccessGroupMember))).scalars().all()
    user_by_id = {u.id: u for u in users}

    role_keys = {role.id: _role_keys(role) for role in roles}
    roles_by_key: dict[str, list[RoleRef]] = {key: [] for key in ALL_KEYS}
    for role in roles:
        for key in role_keys[role.id]:
            roles_by_key.setdefault(key, []).append(_role_ref(role))

    groups_by_key: dict[str, list[GroupRef]] = {key: [] for key in ALL_KEYS}
    group_keys: dict[UUID, set[str]] = {}
    for group in groups:
        keys: set[str] = set()
        for link in group.role_links:
            keys |= role_keys.get(link.role_id, set())
        group_keys[group.id] = keys
        for key in keys:
            groups_by_key.setdefault(key, []).append(GroupRef(id=group.id, name=group.name))

    direct_by_key: dict[str, list[UserRef]] = {key: [] for key in ALL_KEYS}
    user_direct_keys: dict[UUID, set[str]] = {}
    for link in user_roles:
        keys = _role_keys(link.role)
        user_direct_keys.setdefault(link.user_id, set()).update(keys)
        user = user_by_id.get(link.user_id)
        if not user:
            continue
        for key in keys:
            refs = direct_by_key.setdefault(key, [])
            if all(item.id != user.id for item in refs):
                refs.append(UserRef(id=user.id, display_name=user.display_name, email=user.email))

    group_members: dict[UUID, set[UUID]] = {g.id: set() for g in groups}
    email_to_user = {u.email.lower(): u.id for u in users if u.email}
    for member in members:
        if member.user_id:
            group_members.setdefault(member.group_id, set()).add(member.user_id)
        elif member.email and member.email.lower() in email_to_user:
            group_members.setdefault(member.group_id, set()).add(email_to_user[member.email.lower()])

    admin_groups = {gid for gid, keys in group_keys.items() if PLATFORM_ADMIN_KEY in keys}
    admin_direct = {uid for uid, keys in user_direct_keys.items() if PLATFORM_ADMIN_KEY in keys}
    admin_legacy = {u.id for u in users if "platform_admin" in (u.roles or [])}

    out: list[PrivilegeAssignmentOut] = []
    for item in CATALOG:
        holders: set[UUID] = set(admin_direct | admin_legacy)
        for gid in admin_groups:
            holders |= group_members.get(gid, set())
        holders |= {uid for uid, keys in user_direct_keys.items() if item.key in keys}
        for group in groups:
            if item.key in group_keys.get(group.id, set()):
                holders |= group_members.get(group.id, set())
        holders = {uid for uid in holders if user_by_id.get(uid) and (user_by_id[uid].status or "active") == "active"}
        out.append(
            PrivilegeAssignmentOut(
                key=item.key,
                module=item.module,
                name=item.name,
                description=item.description,
                roles=sorted(roles_by_key.get(item.key, []), key=lambda r: r.name.lower()),
                groups=sorted(groups_by_key.get(item.key, []), key=lambda g: g.name.lower()),
                direct_users=sorted(direct_by_key.get(item.key, []), key=lambda u: u.display_name.lower()),
                effective_user_count=len(holders),
            )
        )
    return out


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.read", "admin.groups.read", "admin.users.read")),
):
    rows = (await session.execute(select(AccessRole).options(*_role_load()).order_by(AccessRole.name))).scalars().all()
    return [await _role_out(session, role) for role in rows]


@router.post("/roles", response_model=RoleOut)
async def create_role(
    body: RoleIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.write")),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required")
    taken = (
        await session.execute(select(AccessRole).where(func.lower(AccessRole.name) == name.lower()))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(status_code=409, detail="A role with that name already exists")
    keys = _validated_privileges(body.privileges)
    role = AccessRole(name=name, description=body.description, is_system=False)
    session.add(role)
    await session.flush()
    for key in keys:
        session.add(RolePrivilege(role_id=role.id, privilege_key=key))
    await session.commit()
    return await _role_out(session, await _load_role(session, role.id))


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.read", "admin.groups.read", "admin.users.read")),
):
    return await _role_out(session, await _load_role(session, role_id))


@router.put("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: UUID,
    body: RoleIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.write")),
):
    role = await _load_role(session, role_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required")
    taken = (
        await session.execute(
            select(AccessRole).where(func.lower(AccessRole.name) == name.lower(), AccessRole.id != role.id)
        )
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(status_code=409, detail="A role with that name already exists")
    keys = _validated_privileges(body.privileges)
    if role.is_system and PLATFORM_ADMIN_KEY not in keys:
        raise HTTPException(status_code=400, detail="The platform administrator role must keep platform.admin")
    if PLATFORM_ADMIN_KEY in _role_keys(role) and PLATFORM_ADMIN_KEY not in keys:
        await _guard_last_admin_role(session)
    role.name = name
    role.description = body.description
    await _replace_role_privileges(session, role, keys)
    await session.commit()
    return await _role_out(session, await _load_role(session, role.id))


@router.put("/roles/{role_id}/privileges", response_model=RoleOut)
async def set_role_privileges(
    role_id: UUID,
    body: PrivilegeSet,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.write")),
):
    role = await _load_role(session, role_id)
    keys = _validated_privileges(body.privileges)
    if role.is_system and PLATFORM_ADMIN_KEY not in keys:
        raise HTTPException(status_code=400, detail="The platform administrator role must keep platform.admin")
    if PLATFORM_ADMIN_KEY in _role_keys(role) and PLATFORM_ADMIN_KEY not in keys:
        await _guard_last_admin_role(session)
    await _replace_role_privileges(session, role, keys)
    await session.commit()
    return await _role_out(session, await _load_role(session, role.id))


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.roles.write")),
):
    role = await _load_role(session, role_id)
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    if PLATFORM_ADMIN_KEY in _role_keys(role):
        await _guard_last_admin_role(session)
    await session.delete(role)
    await session.commit()
    return {"ok": True}


@router.get("/users", response_model=list[UserListOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.users.read", "admin.groups.read")),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
):
    stmt = select(User).order_by(User.display_name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.email.ilike(like)))
    if status:
        stmt = stmt.where(User.status == status)
    users = (await session.execute(stmt)).scalars().all()
    context = await _iam_context(session)
    rows = [_user_list_out(user, context) for user in users]
    if group_id:
        rows = [row for row in rows if any(g.id == group_id for g in row.groups)]
    return rows


@router.post("/users", response_model=UserDetailOut)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.users.write")),
):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    existing = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    entra_oid = (body.entra_oid or "").strip() or f"pending:{email}"
    oid_taken = (await session.execute(select(User).where(User.entra_oid == entra_oid))).scalar_one_or_none()
    if oid_taken:
        raise HTTPException(status_code=409, detail="A user with that identity already exists")
    user = User(
        entra_oid=entra_oid,
        email=email,
        display_name=body.display_name.strip() or email,
        roles=["analyst"],
        entra_group_ids=[],
        status="active",
        notes=body.notes or "",
    )
    session.add(user)
    await session.flush()
    await _replace_user_roles(session, user, body.role_ids)
    for group_id in body.group_ids:
        group = await session.get(AccessGroup, group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group {group_id} not found")
        session.add(
            AccessGroupMember(
                group_id=group.id,
                user_id=user.id,
                email=user.email,
                entra_oid=user.entra_oid,
            )
        )
    await session.commit()
    return await _user_detail(session, user.id, actor)


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.users.read")),
):
    return await _user_detail(session, user_id)


@router.patch("/users/{user_id}", response_model=UserDetailOut)
async def patch_user(
    user_id: UUID,
    body: UserPatch,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.users.write")),
):
    user = await _get_user(session, user_id)
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Display name cannot be empty")
        user.display_name = name
    if body.notes is not None:
        user.notes = body.notes
    if body.status is not None and body.status != (user.status or "active"):
        if body.status == "disabled":
            await _guard_losing_admin(session, user, disabling=True)
        user.status = body.status
    await session.commit()
    return await _user_detail(session, user.id, actor)


@router.put("/users/{user_id}/roles", response_model=UserDetailOut)
async def set_user_roles(
    user_id: UUID,
    body: RoleIdSet,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.users.write")),
):
    user = await _get_user(session, user_id)
    await _guard_losing_admin(session, user, keep_direct_admin=False, next_direct_role_ids=body.role_ids)
    await _replace_user_roles(session, user, body.role_ids)
    await session.commit()
    return await _user_detail(session, user.id, actor)


@router.post("/users/{user_id}/groups/{group_id}", response_model=UserDetailOut)
async def add_user_to_group(
    user_id: UUID,
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.users.write")),
):
    user = await _get_user(session, user_id)
    group = await _load_group(session, group_id)
    await _add_member_row(session, group, MemberIn(user_id=user.id, email=user.email, entra_oid=user.entra_oid))
    await session.commit()
    return await _user_detail(session, user.id, actor)


@router.delete("/users/{user_id}/groups/{group_id}", response_model=UserDetailOut)
async def remove_user_from_group(
    user_id: UUID,
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    actor: CurrentUser = Depends(require_privilege("admin.users.write")),
):
    user = await _get_user(session, user_id)
    group = await _load_group(session, group_id)
    if group.is_system:
        await _guard_losing_admin(session, user, dropping_group_id=group.id)
    members = (
        await session.execute(
            select(AccessGroupMember).where(
                AccessGroupMember.group_id == group_id,
                or_(
                    AccessGroupMember.user_id == user.id,
                    func.lower(AccessGroupMember.email) == user.email.lower(),
                    AccessGroupMember.entra_oid == user.entra_oid,
                ),
            )
        )
    ).scalars().all()
    if not members:
        raise HTTPException(status_code=404, detail="User is not a member of this group")
    for member in members:
        await session.delete(member)
    await session.commit()
    return await _user_detail(session, user.id, actor)


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.read")),
    q: str | None = Query(default=None),
):
    stmt = select(AccessGroup).options(*_group_loads()).order_by(AccessGroup.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(AccessGroup.name.ilike(like), AccessGroup.description.ilike(like)))
    rows = (await session.execute(stmt)).scalars().all()
    return [await _group_out(session, g) for g in rows]


@router.post("/groups", response_model=GroupOut)
async def create_group(
    body: GroupIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    taken = (
        await session.execute(select(AccessGroup).where(func.lower(AccessGroup.name) == name.lower()))
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(status_code=409, detail="A group with that name already exists")
    group = AccessGroup(name=name, description=body.description, is_system=False)
    session.add(group)
    await session.flush()
    await _replace_group_roles(session, group, body.role_ids)
    await session.commit()
    return await _group_out(session, await _load_group(session, group.id))


@router.get("/groups/{group_id}", response_model=GroupOut)
async def get_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.read")),
):
    return await _group_out(session, await _load_group(session, group_id))


@router.put("/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: UUID,
    body: GroupIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    taken = (
        await session.execute(
            select(AccessGroup).where(func.lower(AccessGroup.name) == name.lower(), AccessGroup.id != group.id)
        )
    ).scalar_one_or_none()
    if taken:
        raise HTTPException(status_code=409, detail="A group with that name already exists")
    group.name = name
    group.description = body.description
    if body.role_ids:
        await _replace_group_roles(session, group, body.role_ids)
    await session.commit()
    return await _group_out(session, await _load_group(session, group_id))


@router.put("/groups/{group_id}/roles", response_model=GroupOut)
async def set_group_roles(
    group_id: UUID,
    body: RoleIdSet,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    if group.is_system:
        roles = await _roles_by_ids(session, body.role_ids)
        if not any(PLATFORM_ADMIN_KEY in _role_keys(role) for role in roles):
            raise HTTPException(
                status_code=400,
                detail="The platform administrators group must keep a role with platform.admin",
            )
    await _replace_group_roles(session, group, body.role_ids)
    await session.commit()
    return await _group_out(session, await _load_group(session, group_id))


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    if group.is_system:
        raise HTTPException(status_code=400, detail="System groups cannot be deleted")
    await session.delete(group)
    await session.commit()
    return {"ok": True}


@router.post("/groups/{group_id}/members", response_model=MemberOut)
async def add_member(
    group_id: UUID,
    body: MemberIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    member = await _add_member_row(session, group, body)
    await session.commit()
    await session.refresh(member)
    return await _member_out(session, member)


@router.delete("/groups/{group_id}/members/{member_id}")
async def remove_member(
    group_id: UUID,
    member_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    member = await session.get(AccessGroupMember, member_id)
    if member is None or member.group_id != group_id:
        raise HTTPException(status_code=404, detail="Member not found")
    if group.is_system and member.user_id:
        user = await session.get(User, member.user_id)
        if user:
            await _guard_losing_admin(session, user, dropping_group_id=group.id)
    await session.delete(member)
    await session.commit()
    return {"ok": True}


@router.post("/groups/{group_id}/scopes", response_model=ScopeOut)
async def add_scope(
    group_id: UUID,
    body: ScopeIn,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    group = await _load_group(session, group_id)
    tag_key = body.tag_key.strip()
    tag_value = body.tag_value.strip()
    if not tag_key or not tag_value:
        raise HTTPException(status_code=400, detail="Tag key and value are required")
    duplicate = next(
        (
            s
            for s in group.scopes
            if s.tag_key == tag_key
            and s.tag_value == tag_value
            and (s.provider or "") == (body.provider or "")
            and s.connection_id == body.connection_id
        ),
        None,
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="That data scope is already on this group")
    scope = AccessGroupScope(
        group_id=group_id,
        tag_key=tag_key,
        tag_value=tag_value,
        provider=body.provider or None,
        connection_id=body.connection_id,
    )
    session.add(scope)
    await session.commit()
    await session.refresh(scope)
    return ScopeOut.model_validate(scope, from_attributes=True)


@router.delete("/groups/{group_id}/scopes/{scope_id}")
async def remove_scope(
    group_id: UUID,
    scope_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("admin.groups.write")),
):
    scope = await session.get(AccessGroupScope, scope_id)
    if scope is None or scope.group_id != group_id:
        raise HTTPException(status_code=404, detail="Scope not found")
    await session.delete(scope)
    await session.commit()
    return {"ok": True}


@router.post("/jobs/refresh-recommendations")
async def refresh(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_privilege("finops.recommendations.write")),
):
    count = await refresh_recommendations(session)
    return {"created": count}


class _IamContext:
    def __init__(self):
        self.groups: dict[UUID, AccessGroup] = {}
        self.user_groups: dict[UUID, list[AccessGroup]] = {}
        self.email_groups: dict[str, list[AccessGroup]] = {}
        self.user_direct: dict[UUID, set[str]] = {}
        self.user_direct_roles: dict[UUID, list[RoleRef]] = {}
        self.group_keys: dict[UUID, set[str]] = {}
        self.group_roles: dict[UUID, list[RoleRef]] = {}
        self.role_keys: dict[UUID, set[str]] = {}


async def _iam_context(session: AsyncSession) -> _IamContext:
    ctx = _IamContext()
    roles = (await session.execute(select(AccessRole).options(selectinload(AccessRole.privilege_grants)))).scalars().all()
    ctx.role_keys = {role.id: _role_keys(role) for role in roles}
    groups = (
        await session.execute(select(AccessGroup).options(selectinload(AccessGroup.role_links)))
    ).scalars().all()
    members = (await session.execute(select(AccessGroupMember))).scalars().all()
    user_links = (
        await session.execute(select(UserRole).options(selectinload(UserRole.role)))
    ).scalars().all()
    ctx.groups = {g.id: g for g in groups}
    for group in groups:
        refs = []
        keys: set[str] = set()
        for link in group.role_links:
            role = next((r for r in roles if r.id == link.role_id), None)
            if role is None:
                continue
            refs.append(_role_ref(role))
            keys |= ctx.role_keys.get(role.id, set())
        ctx.group_roles[group.id] = sorted(refs, key=lambda r: r.name.lower())
        ctx.group_keys[group.id] = keys
    for member in members:
        group = ctx.groups.get(member.group_id)
        if group is None:
            continue
        if member.user_id:
            ctx.user_groups.setdefault(member.user_id, [])
            if group not in ctx.user_groups[member.user_id]:
                ctx.user_groups[member.user_id].append(group)
        if member.email:
            ctx.email_groups.setdefault(member.email.lower(), [])
            if group not in ctx.email_groups[member.email.lower()]:
                ctx.email_groups[member.email.lower()].append(group)
    for link in user_links:
        ctx.user_direct.setdefault(link.user_id, set()).update(ctx.role_keys.get(link.role_id, set()))
        ctx.user_direct_roles.setdefault(link.user_id, []).append(_role_ref(link.role))
    return ctx


def _groups_for_user(user: User, ctx: _IamContext) -> list[AccessGroup]:
    found: dict[UUID, AccessGroup] = {}
    for group in ctx.user_groups.get(user.id, []):
        found[group.id] = group
    if user.email:
        for group in ctx.email_groups.get(user.email.lower(), []):
            found[group.id] = group
    return sorted(found.values(), key=lambda g: g.name.lower())


def _user_list_out(user: User, ctx: _IamContext) -> UserListOut:
    groups = _groups_for_user(user, ctx)
    direct = set(ctx.user_direct.get(user.id, set()))
    effective = set(direct)
    inherited_roles: dict[UUID, RoleRef] = {r.id: r for r in ctx.user_direct_roles.get(user.id, [])}
    for group in groups:
        effective |= ctx.group_keys.get(group.id, set())
        for role in ctx.group_roles.get(group.id, []):
            inherited_roles[role.id] = role
    if "platform_admin" in (user.roles or []):
        effective.add(PLATFORM_ADMIN_KEY)
    return UserListOut(
        id=user.id,
        entra_oid=user.entra_oid,
        email=user.email,
        display_name=user.display_name,
        roles=user.roles or [],
        status=user.status or "active",
        notes=user.notes or "",
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        is_admin=PLATFORM_ADMIN_KEY in effective,
        groups=[GroupRef(id=g.id, name=g.name) for g in groups],
        access_roles=sorted(inherited_roles.values(), key=lambda r: r.name.lower()),
        direct_roles=sorted(ctx.user_direct_roles.get(user.id, []), key=lambda r: r.name.lower()),
        direct_privileges=sorted(direct),
        privilege_count=len(effective),
    )


async def _user_detail(session: AsyncSession, user_id: UUID, _actor: CurrentUser | None = None) -> UserDetailOut:
    user = await _get_user(session, user_id)
    access = await load_user_access(session, user)
    sources: dict[str, list[PrivilegeGrantSource]] = {}
    for role in access.direct_roles:
        for key in access.role_privilege_map.get(role.id, set()):
            sources.setdefault(key, []).append(
                PrivilegeGrantSource(kind="role", role_id=role.id, role_name=role.name, via="direct")
            )
    for group in access.groups:
        for role in access.group_role_map.get(group.id, []):
            for key in access.role_privilege_map.get(role.id, set()):
                sources.setdefault(key, []).append(
                    PrivilegeGrantSource(
                        kind="role",
                        role_id=role.id,
                        role_name=role.name,
                        group_id=group.id,
                        group_name=group.name,
                        via="group",
                    )
                )
    ctx = await _iam_context(session)

    if PLATFORM_ADMIN_KEY in access.privileges:
        for item in CATALOG:
            if item.key == PLATFORM_ADMIN_KEY:
                continue
            if item.key not in sources:
                sources[item.key] = [PrivilegeGrantSource(kind="implied", via=PLATFORM_ADMIN_KEY)]
    privilege_sources = [
        PrivilegeSourceOut(key=item.key, name=item.name, module=item.module, sources=sources[item.key])
        for item in CATALOG
        if item.key in sources
    ]
    base = _user_list_out(user, ctx)
    return UserDetailOut(
        **base.model_dump(),
        entra_group_ids=user.entra_group_ids or [],
        effective_privileges=sorted(access.privileges),
        privilege_sources=privilege_sources,
        scopes=access.scopes,
    )


async def _get_user(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _load_group(session: AsyncSession, group_id: UUID) -> AccessGroup:
    cached = await session.get(AccessGroup, group_id)
    if cached is not None:
        session.expire(cached)
    group = (await session.execute(select(AccessGroup).options(*_group_loads()).where(AccessGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def _load_role(session: AsyncSession, role_id: UUID) -> AccessRole:
    cached = await session.get(AccessRole, role_id)
    if cached is not None:
        session.expire(cached)
    role = (
        await session.execute(select(AccessRole).options(*_role_load()).where(AccessRole.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


async def _role_out(session: AsyncSession, role: AccessRole) -> RoleOut:
    group_ids = [link.group_id for link in role.group_links]
    user_ids = [link.user_id for link in role.user_links]
    groups = []
    if group_ids:
        rows = (await session.execute(select(AccessGroup).where(AccessGroup.id.in_(group_ids)))).scalars().all()
        groups = [GroupRef(id=g.id, name=g.name) for g in sorted(rows, key=lambda g: g.name.lower())]
    users = []
    if user_ids:
        rows = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users = [
            UserRef(id=u.id, display_name=u.display_name, email=u.email)
            for u in sorted(rows, key=lambda u: u.display_name.lower())
        ]
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=bool(role.is_system),
        created_at=role.created_at,
        privileges=sorted(_role_keys(role)),
        groups=groups,
        users=users,
    )


async def _group_out(session: AsyncSession, group: AccessGroup) -> GroupOut:
    members = [await _member_out(session, m) for m in group.members]
    scopes = [ScopeOut.model_validate(s, from_attributes=True) for s in group.scopes]
    roles = [_role_ref(link.role) for link in group.role_links if link.role]
    privileges: set[str] = set()
    for link in group.role_links:
        if link.role:
            privileges |= _role_keys(link.role)
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        is_system=bool(group.is_system),
        created_at=group.created_at,
        members=members,
        scopes=scopes,
        roles=sorted(roles, key=lambda r: r.name.lower()),
        privileges=sorted(privileges),
    )


async def _member_out(session: AsyncSession, member: AccessGroupMember) -> MemberOut:
    name = None
    if member.user_id:
        user = await session.get(User, member.user_id)
        name = user.display_name if user else None
    elif member.email:
        user = (
            await session.execute(select(User).where(func.lower(User.email) == member.email.lower()))
        ).scalar_one_or_none()
        name = user.display_name if user else None
    kind = "user"
    if member.entra_group_id and not member.user_id:
        kind = "entra_group"
        name = name or "Entra ID group"
    return MemberOut(
        id=member.id,
        user_id=member.user_id,
        entra_oid=member.entra_oid,
        entra_group_id=member.entra_group_id,
        email=member.email,
        display_name=name,
        kind=kind,
    )


async def _add_member_row(session: AsyncSession, group: AccessGroup, body: MemberIn) -> AccessGroupMember:
    payload = body.model_dump()
    if payload.get("email") and not payload.get("user_id"):
        user = (
            await session.execute(select(User).where(func.lower(User.email) == payload["email"].lower()))
        ).scalar_one_or_none()
        if user:
            payload["user_id"] = user.id
            payload["entra_oid"] = payload.get("entra_oid") or user.entra_oid
            payload["email"] = user.email
    if payload.get("user_id"):
        user = await session.get(User, payload["user_id"])
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        payload["email"] = payload.get("email") or user.email
        payload["entra_oid"] = payload.get("entra_oid") or user.entra_oid
    if not payload.get("user_id") and not payload.get("email") and not payload.get("entra_group_id"):
        raise HTTPException(status_code=400, detail="Provide a user, email, or Entra group object ID")
    for existing in group.members:
        if payload.get("user_id") and existing.user_id == payload["user_id"]:
            raise HTTPException(status_code=409, detail="That user is already in this group")
        if payload.get("email") and existing.email and existing.email.lower() == payload["email"].lower():
            raise HTTPException(status_code=409, detail="That user is already in this group")
        if payload.get("entra_group_id") and existing.entra_group_id == payload["entra_group_id"]:
            raise HTTPException(status_code=409, detail="That Entra group is already mapped")
    member = AccessGroupMember(group_id=group.id, **payload)
    session.add(member)
    await session.flush()
    return member


async def _roles_by_ids(session: AsyncSession, role_ids: list[UUID]) -> list[AccessRole]:
    if not role_ids:
        return []
    rows = (
        await session.execute(
            select(AccessRole)
            .options(selectinload(AccessRole.privilege_grants))
            .where(AccessRole.id.in_(role_ids))
        )
    ).scalars().all()
    found = {row.id: row for row in rows}
    missing = [str(rid) for rid in role_ids if rid not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"Role not found: {', '.join(missing)}")
    return [found[rid] for rid in role_ids]


async def _replace_role_privileges(session: AsyncSession, role: AccessRole, keys: list[str]) -> None:
    keys = _validated_privileges(keys)
    existing = {row.privilege_key: row for row in role.privilege_grants}
    for key in keys:
        if key not in existing:
            session.add(RolePrivilege(role_id=role.id, privilege_key=key))
    for key, row in existing.items():
        if key not in keys:
            await session.delete(row)


async def _replace_group_roles(session: AsyncSession, group: AccessGroup, role_ids: list[UUID]) -> None:
    ids = list(dict.fromkeys(role_ids))
    await _roles_by_ids(session, ids)
    existing = {link.role_id: link for link in group.role_links}
    for role_id in ids:
        if role_id not in existing:
            session.add(GroupRole(group_id=group.id, role_id=role_id))
    for role_id, link in existing.items():
        if role_id not in ids:
            await session.delete(link)


async def _replace_user_roles(session: AsyncSession, user: User, role_ids: list[UUID]) -> None:
    ids = list(dict.fromkeys(role_ids))
    roles = await _roles_by_ids(session, ids)
    existing = (
        await session.execute(select(UserRole).where(UserRole.user_id == user.id))
    ).scalars().all()
    have = {link.role_id: link for link in existing}
    for role_id in ids:
        if role_id not in have:
            session.add(UserRole(user_id=user.id, role_id=role_id))
    for role_id, link in have.items():
        if role_id not in ids:
            await session.delete(link)
    has_admin = any(PLATFORM_ADMIN_KEY in _role_keys(role) for role in roles)
    _sync_admin_flag(user, has_admin)


def _validated_privileges(keys: list[str]) -> list[str]:
    unknown = unknown_privileges(keys)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown privileges: {', '.join(unknown)}")
    return sorted(set(keys))


def _sync_admin_flag(user: User, has_admin: bool) -> None:
    roles = {*(user.roles or [])}
    if has_admin:
        roles.add("platform_admin")
    else:
        roles.discard("platform_admin")
    if not roles:
        roles.add("analyst")
    user.roles = sorted(roles)


async def _active_admin_ids(session: AsyncSession) -> set[UUID]:
    users = (await session.execute(select(User).where(User.status == "active"))).scalars().all()
    ctx = await _iam_context(session)
    admins: set[UUID] = set()
    for user in users:
        groups = _groups_for_user(user, ctx)
        effective = set(ctx.user_direct.get(user.id, set()))
        for group in groups:
            effective |= ctx.group_keys.get(group.id, set())
        if "platform_admin" in (user.roles or []):
            effective.add(PLATFORM_ADMIN_KEY)
        if PLATFORM_ADMIN_KEY in effective:
            admins.add(user.id)
    return admins


async def _guard_last_admin_role(session: AsyncSession) -> None:
    admins = await _active_admin_ids(session)
    if len(admins) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last platform administrator")


async def _guard_losing_admin(
    session: AsyncSession,
    user: User,
    disabling: bool = False,
    keep_direct_admin: bool | None = None,
    dropping_group_id: UUID | None = None,
    next_direct_role_ids: list[UUID] | None = None,
) -> None:
    admins = await _active_admin_ids(session)
    if user.id not in admins:
        return
    if admins - {user.id}:
        return
    ctx = await _iam_context(session)
    groups = [g for g in _groups_for_user(user, ctx) if g.id != dropping_group_id]
    effective: set[str] = set()
    if next_direct_role_ids is not None:
        roles = await _roles_by_ids(session, next_direct_role_ids)
        for role in roles:
            effective |= _role_keys(role)
    elif keep_direct_admin is False:
        pass
    else:
        effective |= ctx.user_direct.get(user.id, set())
    for group in groups:
        effective |= ctx.group_keys.get(group.id, set())
    if not disabling and PLATFORM_ADMIN_KEY in effective:
        return
    raise HTTPException(status_code=400, detail="Cannot remove the last platform administrator")
