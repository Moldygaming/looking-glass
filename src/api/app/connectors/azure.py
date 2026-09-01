"""Azure Cost Management connector.

Auth is a token against management.azure.com. Ingest uses the Cost Management
Query API, which allows at most two grouping dimensions. Management-group
scopes are expanded to subscriptions when the identity can list them.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
from azure.identity import ClientSecretCredential, DefaultAzureCredential

from app.connectors.base import Connector, NormalizedCost

log = logging.getLogger("looking-glass.azure")
QUERY_API = "2023-11-01"
SUB_API = "2022-12-01"
MG_API = "2020-05-01"
QUERIES = [
    ("Cost", [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "MeterCategory"}]),
    ("PreTaxCost", [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "MeterCategory"}]),
    ("Cost", [{"type": "Dimension", "name": "ServiceName"}, {"type": "Dimension", "name": "ResourceLocation"}]),
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


async def _query_scope(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scope: str,
    start: date,
    end: date,
    default_tags: dict[str, str],
    currency: str,
) -> list[NormalizedCost]:
    last_error = "No Cost Management query grouping succeeded."
    for cost_column, grouping in QUERIES:
        try:
            raw_rows, columns = await _run_query(client, headers, scope, start, end, grouping, cost_column)
            return [
                _to_cost(item, scope, default_tags, currency, cost_column)
                for item in (_row_dict(columns, raw) for raw in raw_rows)
            ]
        except AzureIngestError as exc:
            last_error = str(exc)
            lowered = last_error.lower()
            if "429" in lowered:
                raise
            if any(token in lowered for token in ("group", "dimension", "column", "aggregat", "invalid", "badrequest", "400")):
                continue
            raise
    raise AzureIngestError(last_error)


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
    params: dict[str, str] | None = {"api-version": QUERY_API}
    while next_url:
        response = await _request(client, "POST", next_url, headers, params=params, json_body=body)
        if response.status_code == 204:
            return [], []
        data = response.json() if response.content else {}
        props = data.get("properties") or data
        columns = [c.get("name") for c in props.get("columns", []) if c.get("name")]
        rows.extend(props.get("rows") or [])
        next_url = props.get("nextLink")
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


def _to_cost(item: dict[str, Any], scope: str, default_tags: dict[str, str], currency: str, cost_column: str) -> NormalizedCost:
    resource_id = str(item.get("ResourceId") or "")
    name, resource_type, subscription_id, resource_group = _parse_resource(resource_id)
    account_id = str(item.get("SubscriptionId") or subscription_id or _subscription_from_scope(scope) or "")
    account_name = str(item.get("SubscriptionName") or account_id)
    service = str(item.get("MeterCategory") or item.get("ServiceName") or resource_type or "Other")
    meter = str(item.get("Meter") or item.get("MeterCategory") or service)
    cost = float(item.get(cost_column) or item.get("Cost") or item.get("PreTaxCost") or 0)
    return NormalizedCost(
        usage_date=_parse_usage_date(item.get("UsageDate") or item.get("Date"), date.today()),
        account_id=account_id,
        account_name=account_name,
        resource_group=resource_group,
        resource_id=resource_id or f"{scope}/{service}",
        resource_name=name or service,
        resource_type=resource_type or service,
        service=service,
        category=_category(service),
        meter=meter,
        region=str(item.get("ResourceLocation") or ""),
        tags=default_tags,
        cost=cost,
        amortized_cost=cost,
        currency=str(item.get("Currency") or currency),
        usage_quantity=float(item.get("UsageQuantity") or 0),
        usage_unit="",
    )


def _parse_resource(resource_id: str) -> tuple[str, str, str, str]:
    if not resource_id:
        return "", "", "", ""
    parts = [p for p in resource_id.split("/") if p]
    name = parts[-1] if parts else resource_id
    resource_type = ""
    subscription_id = ""
    resource_group = ""
    lowered = [p.lower() for p in parts]
    if "providers" in lowered:
        i = lowered.index("providers")
        resource_type = "/".join(parts[i + 1 : i + 3]) if i + 2 < len(parts) else ""
    if "subscriptions" in lowered:
        i = lowered.index("subscriptions")
        if i + 1 < len(parts):
            subscription_id = parts[i + 1]
    if "resourcegroups" in lowered:
        i = lowered.index("resourcegroups")
        if i + 1 < len(parts):
            resource_group = parts[i + 1]
    return name, resource_type, subscription_id, resource_group


def _subscription_from_scope(scope: str) -> str:
    parts = scope.split("/")
    if "subscriptions" in parts:
        i = parts.index("subscriptions")
        if i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _parse_usage_date(value: Any, fallback: date) -> date:
    if value is None:
        return fallback
    text = str(int(value)) if isinstance(value, float) else str(value)
    if len(text) == 8 and text.isdigit():
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return fallback


def _category(service: str) -> str:
    lowered = service.lower()
    if any(k in lowered for k in ("virtual machine", "compute", "aks", "kubernetes", "functions", "app service")):
        return "Compute"
    if any(k in lowered for k in ("storage", "blob", "disk")):
        return "Storage"
    if any(k in lowered for k in ("sql", "cosmos", "database", "cache")):
        return "Database"
    if any(k in lowered for k in ("bandwidth", "network", "vnet", "gateway", "load balancer")):
        return "Network"
    return "Other"
