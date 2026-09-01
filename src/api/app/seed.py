from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AccessGroup,
    AccessGroupMember,
    AccessGroupScope,
    AccessRole,
    Connection,
    CostLineItem,
    Dashboard,
    GroupPrivilege,
    GroupRole,
    RolePrivilege,
    User,
    UserPrivilege,
    UserRole,
)
from app.privileges import ALL_KEYS, DEMO_COST_KEYS, PLATFORM_ADMIN_KEY, PLATFORM_ADMIN_ROLE_NAME
from app.services.recommend import refresh_recommendations

DEMO_USERS = [
    {
        "entra_oid": "demo-admin",
        "email": "avery.chen@lookingglass.local",
        "display_name": "Avery Chen",
        "roles": ["platform_admin"],
        "status": "active",
        "notes": "Seeded platform administrator.",
    },
    {
        "entra_oid": "demo-infra",
        "email": "sam.okonkwo@lookingglass.local",
        "display_name": "Sam Okonkwo",
        "roles": ["analyst"],
        "status": "active",
        "notes": "",
    },
    {
        "entra_oid": "demo-project",
        "email": "priya.shah@lookingglass.local",
        "display_name": "Priya Shah",
        "roles": ["analyst"],
        "status": "active",
        "notes": "",
    },
    {
        "entra_oid": "demo-maya",
        "email": "maya.patel@lookingglass.local",
        "display_name": "Maya Patel",
        "roles": ["analyst"],
        "status": "disabled",
        "notes": "Former contractor. Account kept for audit, access revoked.",
    },
    {
        "entra_oid": "demo-jordan",
        "email": "jordan.lee@lookingglass.local",
        "display_name": "Jordan Lee",
        "roles": ["analyst"],
        "status": "active",
        "notes": "Waiting for group assignment.",
    },
]


async def seed_if_empty(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count()).select_from(Connection))
    if count:
        return
    await seed(session)


