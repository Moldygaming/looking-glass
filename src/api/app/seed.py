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
    DevOpsPipelineAlert,
    DevOpsProject,
    DevOpsPullRequest,
    DevOpsStaleBranch,
    GroupPrivilege,
    GroupRole,
    RolePrivilege,
    User,
    UserPrivilege,
    UserRole,
)
from app.auth import ensure_break_glass_user
from app.identity import BREAK_GLASS_OID
from app.privileges import ALL_KEYS, DEMO_COST_KEYS, PLATFORM_ADMIN_KEY, PLATFORM_ADMIN_ROLE_NAME
from app.services.recommend import refresh_recommendations

DEMO_PERSONA_OIDS = (
    "demo-admin",
    "demo-infra",
    "demo-project",
    "demo-maya",
    "demo-jordan",
)


async def seed_if_empty(session: AsyncSession) -> None:
    count = await session.scalar(select(func.count()).select_from(Connection))
    if count:
        return
    await seed(session)


async def seed(session: AsyncSession) -> None:
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
        ]
    )

    infra_id = infra.id
    admin = await ensure_break_glass_user(session)
    admin_id = admin.id

    resources = _resources(connections)
    session.add_all(_cost_rows(resources))
    await session.flush()

    session.add(
        Dashboard(
            name="Organisation overview",
            description="Multi-cloud spend, providers and top services.",
            owner_user_id=admin_id,
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
            owner_user_id=admin_id,
            visibility="group",
            shared_group_id=infra_id,
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
    await ensure_devops_demo(session)


async def ensure_devops_demo(session: AsyncSession) -> None:
    """Seed a sample Azure DevOps health snapshot when none exists yet."""
    existing = (
        await session.execute(select(Connection).where(Connection.provider == "azure_devops"))
    ).scalars().first()
    if existing is not None:
        return
    now = datetime.now(UTC)
    connection = Connection(
        name="Contoso Engineering – Azure DevOps",
        provider="azure_devops",
        status="connected",
        config={
            "organization": "contoso",
            "organization_url": "https://dev.azure.com/contoso",
            "stale_days": 30,
            "pipeline_lookback": 8,
            "fail_consecutive": 3,
            "fail_rate": 0.75,
            "note": "Seeded demo organisation",
            "monitored_project_ids": [
                "ado-platform",
                "ado-website",
                "ado-payments",
            ],
        },
        last_ingest_at=now,
    )
    session.add(connection)
    await session.flush()

    platform = DevOpsProject(
        connection_id=connection.id,
        ado_project_id="ado-platform",
        name="Platform",
        description="Shared platform services and Looking Glass.",
        url="https://dev.azure.com/contoso/Platform",
        monitored=True,
        last_scan_at=now,
    )
    website = DevOpsProject(
        connection_id=connection.id,
        ado_project_id="ado-website",
        name="Website",
        description="Public site and CMS.",
        url="https://dev.azure.com/contoso/Website",
        monitored=True,
        last_scan_at=now,
    )
    payments = DevOpsProject(
        connection_id=connection.id,
        ado_project_id="ado-payments",
        name="Payments",
        description="Ledger and checkout APIs.",
        url="https://dev.azure.com/contoso/Payments",
        monitored=True,
        last_scan_at=now,
    )
    archive = DevOpsProject(
        connection_id=connection.id,
        ado_project_id="ado-archive",
        name="Archive",
        description="Retired products. Left unmonitored.",
        url="https://dev.azure.com/contoso/Archive",
        monitored=False,
    )
    session.add_all([platform, website, payments, archive])

    def ago(days: int, hours: int = 0) -> datetime:
        return now - timedelta(days=days, hours=hours)

    session.add_all(
        [
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                repo_id="repo-looking-glass",
                repo_name="looking-glass",
                pr_id=1842,
                title="Add cost facets from ingested resource types",
                created_by="Avery Chen",
                created_at=ago(2, 4),
                updated_at=ago(0, 3),
                source_branch="feat/cost-facets",
                target_branch="main",
                reviewer_count=2,
                url="https://dev.azure.com/contoso/Platform/_git/looking-glass/pullrequest/1842",
            ),
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                repo_id="repo-looking-glass",
                repo_name="looking-glass",
                pr_id=1799,
                title="Wire Azure DevOps health checks",
                created_by="Sam Okonkwo",
                created_at=ago(11, 6),
                updated_at=ago(1, 2),
                source_branch="feat/ado-health",
                target_branch="main",
                reviewer_count=1,
                url="https://dev.azure.com/contoso/Platform/_git/looking-glass/pullrequest/1799",
            ),
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                repo_id="repo-infra-bicep",
                repo_name="infra-bicep",
                pr_id=412,
                title="UK South Container Apps environment",
                created_by="Priya Shah",
                created_at=ago(4, 1),
                updated_at=ago(0, 8),
                source_branch="feat/cae-uksouth",
                target_branch="main",
                reviewer_count=3,
                url="https://dev.azure.com/contoso/Platform/_git/infra-bicep/pullrequest/412",
            ),
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-website",
                project_name="Website",
                repo_id="repo-www",
                repo_name="www",
                pr_id=908,
                title="Hero banner for Q3 campaign",
                created_by="Jordan Lee",
                created_at=ago(1, 5),
                updated_at=ago(0, 1),
                source_branch="feat/q3-hero",
                target_branch="main",
                is_draft=True,
                reviewer_count=0,
                url="https://dev.azure.com/contoso/Website/_git/www/pullrequest/908",
            ),
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-website",
                project_name="Website",
                repo_id="repo-www",
                repo_name="www",
                pr_id=881,
                title="Fix cookie banner contrast",
                created_by="Maya Patel",
                created_at=ago(6, 2),
                updated_at=ago(2, 4),
                source_branch="fix/cookie-contrast",
                target_branch="main",
                reviewer_count=2,
                url="https://dev.azure.com/contoso/Website/_git/www/pullrequest/881",
            ),
            DevOpsPullRequest(
                connection_id=connection.id,
                ado_project_id="ado-website",
                project_name="Website",
                repo_id="repo-www",
                repo_name="www",
                pr_id=860,
                title="Migrate image CDN to Front Door",
                created_by="Sam Okonkwo",
                created_at=ago(15, 0),
                updated_at=ago(3, 0),
                source_branch="feat/frontdoor-cdn",
                target_branch="main",
                reviewer_count=1,
                url="https://dev.azure.com/contoso/Website/_git/www/pullrequest/860",
            ),
        ]
    )
    session.add_all(
        [
            DevOpsStaleBranch(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                repo_id="repo-looking-glass",
                repo_name="looking-glass",
                branch_name="feature/old-auth",
                last_commit_at=ago(87),
                last_commit_by="Maya Patel",
                days_stale=87,
                url="https://dev.azure.com/contoso/Platform/_git/looking-glass?version=GBfeature/old-auth",
            ),
            DevOpsStaleBranch(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                repo_id="repo-looking-glass",
                repo_name="looking-glass",
                branch_name="spike/cost-export",
                last_commit_at=ago(45),
                last_commit_by="Avery Chen",
                days_stale=45,
                url="https://dev.azure.com/contoso/Platform/_git/looking-glass?version=GBspike/cost-export",
            ),
            DevOpsStaleBranch(
                connection_id=connection.id,
                ado_project_id="ado-website",
                project_name="Website",
                repo_id="repo-www",
                repo_name="www",
                branch_name="hotfix/banner-2024",
                last_commit_at=ago(120),
                last_commit_by="Jordan Lee",
                days_stale=120,
                url="https://dev.azure.com/contoso/Website/_git/www?version=GBhotfix/banner-2024",
            ),
            DevOpsStaleBranch(
                connection_id=connection.id,
                ado_project_id="ado-payments",
                project_name="Payments",
                repo_id="repo-ledger",
                repo_name="ledger",
                branch_name="experiment/double-entry",
                last_commit_at=ago(62),
                last_commit_by="Priya Shah",
                days_stale=62,
                url="https://dev.azure.com/contoso/Payments/_git/ledger?version=GBexperiment/double-entry",
            ),
        ]
    )
    session.add_all(
        [
            DevOpsPipelineAlert(
                connection_id=connection.id,
                ado_project_id="ado-platform",
                project_name="Platform",
                pipeline_id=77,
                pipeline_name="deploy-api",
                consecutive_failures=5,
                failure_count=5,
                run_count=8,
                failure_rate=0.625,
                reason="consecutive",
                last_result="failed",
                last_run_at=ago(0, 2),
                last_run_url="https://dev.azure.com/contoso/Platform/_build/results?buildId=9101",
                url="https://dev.azure.com/contoso/Platform/_build?definitionId=77",
                recent_results=[
                    {"id": 9101, "result": "failed", "buildNumber": "2026.10.09.1"},
                    {"id": 9094, "result": "failed", "buildNumber": "2026.10.08.4"},
                    {"id": 9088, "result": "failed", "buildNumber": "2026.10.08.2"},
                    {"id": 9072, "result": "failed", "buildNumber": "2026.10.07.3"},
                    {"id": 9061, "result": "failed", "buildNumber": "2026.10.07.1"},
                    {"id": 9040, "result": "succeeded", "buildNumber": "2026.10.06.2"},
                ],
            ),
            DevOpsPipelineAlert(
                connection_id=connection.id,
                ado_project_id="ado-website",
                project_name="Website",
                pipeline_id=12,
                pipeline_name="www-ci",
                consecutive_failures=2,
                failure_count=6,
                run_count=8,
                failure_rate=0.75,
                reason="rate",
                last_result="failed",
                last_run_at=ago(0, 6),
                last_run_url="https://dev.azure.com/contoso/Website/_build/results?buildId=4402",
                url="https://dev.azure.com/contoso/Website/_build?definitionId=12",
                recent_results=[
                    {"id": 4402, "result": "failed", "buildNumber": "4402"},
                    {"id": 4398, "result": "failed", "buildNumber": "4398"},
                    {"id": 4391, "result": "succeeded", "buildNumber": "4391"},
                    {"id": 4384, "result": "failed", "buildNumber": "4384"},
                    {"id": 4377, "result": "failed", "buildNumber": "4377"},
                    {"id": 4370, "result": "failed", "buildNumber": "4370"},
                    {"id": 4362, "result": "succeeded", "buildNumber": "4362"},
                    {"id": 4355, "result": "failed", "buildNumber": "4355"},
                ],
            ),
            DevOpsPipelineAlert(
                connection_id=connection.id,
                ado_project_id="ado-payments",
                project_name="Payments",
                pipeline_id=5,
                pipeline_name="ledger-release",
                consecutive_failures=3,
                failure_count=3,
                run_count=5,
                failure_rate=0.6,
                reason="consecutive",
                last_result="failed",
                last_run_at=ago(1, 3),
                last_run_url="https://dev.azure.com/contoso/Payments/_build/results?buildId=221",
                url="https://dev.azure.com/contoso/Payments/_build?definitionId=5",
                recent_results=[
                    {"id": 221, "result": "failed", "buildNumber": "221"},
                    {"id": 218, "result": "failed", "buildNumber": "218"},
                    {"id": 214, "result": "failed", "buildNumber": "214"},
                    {"id": 210, "result": "succeeded", "buildNumber": "210"},
                    {"id": 206, "result": "succeeded", "buildNumber": "206"},
                ],
            ),
        ]
    )
    await session.commit()


