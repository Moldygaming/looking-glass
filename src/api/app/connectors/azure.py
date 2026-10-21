"""Azure Cost Management connector.

Auth is a token against management.azure.com. Ingest prefers the cost-details
report, which includes every resource type on the bill. The Query API is the
fallback: it allows two groupings, and a ResourceId grouping omits charges
that have no resource. Management-group scopes expand to subscriptions.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
from azure.identity import ClientSecretCredential, DefaultAzureCredential

from app.connectors.base import Connector, NormalizedCost
from app.services.azure_resources import (
    costs_from_details_csv,
    month_windows,
    normalized_from_query_item,
    reconcile_unallocated,
)

log = logging.getLogger("looking-glass.azure")
QUERY_API = "2023-11-01"
SUB_API = "2022-12-01"
MG_API = "2020-05-01"
RESOURCE_GROUPINGS = [
    ("Cost", [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "ServiceName"}]),
    ("PreTaxCost", [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "MeterCategory"}]),
    ("Cost", [{"type": "Dimension", "name": "ResourceId"}]),
]
SERVICE_GROUPINGS = [
    ("Cost", [{"type": "Dimension", "name": "ServiceName"}]),
    ("PreTaxCost", [{"type": "Dimension", "name": "ServiceName"}]),
]


class AzureIngestError(RuntimeError):
    pass


class AzureConnector(Connector):
    provider = "azure"

    async def ingest(
        self, connection_id: UUID, config: dict[str, Any], secret: str | None
    ) -> list[NormalizedCost]:
        scope = _normalize_scope(config.get("scope") or "")
        if not scope:
            raise AzureIngestError("A Cost Management scope is required.")

        credential = _credential(config, secret)
        token = credential.get_token("https://management.azure.com/.default").token
        end = date.today()
        start = end - timedelta(days=max(int(config.get("lookback_days") or 14) - 1, 0))
        default_tags = {str(k): str(v) for k, v in dict(config.get("default_tags") or {}).items()}
        currency = str(config.get("currency") or "GBP")

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=120) as client:
            scopes = await _query_scopes(client, headers, scope)
            rows: list[NormalizedCost] = []
            errors: list[str] = []
            for query_scope in scopes:
                try:
                    rows.extend(
                        await _query_scope(client, headers, query_scope, start, end, default_tags, currency)
                    )
                except AzureIngestError as exc:
                    errors.append(f"{query_scope}: {exc}")
            if not rows and errors:
                raise AzureIngestError("Azure Cost Management rejected the query. " + " | ".join(errors[:4]))
            return rows

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        if not config.get("tenant_id") or not config.get("client_id"):
            raise ValueError("Azure tenant ID and application (client) ID are required.")
        if not secret:
            raise ValueError("Client secret is required.")
        if not config.get("scope"):
            raise ValueError("A Cost Management scope is required.")
        credential = _credential(config, secret)
        credential.get_token("https://management.azure.com/.default")
        return f"Authenticated to tenant {config['tenant_id']} for scope {config['scope']}."


def _credential(config: dict[str, Any], secret: str | None):
    client_id = config.get("client_id")
    tenant_id = config.get("tenant_id")
    client_secret = secret or config.get("client_secret")
    if client_id and tenant_id and client_secret:
        return ClientSecretCredential(str(tenant_id), str(client_id), str(client_secret))
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def _normalize_scope(scope: str) -> str:
    scope = scope.strip()
    if not scope:
        return ""
    if not scope.startswith("/"):
        scope = "/" + scope
    return scope.rstrip("/")


async def _query_scopes(client: httpx.AsyncClient, headers: dict[str, str], scope: str) -> list[str]:
    lower = scope.lower()
    if "/subscriptions/" in lower and "managementgroups" not in lower:
        return [scope]
    if "billingaccounts" in lower:
        return [scope]

    mg_id = scope.split("/")[-1]
    response = await _request(
        client,
        "GET",
        f"https://management.azure.com/providers/Microsoft.Management/managementGroups/{mg_id}/subscriptions",
        headers,
        params={"api-version": MG_API},
        allow_error=True,
    )
    if response.status_code == 200:
        ids = [item.get("name") or item.get("id", "").split("/")[-1] for item in response.json().get("value", [])]
        ids = [i for i in ids if i]
        if ids:
            return [f"/subscriptions/{i}" for i in ids]

    response = await _request(
        client,
        "GET",
        "https://management.azure.com/subscriptions",
        headers,
        params={"api-version": SUB_API},
        allow_error=True,
    )
    if response.status_code == 200:
        ids = [item.get("subscriptionId") for item in response.json().get("value", []) if item.get("subscriptionId")]
        if ids:
            return [f"/subscriptions/{i}" for i in ids]

    return [scope]


def _cost_details_scope(scope: str) -> bool:
    lowered = scope.lower()
    if "/resourcegroups/" in lowered or "managementgroups" in lowered:
        return False
    return "/subscriptions/" in lowered or "billingaccounts" in lowered


async def _query_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
) -> list[NormalizedCost]:
    if _cost_details_scope(scope):
        try:
            detailed = await _cost_details(client, headers, scope, start, end, default_tags, currency)
            if detailed:
                log.info("Azure cost details %s rows=%s", scope, len(detailed))
                return detailed
        except AzureIngestError as exc:
            message = str(exc)
            log.warning("Azure cost details unavailable for %s: %s", scope, message)
            if "429" in message:
                raise
    return await _query_api_scope(client, headers, scope, start, end, default_tags, currency)


async def _query_api_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
) -> list[NormalizedCost]:
    resource_rows, resource_error = await _first_grouping(
        client, headers, scope, start, end, default_tags, currency, RESOURCE_GROUPINGS
    )
    service_rows, service_error = await _first_grouping(
        client, headers, scope, start, end, default_tags, currency, SERVICE_GROUPINGS
    )
    if resource_rows is None and service_rows is None:
        raise AzureIngestError(resource_error or service_error or "No Cost Management query grouping succeeded.")
    return reconcile_unallocated(resource_rows or [], service_rows or [], scope)


async def _first_grouping(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
    groupings: list[tuple[str, list[dict[str, str]]]],
) -> tuple[list[NormalizedCost] | None, str]:
    last_error = "No Cost Management query grouping succeeded."
    for cost_column, grouping in groupings:
        try:
            raw_rows, columns = await _run_query(client, headers, scope, start, end, grouping, cost_column)
            rows = [
                normalized_from_query_item(item, scope, default_tags, currency, cost_column)
                for item in (_row_dict(columns, raw) for raw in raw_rows)
            ]
            return rows, ""
        except AzureIngestError as exc:
            last_error = str(exc)
            lowered = last_error.lower()
            if "429" in lowered:
                raise
            if any(token in lowered for token in ("group", "dimension", "column", "aggregat", "invalid", "badrequest", "400")):
                continue
            raise
    return None, last_error


async def _cost_details(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
) -> list[NormalizedCost]:
    rows: list[NormalizedCost] = []
    for window_start, window_end in month_windows(start, end):
        rows.extend(
            await _cost_details_window(client, headers, scope, window_start, window_end, default_tags, currency)
        )
    return rows


async def _cost_details_window(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
) -> list[NormalizedCost]:
    url = f"https://management.azure.com{scope}/providers/Microsoft.CostManagement/generateCostDetailsReport"
    payload = {
        "metric": "ActualCost",
        "timePeriod": {"start": start.isoformat(), "end": end.isoformat()},
    }
    response = await _request(client, "POST", url, headers, params={"api-version": QUERY_API}, json_body=payload)
    if response.status_code == 204:
        return []
    data = response.json() if response.status_code == 200 else await _poll_cost_details(client, headers, response)
    status = _cost_details_status(data)
    if status == "nodatafound":
        return []
    if status == "failed":
        error = data.get("error") or {}
        raise AzureIngestError(str(error.get("message") or "Cost details report failed."))
    rows: list[NormalizedCost] = []
    for blob in _cost_details_blobs(data):
        link = str(blob.get("blobLink") or "")
        if not link:
            continue
        text = await _download_report(client, link)
        rows.extend(costs_from_details_csv(text, scope, default_tags, currency))
    return rows


def _cost_details_status(data: dict[str, Any]) -> str:
    status = data.get("status") or (data.get("properties") or {}).get("status") or ""
    return str(status).lower()


def _cost_details_blobs(data: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = data.get("manifest") or (data.get("properties") or {}).get("manifest") or {}
    return list(manifest.get("blobs") or [])


async def _poll_cost_details(
    client: httpx.AsyncClient, headers: dict[str, str], response: httpx.Response
) -> dict[str, Any]:
    location = response.headers.get("Location") or response.headers.get("location") or ""
    if not location:
        raise AzureIngestError("Cost details report was accepted without a status URL.")
    if location.startswith("/"):
        location = "https://management.azure.com" + location
    for _ in range(15):
        wait = int(response.headers.get("Retry-After") or response.headers.get("retry-after") or 5)
        await asyncio.sleep(min(max(wait, 2), 8))
        response = await _request(client, "GET", location, headers, allow_error=True)
        if response.status_code == 202:
            continue
        if response.status_code == 200:
            data = response.json() if response.content else {}
            status = _cost_details_status(data)
            if status in {"completed", "nodatafound", "failed", ""}:
                return data
            continue
        raise AzureIngestError(_azure_message(response))
    raise AzureIngestError("Cost details report did not finish in time.")


async def _download_report(client: httpx.AsyncClient, link: str) -> str:
    response = await client.get(link, timeout=120)
    if not response.is_success:
        raise AzureIngestError(f"Azure cost details download failed ({response.status_code}).")
    raw = response.content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8-sig")


async def _run_query(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    grouping: list[dict[str, str]],
    cost_column: str,
) -> tuple[list[list[Any]], list[str]]:
    payload = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": start.isoformat(), "to": end.isoformat()},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": cost_column, "function": "Sum"}},
            "grouping": grouping,
        },
    }
    url = f"https://management.azure.com{scope}/providers/Microsoft.CostManagement/query"
    rows: list[list[Any]] = []
    columns: list[str] = []
    next_url: str | None = url
    body: dict[str, Any] | None = payload
    params: dict[str, str] | None = {"api-version": QUERY_API, "$top": "5000"}
    seen: set[str] = set()
    for _ in range(40):
        if not next_url or next_url in seen:
            break
        seen.add(next_url)
        response = await _request(client, "POST", next_url, headers, params=params, json_body=body)
        if response.status_code == 204:
            return rows, columns
        data = response.json() if response.content else {}
        props = data.get("properties") or data
        columns = [c.get("name") for c in props.get("columns", []) if c.get("name")]
        rows.extend(props.get("rows") or [])
        next_url = props.get("nextLink")
        if next_url and str(next_url).startswith("/"):
            next_url = "https://management.azure.com" + str(next_url)
        body = payload if next_url else None
        params = None
    return rows, columns


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    allow_error: bool = False,
) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(6):
        response = await client.request(method, url, headers=headers, params=params, json=json_body)
        last = response
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After") or min(15 * (attempt + 1), 60))
            log.warning("Azure 429 on %s — waiting %ss", url, wait)
            await asyncio.sleep(wait)
            continue
        if allow_error or response.is_success or response.status_code == 204:
            return response
        raise AzureIngestError(_azure_message(response))
    raise AzureIngestError(_azure_message(last) if last is not None else "Azure Cost Management rate-limited the request.")


def _azure_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error") or payload
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or str(error)
            return f"Azure {response.status_code}: {message}"
        return f"Azure {response.status_code}: {payload}"
    except Exception:  # noqa: BLE001
        text = (response.text or "")[:800]
        return f"Azure {response.status_code}: {text or response.reason_phrase}"


def _row_dict(columns: list[str], raw: list[Any]) -> dict[str, Any]:
    return dict(zip(columns, raw, strict=False))