async def seed(session: AsyncSession) -> None:
    users = {}
    for spec in DEMO_USERS:
        user = User(
            entra_oid=spec["entra_oid"],
            email=spec["email"],
            display_name=spec["display_name"],
            roles=spec["roles"],
            entra_group_ids=[],
            status=spec.get("status", "active"),
            notes=spec.get("notes", ""),
            last_login_at=datetime.now(UTC) if spec.get("status", "active") == "active" else None,
        )
        session.add(user)
        users[spec["entra_oid"]] = user
    await session.flush()

    connections = [
        Connection(
            name="Contoso Corp – Azure tenant",
            provider="azure",
            status="connected",
            config={
                "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "scope": "management-group/contoso",
                "note": "Seeded demo tenant",
            },
            last_ingest_at=datetime.now(UTC),
        ),
        Connection(
            name="Fabrikam – Azure tenant",
            provider="azure",
            status="connected",
            config={
                "tenant_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "scope": "management-group/fabrikam",
            },
            last_ingest_at=datetime.now(UTC),
        ),
        Connection(
            name="Contoso – AWS payer",
            provider="aws",
            status="connected",
            config={"account_id": "111111111111", "cur_uri": "s3://contoso-cur/out/"},
            last_ingest_at=datetime.now(UTC),
        ),
        Connection(
            name="Contoso – GCP org",
            provider="gcp",
            status="connected",
            config={"billing_table": "contoso.billing.gcp_billing_export_v1"},
            last_ingest_at=datetime.now(UTC),
        ),
    ]
    session.add_all(connections)
    await session.flush()

    admins = AccessGroup(
        name="Platform Admins",
        description="Full control of Looking Glass: users, groups, privileges, connectors and every cloud account.",
        is_system=True,
    )
    infra = AccessGroup(
        name="Infra",
        description="Platform engineers. FinOps on resources tagged team=infra.",
    )
    alpha = AccessGroup(
        name="Project Alpha",
        description="Application team. FinOps on resources tagged project=alpha.",
    )
    session.add_all([admins, infra, alpha])
    await session.flush()
    platform_role = AccessRole(
        name=PLATFORM_ADMIN_ROLE_NAME,
        description="Full control of Looking Glass. You can change the name; platform.admin stays checked.",
        is_system=True,
    )
    cost_role = AccessRole(
        name="Cost access",
        description="Demo role: FinOps and viewing connectors. Rename or replace this in Admin → Roles.",
        is_system=False,
    )
    session.add_all([platform_role, cost_role])
    await session.flush()
    session.add_all(
        [
            RolePrivilege(role_id=platform_role.id, privilege_key=PLATFORM_ADMIN_KEY),
            *[RolePrivilege(role_id=cost_role.id, privilege_key=key) for key in DEMO_COST_KEYS],
            GroupRole(group_id=admins.id, role_id=platform_role.id),
            GroupRole(group_id=infra.id, role_id=cost_role.id),
            GroupRole(group_id=alpha.id, role_id=cost_role.id),
            AccessGroupScope(group_id=infra.id, tag_key="team", tag_value="infra"),
            AccessGroupScope(group_id=alpha.id, tag_key="project", tag_value="alpha"),
            AccessGroupMember(
                group_id=admins.id,
                user_id=users["demo-admin"].id,
                email=users["demo-admin"].email,
                entra_oid=users["demo-admin"].entra_oid,
            ),
            AccessGroupMember(
                group_id=infra.id,
                user_id=users["demo-infra"].id,
                email=users["demo-infra"].email,
                entra_oid=users["demo-infra"].entra_oid,
            ),
            AccessGroupMember(
                group_id=alpha.id,
                user_id=users["demo-project"].id,
                email=users["demo-project"].email,
                entra_oid=users["demo-project"].entra_oid,
            ),
        ]
    )

    resources = _resources(connections)
    session.add_all(_cost_rows(resources))
    await session.flush()

    session.add(
        Dashboard(
            name="Organisation overview",
            description="Multi-cloud spend, providers and top services.",
            owner_user_id=users["demo-admin"].id,
            visibility="org",
            widgets=[
                {"id": "w1", "type": "kpi", "title": "Period spend", "group_by": "service", "date_range": "30d"},
                {"id": "w2", "type": "timeseries", "title": "Daily cost", "group_by": "provider", "date_range": "30d"},
                {"id": "w3", "type": "breakdown", "title": "By provider", "group_by": "provider", "date_range": "30d"},
                {"id": "w4", "type": "breakdown", "title": "By service", "group_by": "service", "date_range": "30d"},
                {"id": "w5", "type": "breakdown", "title": "By team tag", "group_by": "tag:team", "date_range": "30d"},
                {"id": "w6", "type": "recommendations", "title": "Open savings", "group_by": "service", "date_range": "30d"},
            ],
        )
    )
    session.add(
        Dashboard(
            name="Infra estate",
            description="Shared with the Infra access group.",
            owner_user_id=users["demo-admin"].id,
            visibility="group",
            shared_group_id=infra.id,
            widgets=[
                {"id": "i1", "type": "kpi", "title": "Infra spend", "group_by": "service", "date_range": "30d"},
                {"id": "i2", "type": "timeseries", "title": "Infra daily", "group_by": "account", "date_range": "30d"},
                {"id": "i3", "type": "breakdown", "title": "Infra accounts", "group_by": "account", "date_range": "30d"},
                {"id": "i4", "type": "table", "title": "Top resources", "group_by": "resource", "date_range": "30d"},
            ],
        )
    )
    await session.commit()
    await refresh_recommendations(session)


