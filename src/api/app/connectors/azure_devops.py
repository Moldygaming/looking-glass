"""Azure DevOps health connector.

Uses a personal access token against the organisation REST API to list
projects, active pull requests, stale git branches, and failing pipelines.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger("looking-glass.azure-devops")
API = "7.1"
DEFAULT_STALE_DAYS = 30
DEFAULT_PIPELINE_LOOKBACK = 8
DEFAULT_FAIL_CONSECUTIVE = 3
DEFAULT_FAIL_RATE = 0.75
BUILD_WINDOW_DAYS = 45


class AzureDevOpsError(RuntimeError):
    pass


@dataclass
class AdoProject:
    id: str
    name: str
    description: str = ""
    url: str = ""
    state: str = "wellFormed"


@dataclass
class AdoPullRequest:
    project_id: str
    project_name: str
    repo_id: str
    repo_name: str
    pr_id: int
    title: str
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source_branch: str = ""
    target_branch: str = ""
    is_draft: bool = False
    reviewer_count: int = 0
    url: str = ""


@dataclass
class AdoStaleBranch:
    project_id: str
    project_name: str
    repo_id: str
    repo_name: str
    branch_name: str
    last_commit_at: datetime | None = None
    last_commit_by: str = ""
    days_stale: int = 0
    url: str = ""


@dataclass
class AdoPipelineAlert:
    project_id: str
    project_name: str
    pipeline_id: int
    pipeline_name: str
    consecutive_failures: int = 0
    failure_count: int = 0
    run_count: int = 0
    failure_rate: float = 0
    reason: str = "consecutive"
    last_result: str = ""
    last_run_at: datetime | None = None
    last_run_url: str = ""
    url: str = ""
    recent_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AdoHealthSnapshot:
    projects: list[AdoProject]
    pull_requests: list[AdoPullRequest]
    stale_branches: list[AdoStaleBranch]
    pipeline_alerts: list[AdoPipelineAlert]


def parse_organization(config: dict[str, Any]) -> tuple[str, str]:
    raw_org = str(config.get("organization") or "").strip().strip("/")
    raw_url = str(config.get("organization_url") or "").strip().rstrip("/")
    if raw_org.startswith("http"):
        raw_url = raw_org.rstrip("/")
        raw_org = raw_url.rsplit("/", 1)[-1]
    if raw_url:
        stripped = raw_url.replace("https://", "").replace("http://", "")
        parts = [p for p in stripped.split("/") if p]
        if parts and "dev.azure.com" in parts[0] and len(parts) >= 2:
            raw_org = parts[1]
            return raw_org, f"https://dev.azure.com/{raw_org}"
        return raw_org or (parts[-1] if parts else ""), raw_url
    if not raw_org:
        raise AzureDevOpsError("Azure DevOps organisation name is required.")
    return raw_org, f"https://dev.azure.com/{raw_org}"


def thresholds(config: dict[str, Any]) -> dict[str, Any]:
    stale_days = max(int(config.get("stale_days") or DEFAULT_STALE_DAYS), 1)
    lookback = max(int(config.get("pipeline_lookback") or DEFAULT_PIPELINE_LOOKBACK), 3)
    consecutive = max(int(config.get("fail_consecutive") or DEFAULT_FAIL_CONSECUTIVE), 2)
    rate_raw = config.get("fail_rate")
    if rate_raw is None:
        rate = DEFAULT_FAIL_RATE
    else:
        rate = float(rate_raw)
        if rate > 1:
            rate = rate / 100
    rate = min(max(rate, 0.5), 1)
    return {
        "stale_days": stale_days,
        "pipeline_lookback": lookback,
        "fail_consecutive": consecutive,
        "fail_rate": rate,
    }


def days_since(when: datetime | None, now: datetime) -> int | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, int((now - when).total_seconds() // 86400))


def is_stale_branch(
    *,
    last_commit_at: datetime | None,
    now: datetime,
    stale_days: int,
    is_default: bool,
) -> bool:
    if is_default or last_commit_at is None:
        return False
    age = days_since(last_commit_at, now)
    return age is not None and age >= stale_days


def is_failed_result(result: str | None) -> bool:
    return (result or "").lower() in {"failed", "partiallysucceeded"}


def evaluate_pipeline(
    runs: list[dict[str, Any]],
    *,
    consecutive_threshold: int,
    fail_rate: float,
    lookback: int,
) -> dict[str, Any] | None:
    """`runs` newest first. Returns alert facts or None."""
    completed: list[dict[str, Any]] = []
    for run in runs:
        status = (run.get("status") or "").lower()
        result = (run.get("result") or "").lower()
        if status and status not in {"completed", ""}:
            continue
        if result in {"canceled", "cancelled", "skipped", "none", ""}:
            continue
        completed.append(run)
        if len(completed) >= lookback:
            break
    if len(completed) < consecutive_threshold:
        return None
    consecutive = 0
    for run in completed:
        if is_failed_result(run.get("result")):
            consecutive += 1
        else:
            break
    fails = sum(1 for run in completed if is_failed_result(run.get("result")))
    rate = fails / len(completed)
    if consecutive >= consecutive_threshold:
        reason = "consecutive"
    elif rate >= fail_rate:
        reason = "rate"
    else:
        return None
    return {
        "consecutive_failures": consecutive,
        "failure_count": fails,
        "run_count": len(completed),
        "failure_rate": round(rate, 3),
        "reason": reason,
        "last_result": completed[0].get("result") or "",
        "last_run_at": _parse_dt(completed[0].get("finishTime") or completed[0].get("queueTime")),
        "last_run_url": _web_link(completed[0]) or str(completed[0].get("url") or ""),
        "recent_results": [
            {
                "id": run.get("id"),
                "result": run.get("result"),
                "finishTime": run.get("finishTime"),
                "buildNumber": run.get("buildNumber") or run.get("name"),
            }
            for run in completed
        ],
    }


def short_ref(ref: str | None) -> str:
    value = ref or ""
    for prefix in ("refs/heads/", "refs/pull/", "refs/tags/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


class AzureDevOpsConnector:
    provider = "azure_devops"

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        org, base = parse_organization(config)
        if not secret:
            raise AzureDevOpsError("A personal access token is required.")
        async with httpx.AsyncClient(timeout=30, auth=httpx.BasicAuth("", secret)) as client:
            projects = await _get_list(client, f"{base}/_apis/projects", {"$top": 1, "api-version": API})
        return f"Authenticated to {org}. {len(projects)} project{'s' if len(projects) != 1 else ''} visible on the first page."

    async def list_projects(self, config: dict[str, Any], secret: str | None) -> list[AdoProject]:
        org, base = parse_organization(config)
        if not secret:
            raise AzureDevOpsError("A personal access token is required.")
        async with httpx.AsyncClient(timeout=60, auth=httpx.BasicAuth("", secret)) as client:
            rows = await _get_list(
                client,
                f"{base}/_apis/projects",
                {"$top": 100, "stateFilter": "wellFormed", "api-version": API},
            )
        return [_project(row, org, base) for row in rows]

    async def scan(
        self,
        config: dict[str, Any],
        secret: str | None,
        projects: list[AdoProject],
    ) -> AdoHealthSnapshot:
        org, base = parse_organization(config)
        if not secret:
            raise AzureDevOpsError("A personal access token is required.")
        if not projects:
            return AdoHealthSnapshot(projects=[], pull_requests=[], stale_branches=[], pipeline_alerts=[])
        limits = thresholds(config)
        now = datetime.now(UTC)
        pull_requests: list[AdoPullRequest] = []
        stale_branches: list[AdoStaleBranch] = []
        pipeline_alerts: list[AdoPipelineAlert] = []
        async with httpx.AsyncClient(timeout=90, auth=httpx.BasicAuth("", secret)) as client:
            for project in projects:
                pull_requests.extend(await _project_pull_requests(client, base, org, project))
                stale_branches.extend(
                    await _project_stale_branches(client, base, org, project, now, limits["stale_days"])
                )
                pipeline_alerts.extend(await _project_pipeline_alerts(client, base, org, project, now, limits))
        return AdoHealthSnapshot(
            projects=projects,
            pull_requests=pull_requests,
            stale_branches=stale_branches,
            pipeline_alerts=pipeline_alerts,
        )


def _project(row: dict[str, Any], org: str, base: str) -> AdoProject:
    name = str(row.get("name") or "")
    web = _web_link(row) or f"{base}/{quote(name)}"
    return AdoProject(
        id=str(row.get("id") or ""),
        name=name,
        description=str(row.get("description") or ""),
        url=web,
        state=str(row.get("state") or "wellFormed"),
    )


async def _project_pull_requests(
    client: httpx.AsyncClient, base: str, org: str, project: AdoProject
) -> list[AdoPullRequest]:
    encoded = quote(project.name)
    rows = await _get_list(
        client,
        f"{base}/{encoded}/_apis/git/pullrequests",
        {"searchCriteria.status": "active", "$top": 100, "api-version": API},
    )
    items: list[AdoPullRequest] = []
    for row in rows:
        repo = row.get("repository") or {}
        repo_name = str(repo.get("name") or "")
        repo_id = str(repo.get("id") or "")
        pr_id = int(row.get("pullRequestId") or 0)
        created_by = ((row.get("createdBy") or {}).get("displayName")) or ""
        items.append(
            AdoPullRequest(
                project_id=project.id,
                project_name=project.name,
                repo_id=repo_id,
                repo_name=repo_name,
                pr_id=pr_id,
                title=str(row.get("title") or f"PR {pr_id}"),
                created_by=str(created_by),
                created_at=_parse_dt(row.get("creationDate")),
                updated_at=_parse_dt(row.get("closedDate") or row.get("creationDate")),
                source_branch=short_ref(row.get("sourceRefName")),
                target_branch=short_ref(row.get("targetRefName")),
                is_draft=bool(row.get("isDraft")),
                reviewer_count=len(row.get("reviewers") or []),
                url=_web_link(row) or f"{base}/{encoded}/_git/{quote(repo_name)}/pullrequest/{pr_id}",
            )
        )
    return items


async def _project_stale_branches(
    client: httpx.AsyncClient,
    base: str,
    org: str,
    project: AdoProject,
    now: datetime,
    stale_days: int,
) -> list[AdoStaleBranch]:
    encoded = quote(project.name)
    repos = await _get_list(
        client,
        f"{base}/{encoded}/_apis/git/repositories",
        {"api-version": API},
    )
    stale: list[AdoStaleBranch] = []
    for repo in repos:
        if (repo.get("isDisabled") is True) or str(repo.get("project", {}).get("state") or "") == "deleted":
            continue
        repo_id = str(repo.get("id") or "")
        repo_name = str(repo.get("name") or "")
        default_branch = short_ref(repo.get("defaultBranch"))
        try:
            stats = await _get_list(
                client,
                f"{base}/{encoded}/_apis/git/repositories/{repo_id}/stats/branches",
                {"api-version": API},
            )
        except AzureDevOpsError as exc:
            log.warning("branch stats failed for %s/%s: %s", project.name, repo_name, exc)
            continue
        for stat in stats:
            name = short_ref(stat.get("name"))
            if not name:
                continue
            commit = stat.get("commit") or {}
            committer = commit.get("committer") or commit.get("author") or {}
            last_commit_at = _parse_dt(committer.get("date") or commit.get("author", {}).get("date"))
            is_default = bool(stat.get("isBaseVersion")) or name == default_branch
            if not is_stale_branch(
                last_commit_at=last_commit_at, now=now, stale_days=stale_days, is_default=is_default
            ):
                continue
            stale.append(
                AdoStaleBranch(
                    project_id=project.id,
                    project_name=project.name,
                    repo_id=repo_id,
                    repo_name=repo_name,
                    branch_name=name,
                    last_commit_at=last_commit_at,
                    last_commit_by=str(committer.get("name") or ""),
                    days_stale=days_since(last_commit_at, now) or 0,
                    url=f"{base}/{encoded}/_git/{quote(repo_name)}?version=GB{quote(name)}",
                )
            )
    return stale


async def _project_pipeline_alerts(
    client: httpx.AsyncClient,
    base: str,
    org: str,
    project: AdoProject,
    now: datetime,
    limits: dict[str, Any],
) -> list[AdoPipelineAlert]:
    encoded = quote(project.name)
    since = (now - timedelta(days=BUILD_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        definitions = await _get_list(
            client,
            f"{base}/{encoded}/_apis/build/definitions",
            {"$top": 200, "queryOrder": "lastModifiedDescending", "api-version": API},
        )
        builds = await _get_list(
            client,
            f"{base}/{encoded}/_apis/build/builds",
            {
                "$top": 200,
                "minTime": since,
                "queryOrder": "finishTimeDescending",
                "api-version": API,
            },
        )
    except AzureDevOpsError as exc:
        log.warning("pipeline query failed for %s: %s", project.name, exc)
        return []
    by_def: dict[int, list[dict[str, Any]]] = {}
    for build in builds:
        definition = build.get("definition") or {}
        def_id = definition.get("id")
        if def_id is None:
            continue
        by_def.setdefault(int(def_id), []).append(build)
    names = {int(row["id"]): str(row.get("name") or f"Pipeline {row['id']}") for row in definitions if row.get("id") is not None}
    alerts: list[AdoPipelineAlert] = []
    for def_id, runs in by_def.items():
        facts = evaluate_pipeline(
            runs,
            consecutive_threshold=limits["fail_consecutive"],
            fail_rate=limits["fail_rate"],
            lookback=limits["pipeline_lookback"],
        )
        if facts is None:
            continue
        name = names.get(def_id) or ((runs[0].get("definition") or {}).get("name")) or f"Pipeline {def_id}"
        alerts.append(
            AdoPipelineAlert(
                project_id=project.id,
                project_name=project.name,
                pipeline_id=def_id,
                pipeline_name=str(name),
                consecutive_failures=int(facts["consecutive_failures"]),
                failure_count=int(facts["failure_count"]),
                run_count=int(facts["run_count"]),
                failure_rate=float(facts["failure_rate"]),
                reason=str(facts["reason"]),
                last_result=str(facts["last_result"]),
                last_run_at=facts.get("last_run_at"),
                last_run_url=str(facts.get("last_run_url") or ""),
                url=f"{base}/{encoded}/_build?definitionId={def_id}",
                recent_results=list(facts.get("recent_results") or []),
            )
        )
    return alerts


async def _get_list(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    query = dict(params)
    while True:
        payload = await _get(client, url, query)
        items.extend(payload.get("value") or [])
        token = payload.get("continuationToken")
        if not token:
            break
        query = {**params, "continuationToken": token}
        if len(items) >= 2000:
            break
    return items


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    last_error = "Azure DevOps request failed."
    for attempt in range(4):
        response = await client.get(url, params=params)
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After") or min(8 * (attempt + 1), 30))
            log.warning("Azure DevOps 429 on %s — waiting %ss", url, wait)
            await _sleep(wait)
            continue
        if response.status_code in {401, 403}:
            raise AzureDevOpsError(
                "Azure DevOps rejected the token. Grant the PAT Code (Read), Build (Read), "
                "and Project and team (Read), and check the organisation name."
            )
        if response.status_code >= 400:
            last_error = _error_message(response)
            if response.status_code >= 500 and attempt < 3:
                await _sleep(min(4 * (attempt + 1), 15))
                continue
            raise AzureDevOpsError(last_error)
        data = response.json()
        token = response.headers.get("x-ms-continuationtoken")
        if token and isinstance(data, dict) and not data.get("continuationToken"):
            data["continuationToken"] = token
        return data if isinstance(data, dict) else {"value": data}
    raise AzureDevOpsError(last_error)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        message = body.get("message") or body.get("typeKey") or body
        return f"Azure DevOps {response.status_code}: {message}"
    except Exception:  # noqa: BLE001
        text = (response.text or "")[:400]
        return f"Azure DevOps {response.status_code}: {text or response.reason_phrase}"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _web_link(row: dict[str, Any]) -> str:
    links = row.get("_links") or {}
    web = links.get("web") or links.get("self") or {}
    return str(web.get("href") or "")


async def _sleep(seconds: int) -> None:
    await asyncio.sleep(seconds)
