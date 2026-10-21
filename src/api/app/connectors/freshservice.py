"""Freshservice tickets, problems, and changes.

Auth is HTTP basic with the API key as the username and the literal password X.
The domain is a subdomain (acme) or a host (acme.freshservice.com).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.service_records import ServiceRecord

log = logging.getLogger("looking-glass.freshservice")

PAGE_SIZE = 100
MAX_PAGES = 5
AGENT_PAGES = 10
HYDRATE_LIMIT = 80
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.freshservice\.com$")

TICKET_STATUS = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
PROBLEM_STATUS = {1: "Open", 2: "Change Requested", 3: "Closed"}
CHANGE_STATUS = {
    1: "Open",
    2: "Planning",
    3: "Awaiting Approval",
    4: "Pending Release",
    5: "Pending Review",
    6: "Closed",
}
PRIORITY = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
CHANGE_TYPE = {1: "Minor", 2: "Standard", 3: "Major", 4: "Emergency"}
CLOSED_STATUS = {"ticket": {4, 5}, "problem": {3}, "change": {6}}
KINDS = ("ticket", "problem", "change")
_LIST_KEY = {"ticket": "tickets", "problem": "problems", "change": "changes"}


class FreshserviceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def parse_domain(config: dict[str, Any]) -> tuple[str, str]:
    raw = str(config.get("domain") or "").strip().lower()
    if not raw:
        raise FreshserviceError("Freshservice domain is required (for example acme or acme.freshservice.com).")
    raw = raw.removeprefix("https://").removeprefix("http://")
    host = raw.split("/")[0].strip().strip(".")
    if not host.endswith(".freshservice.com"):
        label = host.split(".")[0]
        host = f"{label}.freshservice.com"
    if not _HOST.match(host):
        raise FreshserviceError("Freshservice domain is required (for example acme or acme.freshservice.com).")
    return host.split(".")[0], f"https://{host}"


def status_label(kind: str, code: Any) -> str:
    number = _as_int(code)
    table = {"ticket": TICKET_STATUS, "problem": PROBLEM_STATUS, "change": CHANGE_STATUS}.get(kind, {})
    if number is None:
        return "" if code in (None, "") else str(code)
    return table.get(number, f"Status {number}")


def priority_label(code: Any) -> str:
    number = _as_int(code)
    if number is None:
        return "" if code in (None, "") else str(code)
    return PRIORITY.get(number, str(number))


def record_is_open(kind: str, code: Any) -> bool:
    number = _as_int(code)
    if number is None:
        return True
    return number not in CLOSED_STATUS.get(kind, set())


def skip_missing_module(kind: str, status: int | None) -> bool:
    return kind in {"problem", "change"} and status in {403, 404}


def normalize_record(
    kind: str,
    row: dict[str, Any],
    base_url: str,
    agents: dict[int, tuple[str, str]] | None = None,
) -> ServiceRecord | None:
    item_id = row.get("id")
    if item_id is None:
        return None
    status = row.get("status")
    people = agents or {}
    requester, _requester_email = _linked_person(row.get("requester"), row.get("requester_id"), people)
    assignee, assignee_email = _assignee(kind, row, people)
    if assignee_email:
        assignee = assignee_email
    return ServiceRecord(
        source="freshservice",
        kind=kind,
        external_id=str(item_id),
        title=str(row.get("subject") or row.get("title") or f"{kind} {item_id}"),
        item_type=_item_type(kind, row),
        state=status_label(kind, status),
        status_code="" if status is None else str(status),
        priority=priority_label(row.get("priority")),
        assignee=assignee,
        assignee_email=assignee_email,
        requester=requester,
        url=f"{base_url.rstrip('/')}/a/{_LIST_KEY[kind]}/{item_id}",
        is_open=record_is_open(kind, status),
        opened_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


class FreshserviceConnector:
    provider = "freshservice"

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        label, base = parse_domain(config)
        if not secret:
            raise FreshserviceError("A Freshservice API key is required.")
        async with _client(secret) as client:
            await _get(client, f"{base}/api/v2/tickets", {"page": 1, "per_page": 1})
        return f"Authenticated to {label}.freshservice.com."

    async def list_records(self, config: dict[str, Any], secret: str | None) -> tuple[list[ServiceRecord], list[str]]:
        _, base = parse_domain(config)
        if not secret:
            raise FreshserviceError("A Freshservice API key is required.")
        async with _client(secret) as client:
            people = await _load_people(client, base)
            collected: list[tuple[str, dict[str, Any]]] = []
            for kind in KINDS:
                try:
                    rows = await _list_kind(client, base, kind)
                except FreshserviceError as exc:
                    if skip_missing_module(kind, exc.status):
                        log.info("Freshservice %s is not available (%s)", kind, exc.status)
                        continue
                    raise
                collected.extend((kind, row) for row in rows if isinstance(row, dict))
            missing = _missing_people(collected, people)
            if missing:
                await _hydrate_people(client, base, people, missing)
            records: list[ServiceRecord] = []
            assigned = 0
            resolved = 0
            for kind, row in collected:
                record = normalize_record(kind, row, base, people)
                if record is None:
                    continue
                records.append(record)
                if _assignee_id(kind, row) is not None:
                    assigned += 1
                    if record.assignee or record.assignee_email:
                        resolved += 1
        warning = assignment_warning(assigned, resolved)
        return records, [warning] if warning else []


def _client(secret: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60, auth=httpx.BasicAuth(secret, "X"))


async def _list_kind(client: httpx.AsyncClient, base: str, kind: str) -> list[dict[str, Any]]:
    extra = {"include": "requester"} if kind == "ticket" else {}
    try:
        return await _list_collection(client, base, _LIST_KEY[kind], extra, MAX_PAGES)
    except FreshserviceError as exc:
        if extra and exc.status == 400:
            return await _list_collection(client, base, _LIST_KEY[kind], {}, MAX_PAGES)
        raise


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    last_error = FreshserviceError("Freshservice request failed.")
    for attempt in range(2):
        response = await client.get(url, params=params)
        if response.status_code == 429:
            wait = min(int(response.headers.get("Retry-After") or 2), 4)
            log.warning("Freshservice 429 on %s — waiting %ss", url, wait)
            await asyncio.sleep(wait)
            continue
        if response.status_code in {401, 403} and "tickets" in url and params.get("per_page") == 1:
            raise FreshserviceError(
                "Freshservice rejected the API key. Check the key and the domain.",
                status=response.status_code,
            )
        if response.status_code >= 400:
            last_error = _error(response)
            if response.status_code >= 500 and attempt == 0:
                await asyncio.sleep(2)
                continue
            raise last_error
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise FreshserviceError(f"Freshservice returned a response that was not JSON ({response.status_code}).") from exc
    raise last_error


def _error(response: httpx.Response) -> FreshserviceError:
    message: object
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("message") or body.get("description") or body.get("errors") or body
        else:
            message = body
    except Exception:  # noqa: BLE001
        message = (response.text or "")[:400] or response.reason_phrase
    if response.status_code in {401, 403}:
        text = "Freshservice rejected the API key. Check the key and the domain."
    else:
        text = f"Freshservice {response.status_code}: {message}"
    return FreshserviceError(text[:500], status=response.status_code)


def _item_type(kind: str, row: dict[str, Any]) -> str:
    if kind == "ticket":
        return str(row.get("type") or "Ticket")
    if kind == "problem":
        return "Problem"
    number = _as_int(row.get("change_type"))
    label = CHANGE_TYPE.get(number) if number is not None else None
    return f"{label} change" if label else "Change"


def assignment_warning(assigned: int, resolved: int) -> str:
    """Explain a sync that stored tickets but no assignee names."""
    if assigned > 0 and resolved == 0:
        return (
            "Freshservice returned assignees as ids only, and this API key could not read agent names. "
            "Allow the key to view agents, then sync again."
        )
    return ""


def agent_directory(rows: list[Any]) -> dict[int, tuple[str, str]]:
    """Map Freshservice user and agent ids to (display name, email).

    Ticket responder_id is sometimes the agent id and sometimes the user id.
    Both are indexed when the payload contains them.
    """
    found: dict[int, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        person = _unwrap_person(row)
        if person is None:
            continue
        name = _person_name(person)
        email = _person_email(person)
        if not name and not email:
            continue
        ids = _person_ids(row) | _person_ids(person)
        if not ids:
            continue
        for person_id in ids:
            previous = found.get(person_id)
            if previous and previous[0] and previous[1] and not email:
                continue
            merged_name = name or (previous[0] if previous else "") or email
            merged_email = email or (previous[1] if previous else "")
            found[person_id] = (merged_name, merged_email)
    return found


def _assignee(kind: str, row: dict[str, Any], people: dict[int, tuple[str, str]]) -> tuple[str, str]:
    embedded = row.get("responder") if kind == "ticket" else row.get("agent")
    if not isinstance(embedded, dict):
        embedded = row.get("responder") if isinstance(row.get("responder"), dict) else row.get("agent")
    return _linked_person(embedded, _assignee_id(kind, row), people)


def _linked_person(embedded: Any, raw_id: Any, people: dict[int, tuple[str, str]]) -> tuple[str, str]:
    name = _person_name(embedded)
    email = _person_email(embedded)
    person_id = _as_int(raw_id)
    if person_id is not None and person_id in people:
        looked_name, looked_email = people[person_id]
        name = name or looked_name
        email = email or looked_email
    return name, email


def _assignee_id(kind: str, row: dict[str, Any]) -> int | None:
    keys = ("responder_id", "agent_id") if kind == "ticket" else ("agent_id", "responder_id")
    for key in keys:
        number = _as_int(row.get(key))
        if number is not None:
            return number
    return None


def _missing_people(
    collected: list[tuple[str, dict[str, Any]]], people: dict[int, tuple[str, str]]
) -> list[int]:
    missing: list[int] = []
    seen: set[int] = set()

    def add(number: int | None) -> None:
        if number is None or number in people or number in seen:
            return
        seen.add(number)
        missing.append(number)

    for kind, row in collected:
        add(_assignee_id(kind, row))
        requester = row.get("requester")
        if not (isinstance(requester, dict) and (_person_name(requester) or _person_email(requester))):
            add(_as_int(row.get("requester_id")))
    return missing


async def _load_people(client: httpx.AsyncClient, base: str) -> dict[int, tuple[str, str]]:
    """Build the id → person map used to fill ticket assignees.

    The agents list is the primary source. A key that cannot list agents falls
    back to requesters with agents included. Ids that are still unknown are
    fetched one at a time later.
    """
    rows: list[dict[str, Any]] = []
    agents_ok = False
    try:
        rows.extend(await _list_collection(client, base, "agents", {}))
        agents_ok = True
    except FreshserviceError as exc:
        if exc.status not in {401, 403, 404}:
            raise
        log.info("Freshservice agents list is not available (%s)", exc.status)
    if agents_ok:
        try:
            rows.extend(await _list_collection(client, base, "agents", {"active": "false"}))
        except FreshserviceError as exc:
            log.info("Freshservice deactivated agents were skipped (%s)", exc.status)
    if not rows:
        try:
            rows.extend(await _list_collection(client, base, "requesters", {"include_agents": "true"}))
        except FreshserviceError as exc:
            if exc.status not in {400, 401, 403, 404}:
                raise
            log.info("Freshservice requesters were not available (%s)", exc.status)
    return agent_directory(rows)


async def _hydrate_people(
    client: httpx.AsyncClient,
    base: str,
    people: dict[int, tuple[str, str]],
    missing: list[int],
) -> None:
    """Look up assignee ids the bulk list did not contain.

    Freshservice responder_id does not always equal the id on the agents list.
    A forbidden lookup stops the loop so a locked-down key does not spend the
    whole sync on 403s.
    """
    for person_id in missing[:HYDRATE_LIMIT]:
        denied = False
        for path in (f"agents/{person_id}", f"requesters/{person_id}"):
            try:
                payload = await _get(client, f"{base}/api/v2/{path}", {})
            except FreshserviceError as exc:
                if exc.status in {401, 403}:
                    log.info("Freshservice %s is not permitted (%s)", path, exc.status)
                    denied = True
                continue
            if isinstance(payload, dict):
                people.update(agent_directory([payload]))
            if person_id in people:
                denied = False
                break
        if denied and person_id not in people:
            return


async def _list_collection(
    client: httpx.AsyncClient,
    base: str,
    key: str,
    extra: dict[str, Any],
    page_cap: int = AGENT_PAGES,
) -> list[dict[str, Any]]:
    """Page a Freshservice collection.

    Some accounts ignore per_page and always return 30 rows, with no Link
    header. Stopping when the page is shorter than 100 would drop everyone
    after the first page. A repeated id means the server ignored the page
    number, so that ends the loop as well.
    """
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    page_size: int | None = None
    for page in range(1, page_cap + 1):
        payload = await _get(client, f"{base}/api/v2/{key}", {"page": page, "per_page": PAGE_SIZE, **extra})
        batch = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(batch, list):
            batch = []
        fresh: list[dict[str, Any]] = []
        for row in batch:
            if not isinstance(row, dict):
                continue
            marker = _as_int(row.get("id"))
            if marker is None:
                inner = _unwrap_person(row)
                marker = _as_int(inner.get("id")) if isinstance(inner, dict) else None
            if marker is not None:
                if marker in seen:
                    continue
                seen.add(marker)
            fresh.append(row)
        if not fresh:
            break
        rows.extend(fresh)
        if page_size is None:
            page_size = len(batch)
        if len(batch) < page_size:
            break
    return rows


def _unwrap_person(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("agent", "requester", "user"):
        inner = row.get(key)
        if not isinstance(inner, dict):
            continue
        user = inner.get("user")
        if isinstance(user, dict):
            merged = dict(user)
            agent_id = inner.get("id")
            for field, value in inner.items():
                if field in {"user", "id"} or value in (None, ""):
                    continue
                merged[field] = value
            if agent_id not in (None, ""):
                merged["_agent_id"] = agent_id
            return merged
        return inner
    if any(row.get(key) not in (None, "") for key in ("id", "email", "primary_email", "first_name", "name")):
        return row
    return None


def _person_ids(row: dict[str, Any]) -> set[int]:
    found: set[int] = set()
    for key in ("id", "user_id", "_agent_id"):
        number = _as_int(row.get(key))
        if number is not None:
            found.add(number)
    user = row.get("user")
    if isinstance(user, dict):
        number = _as_int(user.get("id"))
        if number is not None:
            found.add(number)
    return found


def _person_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    name = str(value.get("name") or "").strip()
    if name:
        return name
    first = str(value.get("first_name") or "").strip()
    last = str(value.get("last_name") or "").strip()
    joined = " ".join(part for part in (first, last) if part)
    return joined or _person_email(value)


def _person_email(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("email") or value.get("primary_email") or "").strip()
    return ""


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