async def ensure_iam(session: AsyncSession) -> None:
    """Backfill the Platform Admins group and migrate raw privileges onto roles."""
    for spec in DEMO_USERS:
        existing = (
            await session.execute(select(User).where(User.entra_oid == spec["entra_oid"]))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    entra_oid=spec["entra_oid"],
                    email=spec["email"],
                    display_name=spec["display_name"],
                    roles=spec["roles"],
                    entra_group_ids=[],
                    status=spec.get("status", "active"),
                    notes=spec.get("notes", ""),
                    last_login_at=datetime.now(UTC) if spec.get("status", "active") == "active" else None,
                )
            )
    await session.flush()

    admins = (
        await session.execute(select(AccessGroup).where(AccessGroup.name == "Platform Admins"))
    ).scalar_one_or_none()
    if admins is None:
        admins = AccessGroup(
            name="Platform Admins",
            description="Full control of Looking Glass: users, groups, roles, connectors and every cloud account.",
            is_system=True,
        )
        session.add(admins)
        await session.flush()
    admins.is_system = True

    platform_role = (
        await session.execute(select(AccessRole).where(AccessRole.name == PLATFORM_ADMIN_ROLE_NAME))
    ).scalar_one_or_none()
    if platform_role is None:
        platform_role = AccessRole(
            name=PLATFORM_ADMIN_ROLE_NAME,
            description="Full control of Looking Glass.",
            is_system=True,
        )
        session.add(platform_role)
        await session.flush()
    platform_role.is_system = True
    has_admin_priv = (
        await session.execute(
            select(RolePrivilege).where(
                RolePrivilege.role_id == platform_role.id,
                RolePrivilege.privilege_key == PLATFORM_ADMIN_KEY,
            )
        )
    ).scalar_one_or_none()
    if has_admin_priv is None:
        session.add(RolePrivilege(role_id=platform_role.id, privilege_key=PLATFORM_ADMIN_KEY))
    linked = (
        await session.execute(
            select(GroupRole).where(GroupRole.group_id == admins.id, GroupRole.role_id == platform_role.id)
        )
    ).scalar_one_or_none()
    if linked is None:
        session.add(GroupRole(group_id=admins.id, role_id=platform_role.id))

    platform_users = (
        await session.execute(select(User).where(User.roles.contains(["platform_admin"])))
    ).scalars().all()
    for user in platform_users:
        member = (
            await session.execute(
                select(AccessGroupMember).where(
                    AccessGroupMember.group_id == admins.id,
                    AccessGroupMember.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            session.add(
                AccessGroupMember(
                    group_id=admins.id,
                    user_id=user.id,
                    email=user.email,
                    entra_oid=user.entra_oid,
                )
            )

    await _migrate_group_privileges(session)
    await _migrate_user_privileges(session)
    await _strip_unknown_role_privileges(session)
    await session.commit()


async def _migrate_group_privileges(session: AsyncSession) -> None:
    groups = (
        await session.execute(
            select(AccessGroup).options(
                selectinload(AccessGroup.privilege_grants),
                selectinload(AccessGroup.role_links),
            )
        )
    ).scalars().all()
    for group in groups:
        if group.role_links:
            continue
        keys = sorted({row.privilege_key for row in group.privilege_grants if row.privilege_key in ALL_KEYS})
        if not keys:
            continue
        role_name = PLATFORM_ADMIN_ROLE_NAME if PLATFORM_ADMIN_KEY in keys else f"{group.name} access"
        role = (
            await session.execute(select(AccessRole).where(func.lower(AccessRole.name) == role_name.lower()))
        ).scalar_one_or_none()
        if role is None:
            role = AccessRole(
                name=role_name,
                description=f"Created from the {group.name} group so permissions live on a role.",
                is_system=PLATFORM_ADMIN_KEY in keys,
            )
            session.add(role)
            await session.flush()
            existing_keys = set()
        else:
            existing_keys = {
                row.privilege_key
                for row in (
                    await session.execute(select(RolePrivilege).where(RolePrivilege.role_id == role.id))
                ).scalars().all()
            }
        for key in keys:
            if key not in existing_keys:
                session.add(RolePrivilege(role_id=role.id, privilege_key=key))
        session.add(GroupRole(group_id=group.id, role_id=role.id))


async def _migrate_user_privileges(session: AsyncSession) -> None:
    grants = (await session.execute(select(UserPrivilege))).scalars().all()
    by_user: dict = {}
    for grant in grants:
        if grant.privilege_key not in ALL_KEYS:
            continue
        by_user.setdefault(grant.user_id, set()).add(grant.privilege_key)
    for user_id, keys in by_user.items():
        existing = (
            await session.execute(select(UserRole).where(UserRole.user_id == user_id))
        ).scalars().all()
        if existing:
            continue
        user = await session.get(User, user_id)
        if user is None:
            continue
        role_name = f"{user.display_name} access"
        role = (
            await session.execute(select(AccessRole).where(func.lower(AccessRole.name) == role_name.lower()))
        ).scalar_one_or_none()
        if role is None:
            role = AccessRole(
                name=role_name,
                description="Created from direct user privileges. Edit or replace this role.",
            )
            session.add(role)
            await session.flush()
            for key in sorted(keys):
                session.add(RolePrivilege(role_id=role.id, privilege_key=key))
        session.add(UserRole(user_id=user.id, role_id=role.id))


async def _strip_unknown_role_privileges(session: AsyncSession) -> None:
    rows = (await session.execute(select(RolePrivilege))).scalars().all()
    for row in rows:
        if row.privilege_key not in ALL_KEYS:
            await session.delete(row)


def _resources(connections: list[Connection]) -> list[dict]:
    azure_a, azure_b, aws, gcp = connections
    return [
        _r(azure_a, "sub-infra-prod", "az-infra-prod", "rg-infra", "vm-jump-01", "Virtual Machine", "Virtual Machines", "Compute", "uksouth", {"team": "infra", "env": "prod", "costCenter": "platform"}, idle=True),
        _r(azure_a, "sub-infra-prod", "az-infra-prod", "rg-infra", "aks-platform", "Azure Kubernetes Service", "Azure Kubernetes Service", "Compute", "uksouth", {"team": "infra", "env": "prod", "costCenter": "platform"}),
        _r(azure_a, "sub-infra-prod", "az-infra-prod", "rg-infra", "disk-orphan-01", "Managed Disk", "Storage", "Storage", "uksouth", {"team": "infra", "env": "prod"}),
        _r(azure_a, "sub-infra-prod", "az-infra-prod", "rg-network", "pip-old-nat", "Public IP", "Bandwidth", "Network", "uksouth", {"team": "infra", "env": "prod"}),
        _r(azure_a, "sub-alpha-prod", "az-alpha-prod", "rg-alpha", "app-alpha-api", "App Service", "Azure App Service", "Compute", "uksouth", {"team": "product", "project": "alpha", "env": "prod"}),
        _r(azure_a, "sub-alpha-prod", "az-alpha-prod", "rg-alpha", "sql-alpha", "Azure SQL Database", "SQL Database", "Database", "uksouth", {"team": "product", "project": "alpha", "env": "prod"}),
        _r(azure_a, "sub-alpha-dev", "az-alpha-dev", "rg-alpha-dev", "stalpha", "Storage Account", "Storage", "Storage", "uksouth", {"team": "product", "project": "alpha", "env": "dev"}),
        _r(azure_b, "sub-shared-services", "fabrikam-shared", "rg-shared", "kv-fabrikam", "Key Vault", "Key Vault", "Other", "westeurope", {"team": "infra", "env": "prod", "costCenter": "security"}),
        _r(azure_b, "sub-data", "fabrikam-data", "rg-data", "synapse-core", "Synapse Workspace", "Azure Synapse Analytics", "Database", "westeurope", {"team": "data", "env": "prod"}),
        _r(aws, "111111111111", "aws-payer", "", "i-0idlebastion", "EC2 Instance", "Amazon Elastic Compute Cloud - Compute", "Compute", "eu-west-2", {"team": "infra", "env": "prod"}, idle=True),
        _r(aws, "111111111111", "aws-payer", "", "vol-unattached", "EBS Volume", "Amazon Elastic Block Store", "Storage", "eu-west-2", {"team": "infra", "env": "prod"}),
        _r(aws, "222222222222", "aws-alpha", "", "alpha-api-ecs", "ECS Service", "Amazon Elastic Container Service", "Compute", "eu-west-2", {"team": "product", "project": "alpha", "env": "prod"}),
        _r(aws, "222222222222", "aws-alpha", "", "alpha-rds", "RDS Instance", "Amazon Relational Database Service", "Database", "eu-west-2", {"team": "product", "project": "alpha", "env": "prod"}),
        _r(gcp, "proj-infra-host", "gcp-infra-host", "", "gke-shared", "GKE Cluster", "Kubernetes Engine", "Compute", "europe-west2", {"team": "infra", "env": "prod", "costCenter": "platform"}),
        _r(gcp, "proj-alpha", "gcp-alpha", "", "run-alpha-worker", "Cloud Run", "Cloud Run", "Compute", "europe-west2", {"team": "product", "project": "alpha", "env": "prod"}),
        _r(gcp, "proj-sandbox", "gcp-sandbox", "", "vm-scratch", "Compute Engine VM", "Compute Engine", "Compute", "europe-west2", {"env": "dev"}, idle=True),
    ]


def _r(connection, account_id, account_name, resource_group, name, rtype, service, category, region, tags, idle=False):
    if connection.provider == "azure":
        resource_id = f"/subscriptions/{account_id}/resourceGroups/{resource_group}/providers/Microsoft.Compute/{name}"
    else:
        resource_id = f"{connection.provider}://{account_id}/{name}"
    return {
        "connection": connection,
        "account_id": account_id,
        "account_name": account_name,
        "resource_group": resource_group,
        "resource_id": resource_id,
        "resource_name": name,
        "resource_type": rtype,
        "service": service,
        "category": category,
        "region": region,
        "tags": tags,
        "idle": idle,
        "base": {
            "Compute": 42,
            "Storage": 9,
            "Database": 28,
            "Network": 6,
            "Other": 3,
        }[category],
    }


def _cost_rows(resources: list[dict]) -> list[CostLineItem]:
    rng = random.Random(42)
    today = date.today()
    items: list[CostLineItem] = []
    for offset in range(90):
        day = today - timedelta(days=offset)
        weekday = 0.75 if day.weekday() >= 5 else 1.0
        trend = 1.0 + (90 - offset) * 0.0015
        for res in resources:
            jitter = rng.uniform(0.85, 1.2)
            usage = rng.uniform(0.1, 1.5) if res["idle"] else rng.uniform(8, 40)
            cost = round(res["base"] * weekday * trend * jitter, 2)
            if res["resource_type"] in {"Managed Disk", "EBS Volume"} and "attached_to" not in res["tags"]:
                cost = round(cost * 0.55, 2)
            items.append(
                CostLineItem(
                    usage_date=day,
                    connection_id=res["connection"].id,
                    provider=res["connection"].provider,
                    account_id=res["account_id"],
                    account_name=res["account_name"],
                    resource_group=res.get("resource_group") or "",
                    org_id=str((res["connection"].config or {}).get("tenant_id") or (res["connection"].config or {}).get("account_id") or res["connection"].name),
                    org_name=res["connection"].name,
                    resource_id=res["resource_id"],
                    resource_name=res["resource_name"],
                    resource_type=res["resource_type"],
                    service=res["service"],
                    category=res["category"],
                    meter=f"{res['service']} – usage",
                    region=res["region"],
                    tags=res["tags"],
                    cost=cost,
                    amortized_cost=round(cost * 0.92, 2),
                    currency="GBP",
                    usage_quantity=round(usage, 2),
                    usage_unit="Hours" if res["category"] == "Compute" else "Units",
                )
            )
    return items