async def ensure_iam(session: AsyncSession) -> None:
    """Backfill the Platform Admins group and migrate raw privileges onto roles."""
    await ensure_break_glass_user(session)
    await _purge_demo_personas(session)

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
    await _ensure_demo_devops_read(session)
    await session.commit()


async def _purge_demo_personas(session: AsyncSession) -> None:
    """Remove leftover demo login accounts from earlier builds."""
    await _reassign_demo_dashboards(session)
    rows = (
        await session.execute(select(User).where(User.entra_oid.in_(DEMO_PERSONA_OIDS)))
    ).scalars().all()
    for user in rows:
        if user.entra_oid == BREAK_GLASS_OID:
            continue
        await session.delete(user)


async def _reassign_demo_dashboards(session: AsyncSession) -> None:
    admin = (
        await session.execute(select(User).where(User.entra_oid == BREAK_GLASS_OID))
    ).scalar_one_or_none()
    if admin is None:
        return
    owners = (
        await session.execute(select(User.id).where(User.entra_oid.in_(DEMO_PERSONA_OIDS)))
    ).scalars().all()
    if not owners:
        return
    dashboards = (
        await session.execute(select(Dashboard).where(Dashboard.owner_user_id.in_(owners)))
    ).scalars().all()
    for dashboard in dashboards:
        dashboard.owner_user_id = admin.id


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


async def _ensure_demo_devops_read(session: AsyncSession) -> None:
    """Grant devops.read to roles that already hold the original FinOps bundle."""
    cost_bundle = set(DEMO_COST_KEYS) - {"devops.read"}
    roles = (
        await session.execute(select(AccessRole).options(selectinload(AccessRole.privilege_grants)))
    ).scalars().all()
    for role in roles:
        keys = {row.privilege_key for row in role.privilege_grants}
        if "devops.read" in keys or not cost_bundle.issubset(keys):
            continue
        session.add(RolePrivilege(role_id=role.id, privilege_key="devops.read"))


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
