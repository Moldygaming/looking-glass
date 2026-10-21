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

from app.services.service_records import ServiceRecord

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

    async def list_work_items(
        self,
        config: dict[str, Any],
        secret: str | None,
        project_name: str,
        project_id: str = "",
    ) -> list[ServiceRecord]:
        _, base = parse_organization(config)
        if not secret:
            raise AzureDevOpsError("A personal access token is required.")
        name = project_name.strip()
        if not name and not project_id.strip():
            raise AzureDevOpsError("Choose an Azure DevOps project before syncing work items.")
        # The project id is a GUID and does not need escaping. @project is scoped by that URL.
        segment = quote((project_id or name).strip(), safe="-")
        params = {"api-version": API, "$top": work_item_top()}
        async with httpx.AsyncClient(timeout=60, auth=httpx.BasicAuth("", secret)) as client:
            payload = await _post(
                client,
                f"{base}/{segment}/_apis/wit/wiql",
                params,
                {"query": work_item_wiql()},
            )
            ids = _work_item_ids(payload)
            if not ids:
                return []
            batch = await _post_work_items(client, base, ids)
        records: list[ServiceRecord] = []
        for row in batch.get("value") or []:
            if not isinstance(row, dict):
                continue
            record = normalize_work_item(row, org_url=base, project_name=name or project_id)
            if record is not None:
                records.append(record)
        return records


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


def _auth_message(auth_hint: str) -> str:
    if auth_hint == "work_items":
        return (
            "Azure DevOps rejected the token. Grant the PAT Work Items (Read) "
            "and Project and team (Read), and check the organisation name."
        )
    return (
        "Azure DevOps rejected the token. Grant the PAT Code (Read), Build (Read), "
        "and Project and team (Read), and check the organisation name."
    )


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    return await _request(client, "GET", url, params)


async def _post(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    body: dict[str, Any],
    *,
    attempts: int = 2,
) -> dict[str, Any]:
    return await _request(
        client, "POST", url, params, body, auth_hint="work_items", attempts=attempts, quick=True
    )


async def _post_work_items(client: httpx.AsyncClient, base: str, ids: list[int]) -> dict[str, Any]:
    url = f"{base}/_apis/wit/workitemsbatch"
    params = {"api-version": API}
    try:
        return await _post(client, url, params, {"ids": ids, "fields": list(WORK_ITEM_FIELDS)})
    except AzureDevOpsError as exc:
        text = str(exc)
        if "Priority" not in text and "TF51535" not in text:
            raise
        return await _post(
            client,
            url,
            params,
            {"ids": ids, "fields": [field for field in WORK_ITEM_FIELDS if field != "Microsoft.VSTS.Common.Priority"]},
        )


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    params: dict[str, Any],
    body: dict[str, Any] | None = None,
    auth_hint: str = "default",
    attempts: int = 4,
    quick: bool = False,
) -> dict[str, Any]:
    last_error = "Azure DevOps request failed."
    total = max(1, attempts)
    for attempt in range(total):
        if method == "POST":
            response = await client.post(url, params=params, json=body)
        else:
            response = await client.get(url, params=params)
        if response.status_code == 429:
            default_wait = 2 if quick else min(8 * (attempt + 1), 30)
            wait = int(response.headers.get("Retry-After") or default_wait)
            if quick:
                wait = min(wait, 4)
            log.warning("Azure DevOps 429 on %s — waiting %ss", url, wait)
            await _sleep(wait)
            continue
        if response.status_code in {401, 403}:
            raise AzureDevOpsError(_auth_message(auth_hint))
        if response.status_code >= 400:
            last_error = _error_message(response)
            # Work-item calls retry once, briefly. A long sleep outlasts the portal
            # timeout and the user only sees a generic failure.
            if response.status_code >= 500 and attempt + 1 < total:
                await _sleep(2 if quick else min(4 * (attempt + 1), 15))
                continue
            raise AzureDevOpsError(last_error)
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise AzureDevOpsError(f"Azure DevOps returned a response that was not JSON ({response.status_code}).") from exc
        token = response.headers.get("x-ms-continuationtoken")
        if token and isinstance(data, dict) and not data.get("continuationToken"):
            data["continuationToken"] = token
        return data if isinstance(data, dict) else {"value": data}
    raise AzureDevOpsError(last_error)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("message") or body.get("typeKey") or ""
            inner = body.get("innerException")
            if isinstance(inner, dict) and inner.get("message"):
                message = f"{message} {inner.get('message')}".strip()
            message = message or body
        else:
            message = body
        return f"Azure DevOps {response.status_code}: {message}"[:500]
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


