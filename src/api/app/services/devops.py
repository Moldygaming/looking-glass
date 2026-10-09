"""Persist Azure DevOps health snapshots and assemble the report dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.azure_devops import (
    AdoProject,
    AzureDevOpsConnector,
    AzureDevOpsError,
    days_since,
    parse_organization,
    thresholds,
)
from app.connectors.registry import connector_secret, credentials_configured, public_config
from app.models import (
    Connection,
    DevOpsPipelineAlert,
    DevOpsProject,
    DevOpsPullRequest,
    DevOpsStaleBranch,
)
from app.schemas import (
    DevOpsPipelineAlertOut,
    DevOpsProjectOut,
    DevOpsPullRequestOut,
    DevOpsReportOut,
    DevOpsRepoPullRequestsOut,
    DevOpsRepoStaleBranchesOut,
    DevOpsScanOut,
    DevOpsStaleBranchOut,
    DevOpsSummaryOut,
    DevOpsThresholdsOut,
)

ADO = AzureDevOpsConnector()


async def list_ado_connections(session: AsyncSession) -> list[Connection]:
    rows = (
        await session.execute(
            select(Connection).where(Connection.provider == "azure_devops").order_by(Connection.name)
        )
    ).scalars().all()
    return list(rows)


async def refresh_projects(session: AsyncSession, connection_id: UUID) -> list[DevOpsProject]:
    connection = await _connection(session, connection_id)
    _require_credentials(connection)
    listed = await ADO.list_projects(public_config(connection.config or {}), connector_secret(connection))
    existing = {
        row.ado_project_id: row
        for row in (
            await session.execute(select(DevOpsProject).where(DevOpsProject.connection_id == connection_id))
        ).scalars()
    }
    seen: set[str] = set()
    for item in listed:
        seen.add(item.id)
        row = existing.get(item.id)
        if row is None:
            row = DevOpsProject(
                connection_id=connection_id,
                ado_project_id=item.id,
                name=item.name,
                description=item.description,
                url=item.url,
                state=item.state,
                monitored=False,
            )
            session.add(row)
        else:
            row.name = item.name
            row.description = item.description
            row.url = item.url
            row.state = item.state
    for ado_id, row in existing.items():
        if ado_id not in seen:
            row.state = "missing"
    connection.last_error = None
    if connection.status == "pending":
        connection.status = "ready"
    await session.commit()
    return await _projects(session, connection_id)


async def set_monitored_projects(
    session: AsyncSession, connection_id: UUID, project_ids: list[str]
) -> list[DevOpsProject]:
    connection = await _connection(session, connection_id)
    wanted = {item.strip() for item in project_ids if item and item.strip()}
    rows = await _projects(session, connection_id)
    if not rows:
        rows = await refresh_projects(session, connection_id)
    for row in rows:
        row.monitored = row.ado_project_id in wanted
    config = dict(connection.config or {})
    config["monitored_project_ids"] = sorted(wanted)
    connection.config = config
    await session.commit()
    return await _projects(session, connection_id)


async def run_devops_scan(session: AsyncSession, connection_id: UUID) -> DevOpsScanOut:
    connection = await _connection(session, connection_id)
    _require_credentials(connection)
    rows = await _projects(session, connection_id)
    if not rows:
        rows = await refresh_projects(session, connection_id)
    monitored = [row for row in rows if row.monitored]
    if not monitored:
        raise AzureDevOpsError("Select at least one Azure DevOps project to monitor.")
    snapshot = await ADO.scan(
        public_config(connection.config or {}),
        connector_secret(connection),
        [
            AdoProject(
                id=row.ado_project_id,
                name=row.name,
                description=row.description,
                url=row.url,
                state=row.state,
            )
            for row in monitored
        ],
    )
    now = datetime.now(UTC)
    await session.execute(delete(DevOpsPullRequest).where(DevOpsPullRequest.connection_id == connection_id))
    await session.execute(delete(DevOpsStaleBranch).where(DevOpsStaleBranch.connection_id == connection_id))
    await session.execute(delete(DevOpsPipelineAlert).where(DevOpsPipelineAlert.connection_id == connection_id))
    for item in snapshot.pull_requests:
        session.add(
            DevOpsPullRequest(
                connection_id=connection_id,
                ado_project_id=item.project_id,
                project_name=item.project_name,
                repo_id=item.repo_id,
                repo_name=item.repo_name,
                pr_id=item.pr_id,
                title=item.title,
                created_by=item.created_by,
                created_at=item.created_at,
                updated_at=item.updated_at,
                source_branch=item.source_branch,
                target_branch=item.target_branch,
                is_draft=item.is_draft,
                reviewer_count=item.reviewer_count,
                url=item.url,
            )
        )
    for item in snapshot.stale_branches:
        session.add(
            DevOpsStaleBranch(
                connection_id=connection_id,
                ado_project_id=item.project_id,
                project_name=item.project_name,
                repo_id=item.repo_id,
                repo_name=item.repo_name,
                branch_name=item.branch_name,
                last_commit_at=item.last_commit_at,
                last_commit_by=item.last_commit_by,
                days_stale=item.days_stale,
                url=item.url,
            )
        )
    for item in snapshot.pipeline_alerts:
        session.add(
            DevOpsPipelineAlert(
                connection_id=connection_id,
                ado_project_id=item.project_id,
                project_name=item.project_name,
                pipeline_id=item.pipeline_id,
                pipeline_name=item.pipeline_name,
                consecutive_failures=item.consecutive_failures,
                failure_count=item.failure_count,
                run_count=item.run_count,
                failure_rate=item.failure_rate,
                reason=item.reason,
                last_result=item.last_result,
                last_run_at=item.last_run_at,
                last_run_url=item.last_run_url,
                url=item.url,
                recent_results=item.recent_results,
            )
        )
    monitored_ids = {row.ado_project_id for row in monitored}
    for row in rows:
        if row.ado_project_id in monitored_ids:
            row.last_scan_at = now
    connection.status = "connected"
    connection.last_error = None
    connection.last_ingest_at = now
    await session.commit()
    return DevOpsScanOut(
        connection_id=connection_id,
        projects=len(monitored),
        pull_requests=len(snapshot.pull_requests),
        stale_branches=len(snapshot.stale_branches),
        pipeline_alerts=len(snapshot.pipeline_alerts),
    )


async def build_report(session: AsyncSession, connection: Connection) -> DevOpsReportOut:
    now = datetime.now(UTC)
    limits = thresholds(connection.config or {})
    try:
        organization, _ = parse_organization(connection.config or {})
    except AzureDevOpsError:
        organization = str((connection.config or {}).get("organization") or "")
    projects = await _projects(session, connection.id)
    pull_requests = (
        await session.execute(
            select(DevOpsPullRequest)
            .where(DevOpsPullRequest.connection_id == connection.id)
            .order_by(DevOpsPullRequest.created_at.asc().nullslast())
        )
    ).scalars().all()
    stale_branches = (
        await session.execute(
            select(DevOpsStaleBranch)
            .where(DevOpsStaleBranch.connection_id == connection.id)
            .order_by(DevOpsStaleBranch.days_stale.desc())
        )
    ).scalars().all()
    alerts = (
        await session.execute(
            select(DevOpsPipelineAlert)
            .where(DevOpsPipelineAlert.connection_id == connection.id)
            .order_by(DevOpsPipelineAlert.consecutive_failures.desc(), DevOpsPipelineAlert.failure_rate.desc())
        )
    ).scalars().all()

    pr_out: list[DevOpsPullRequestOut] = []
    for row in pull_requests:
        pr_out.append(
            DevOpsPullRequestOut(
                id=row.id,
                ado_project_id=row.ado_project_id,
                project_name=row.project_name,
                repo_id=row.repo_id,
                repo_name=row.repo_name,
                pr_id=row.pr_id,
                title=row.title,
                created_by=row.created_by,
                created_at=row.created_at,
                updated_at=row.updated_at,
                source_branch=row.source_branch,
                target_branch=row.target_branch,
                is_draft=row.is_draft,
                reviewer_count=row.reviewer_count,
                url=row.url,
                age_days=days_since(row.created_at, now),
            )
        )
    repos_pr: dict[str, DevOpsRepoPullRequestsOut] = {}
    for item in pr_out:
        key = item.repo_id or f"{item.project_name}/{item.repo_name}"
        group = repos_pr.get(key)
        if group is None:
            group = DevOpsRepoPullRequestsOut(
                repo_id=item.repo_id,
                repo_name=item.repo_name,
                project_name=item.project_name,
                ado_project_id=item.ado_project_id,
                pr_count=0,
                oldest_age_days=item.age_days,
                url=_repo_url(item.url),
                pull_requests=[],
            )
            repos_pr[key] = group
        group.pull_requests.append(item)
        group.pr_count = len(group.pull_requests)
        if item.age_days is not None and (group.oldest_age_days is None or item.age_days > group.oldest_age_days):
            group.oldest_age_days = item.age_days

    stale_out = [
        DevOpsStaleBranchOut(
            id=row.id,
            ado_project_id=row.ado_project_id,
            project_name=row.project_name,
            repo_id=row.repo_id,
            repo_name=row.repo_name,
            branch_name=row.branch_name,
            last_commit_at=row.last_commit_at,
            last_commit_by=row.last_commit_by,
            days_stale=row.days_stale,
            url=row.url,
        )
        for row in stale_branches
    ]
    repos_stale: dict[str, DevOpsRepoStaleBranchesOut] = {}
    for item in stale_out:
        key = item.repo_id or f"{item.project_name}/{item.repo_name}"
        group = repos_stale.get(key)
        if group is None:
            group = DevOpsRepoStaleBranchesOut(
                repo_id=item.repo_id,
                repo_name=item.repo_name,
                project_name=item.project_name,
                ado_project_id=item.ado_project_id,
                branch_count=0,
                oldest_days=item.days_stale,
                url=_repo_url(item.url),
                branches=[],
            )
            repos_stale[key] = group
        group.branches.append(item)
        group.branch_count = len(group.branches)
        group.oldest_days = max(group.oldest_days, item.days_stale)

    alert_out = [
        DevOpsPipelineAlertOut(
            id=row.id,
            ado_project_id=row.ado_project_id,
            project_name=row.project_name,
            pipeline_id=row.pipeline_id,
            pipeline_name=row.pipeline_name,
            consecutive_failures=row.consecutive_failures,
            failure_count=row.failure_count,
            run_count=row.run_count,
            failure_rate=row.failure_rate,
            reason=row.reason,
            last_result=row.last_result,
            last_run_at=row.last_run_at,
            last_run_url=row.last_run_url,
            url=row.url,
            recent_results=row.recent_results or [],
        )
        for row in alerts
    ]

    project_out = [
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
        for row in projects
    ]
    monitored = [row for row in project_out if row.monitored]
    return DevOpsReportOut(
        connection_id=connection.id,
        connection_name=connection.name,
        organization=organization,
        status=connection.status,
        credentials_configured=credentials_configured(connection),
        last_scan_at=connection.last_ingest_at,
        last_error=connection.last_error,
        thresholds=DevOpsThresholdsOut(**limits),
        summary=DevOpsSummaryOut(
            projects=len(project_out),
            monitored=len(monitored),
            repositories_with_pull_requests=len(repos_pr),
            active_pull_requests=len(pr_out),
            repositories_with_stale_branches=len(repos_stale),
            stale_branches=len(stale_out),
            failing_pipelines=len(alert_out),
        ),
        projects=project_out,
        repositories_with_pull_requests=sorted(
            repos_pr.values(), key=lambda row: (-(row.oldest_age_days or 0), -row.pr_count, row.repo_name)
        ),
        repositories_with_stale_branches=sorted(
            repos_stale.values(), key=lambda row: (-row.oldest_days, -row.branch_count, row.repo_name)
        ),
        pipeline_alerts=alert_out,
    )


def _repo_url(item_url: str) -> str:
    if "/pullrequest/" in item_url:
        return item_url.split("/pullrequest/")[0]
    if "?version=" in item_url:
        return item_url.split("?version=")[0]
    return item_url


async def _projects(session: AsyncSession, connection_id: UUID) -> list[DevOpsProject]:
    return list(
        (
            await session.execute(
                select(DevOpsProject)
                .where(DevOpsProject.connection_id == connection_id)
                .order_by(DevOpsProject.name)
            )
        ).scalars()
    )


async def _connection(session: AsyncSession, connection_id: UUID) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None or connection.provider != "azure_devops":
        raise AzureDevOpsError("Azure DevOps connection not found.")
    return connection


def _require_credentials(connection: Connection) -> None:
    if not credentials_configured(connection):
        raise AzureDevOpsError("This connection is missing the organisation name or personal access token.")