WORK_ITEM_LIMIT = 200
WORK_ITEM_FIELDS = (
    "System.Id",
    "System.Title",
    "System.WorkItemType",
    "System.State",
    "System.AssignedTo",
    "System.ChangedDate",
    "System.CreatedDate",
    "Microsoft.VSTS.Common.Priority",
    "System.TeamProject",
)
CLOSED_WORK_ITEM_STATES = {"closed", "removed", "done", "completed"}


def escape_wiql_literal(value: str) -> str:
    return value.replace("'", "''")


def work_item_top(limit: int = WORK_ITEM_LIMIT) -> int:
    return max(1, min(int(limit), WORK_ITEM_LIMIT))


def work_item_wiql(project_name: str | None = None) -> str:
    """Flat work-item query.

    The REST API applies the row cap with the $top query parameter. SELECT TOP
    inside the WIQL text is not that cap, and a project-wide query without $top
    fails once the project is large. @project is filled from the project in the URL.
    """
    if project_name:
        project = f"'{escape_wiql_literal(project_name)}'"
    else:
        project = "@project"
    return (
        "SELECT [System.Id] FROM WorkItems "
        f"WHERE [System.TeamProject] = {project} "
        "AND [System.State] <> 'Removed' "
        "ORDER BY [System.ChangedDate] DESC"
    )


def work_item_is_open(state: str) -> bool:
    return state.strip().lower() not in CLOSED_WORK_ITEM_STATES


def _work_item_ids(payload: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for row in payload.get("workItems") or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        try:
            ids.append(int(row["id"]))
        except (TypeError, ValueError):
            continue
        if len(ids) >= WORK_ITEM_LIMIT:
            break
    return ids


def _identity_parts(value: Any) -> tuple[str, str]:
    """UPN plus the same address for matching.

    uniqueName is the Entra user principal name when the identity is backed by
    a directory. Display name is used only when Azure DevOps did not send an
    address, such as DOMAIN\\user.
    """
    if isinstance(value, dict):
        email = _email_text(value.get("uniqueName")) or _email_text(value.get("mail"))
        display = str(value.get("displayName") or "").strip()
        identity = email or display or str(value.get("uniqueName") or "").strip()
        return identity, email
    text = "" if value is None else str(value).strip()
    if "<" in text and text.endswith(">"):
        name, _, rest = text.rpartition("<")
        email = _email_text(rest[:-1])
        return email or name.strip() or text, email
    email = _email_text(text)
    return (email or text), email


def _email_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text or "@" not in text or any(ch.isspace() for ch in text):
        return ""
    if text.lower().startswith("vstfs:"):
        return ""
    local, _, domain = text.partition("@")
    if not local or "." not in domain or any(ch in text for ch in "<>"):
        return ""
    return text


def normalize_work_item(raw: dict[str, Any], *, org_url: str, project_name: str) -> ServiceRecord | None:
    fields = raw.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    item_id = raw.get("id")
    if item_id is None:
        item_id = fields.get("System.Id")
    if item_id is None:
        return None
    project = str(fields.get("System.TeamProject") or project_name or "").strip()
    state = str(fields.get("System.State") or "")
    priority = fields.get("Microsoft.VSTS.Common.Priority")
    title = str(fields.get("System.Title") or f"Work item {item_id}")
    encoded = quote(project or project_name, safe="")
    assignee, assignee_email = _identity_parts(fields.get("System.AssignedTo"))
    return ServiceRecord(
        source="azure_devops",
        kind="work_item",
        external_id=str(item_id),
        title=title,
        item_type=str(fields.get("System.WorkItemType") or "Work item"),
        state=state,
        priority="" if priority is None else str(priority),
        assignee=assignee,
        assignee_email=assignee_email,
        project_name=project or project_name,
        url=f"{org_url.rstrip('/')}/{encoded}/_workitems/edit/{item_id}",
        is_open=work_item_is_open(state),
        opened_at=_parse_dt(fields.get("System.CreatedDate")),
        updated_at=_parse_dt(fields.get("System.ChangedDate")),
    )


def _web_link(row: dict[str, Any]) -> str:
    links = row.get("_links") or {}
    web = links.get("web") or links.get("self") or {}
    return str(web.get("href") or "")


async def _sleep(seconds: int) -> None:
    await asyncio.sleep(seconds)
