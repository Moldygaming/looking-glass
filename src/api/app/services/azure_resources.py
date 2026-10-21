"""Pure helpers for Azure cost rows.

The Cost Management Query API, grouped by ResourceId, omits charges that have
no resource id and is a poor fit for a full bill. These helpers turn either
that query or a cost-details CSV into the same normalized rows, and name ARM
types the way the rest of the product already talks about them.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.connectors.base import NormalizedCost
from app.services.hierarchy import classify_category

_FRIENDLY = {
    "microsoft.web/sites": "App Service",
    "microsoft.web/sites/slots": "App Service slot",
    "microsoft.web/serverfarms": "App Service plan",
    "microsoft.compute/virtualmachines": "Virtual Machine",
    "microsoft.compute/virtualmachinescalesets": "Virtual machine scale set",
    "microsoft.compute/disks": "Managed Disk",
    "microsoft.compute/snapshots": "Snapshot",
    "microsoft.storage/storageaccounts": "Storage account",
    "microsoft.sql/servers": "Azure SQL",
    "microsoft.sql/servers/databases": "SQL database",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL",
    "microsoft.dbformysql/flexibleservers": "MySQL",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.cache/redis": "Redis",
    "microsoft.containerregistry/registries": "Container registry",
    "microsoft.containerservice/managedclusters": "AKS",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.network/publicipaddresses": "Public IP",
    "microsoft.network/loadbalancers": "Load balancer",
    "microsoft.network/applicationgateways": "Application gateway",
    "microsoft.network/natgateways": "NAT gateway",
    "microsoft.network/bastionhosts": "Bastion",
    "microsoft.network/azurefirewalls": "Azure Firewall",
    "microsoft.network/privateendpoints": "Private endpoint",
    "microsoft.insights/components": "Application Insights",
    "microsoft.operationalinsights/workspaces": "Log Analytics",
    "microsoft.logic/workflows": "Logic App",
    "microsoft.servicebus/namespaces": "Service Bus",
    "microsoft.eventhub/namespaces": "Event Hubs",
    "microsoft.cognitiveservices/accounts": "Cognitive Services",
    "microsoft.app/containerapps": "Container App",
    "microsoft.app/managedenvironments": "Container Apps environment",
    "microsoft.containerinstance/containergroups": "Container instance",
    "microsoft.recoveryservices/vaults": "Recovery Services",
    "microsoft.cdn/profiles": "CDN",
    "microsoft.apimanagement/service": "API Management",
}


def friendly_resource_type(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    mapped = _FRIENDLY.get(text.lower())
    if mapped:
        return mapped
    if not text.lower().startswith("microsoft."):
        return text
    tail = text.split("/")[-1]
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", tail).replace("-", " ").strip()
    if not spaced:
        return text
    return spaced[:1].upper() + spaced[1:]


def parse_arm_resource(resource_id: str) -> tuple[str, str, str, str]:
    """Return name, ARM type, subscription id and resource group."""
    if not resource_id:
        return "", "", "", ""
    parts = [part for part in resource_id.split("/") if part]
    lowered = [part.lower() for part in parts]
    subscription_id = ""
    resource_group = ""
    if "subscriptions" in lowered:
        index = lowered.index("subscriptions")
        if index + 1 < len(parts):
            subscription_id = parts[index + 1]
    if "resourcegroups" in lowered:
        index = lowered.index("resourcegroups")
        if index + 1 < len(parts):
            resource_group = parts[index + 1]
    name = parts[-1] if parts else ""
    resource_type = ""
    if "providers" in lowered:
        index = lowered.index("providers")
        rest = parts[index + 1 :]
        if rest:
            type_bits = rest[1::2]
            resource_type = "/".join([rest[0], *type_bits]) if type_bits else rest[0]
            if len(rest) >= 2:
                name = rest[-1]
    return name, resource_type, subscription_id, resource_group


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split a range into calendar months. Cost details allows one month per call."""
    if end < start:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        window_end = min(end, next_month - timedelta(days=1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def subscription_from_scope(scope: str) -> str:
    parts = scope.split("/")
    if "subscriptions" in parts:
        index = parts.index("subscriptions")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def parse_usage_date(value: Any, fallback: date) -> date:
    if value is None or value == "":
        return fallback
    text = str(int(value)) if isinstance(value, float) and float(value).is_integer() else str(value)
    text = text.strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    if "/" in text:
        parts = text.split("/")
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            month, day, year = (int(part) for part in parts[:3])
            try:
                return date(year, month, day)
            except ValueError:
                return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return fallback


def costs_from_details_csv(
    text: str, scope: str, default_tags: dict[str, str], currency: str
) -> list[NormalizedCost]:
    rows: list[NormalizedCost] = []
    for raw in csv.DictReader(io.StringIO(text or "")):
        item = normalized_from_details_row(raw, scope, default_tags, currency)
        if item is not None:
            rows.append(item)
    return rows


def normalized_from_details_row(
    row: dict[str, Any], scope: str, default_tags: dict[str, str], currency: str
) -> NormalizedCost | None:
    lowered = {(key or "").strip().lower(): "" if value is None else str(value).strip() for key, value in row.items()}

    def col(*names: str) -> str:
        for name in names:
            value = lowered.get(name.lower())
            if value:
                return value
        return ""

    item = {
        "ResourceId": col("resourceid", "instanceid"),
        "SubscriptionId": col("subscriptionid", "subscriptionguid"),
        "SubscriptionName": col("subscriptionname"),
        "ResourceGroup": col("resourcegroup", "resourcegroupname"),
        "MeterCategory": col("metercategory", "servicename", "consumedservice"),
        "ServiceName": col("servicename", "metercategory", "consumedservice"),
        "Meter": col("metername", "meter"),
        "ResourceLocation": col("resourcelocation", "location"),
        "Cost": col("costinbillingcurrency", "cost", "pretaxcost"),
        "Currency": col("billingcurrency", "currency", "pricingcurrency") or currency,
        "UsageDate": col("date", "usagedate"),
        "UsageQuantity": col("quantity", "usagequantity"),
        "UnitOfMeasure": col("unitofmeasure"),
    }
    tags = {**default_tags, **_parse_tags(col("tags"))}
    cost = normalized_from_query_item(item, scope, tags, currency, "Cost")
    if abs(cost.cost) < 1e-9 and abs(cost.usage_quantity) < 1e-9:
        return None
    return cost


def normalized_from_query_item(
    item: dict[str, Any],
    scope: str,
    default_tags: dict[str, str],
    currency: str,
    cost_column: str,
) -> NormalizedCost:
    resource_id = str(item.get("ResourceId") or "")
    name, resource_type, subscription_id, resource_group = parse_arm_resource(resource_id)
    resource_group = resource_group or str(item.get("ResourceGroup") or "")
    account_id = str(item.get("SubscriptionId") or subscription_id or subscription_from_scope(scope) or "")
    account_name = str(item.get("SubscriptionName") or account_id)
    service = str(item.get("MeterCategory") or item.get("ServiceName") or resource_type or "Other")
    meter = str(item.get("Meter") or item.get("MeterCategory") or service)
    amount = _num(item.get(cost_column) if item.get(cost_column) not in (None, "") else None)
    if item.get(cost_column) in (None, ""):
        amount = _num(item.get("Cost") if item.get("Cost") not in (None, "") else item.get("PreTaxCost"))
    usage_date = parse_usage_date(item.get("UsageDate") or item.get("Date"), date.today())
    if not resource_id:
        label = service or "Other"
        resource_id = f"{scope}/unallocated/{label}/{usage_date.isoformat()}"
        name = f"{label} (no resource)"
        resource_type = "Unallocated"
    else:
        resource_type = friendly_resource_type(resource_type) or service
    return NormalizedCost(
        usage_date=usage_date,
        account_id=_clip(account_id, 256),
        account_name=_clip(account_name, 256),
        resource_group=_clip(resource_group, 256),
        resource_id=_clip(resource_id, 1024),
        resource_name=_clip(name or service, 256),
        resource_type=_clip(resource_type or "Other", 128),
        service=_clip(service, 128),
        category=classify_category(service, resource_type),
        meter=_clip(meter, 256),
        region=_clip(str(item.get("ResourceLocation") or ""), 64),
        tags=dict(default_tags),
        cost=amount,
        amortized_cost=amount,
        currency=_clip(str(item.get("Currency") or currency or "GBP"), 8) or "GBP",
        usage_quantity=_num(item.get("UsageQuantity")),
        usage_unit=_clip(str(item.get("UnitOfMeasure") or ""), 64),
    )


def reconcile_unallocated(
    resource_rows: list[NormalizedCost], service_rows: list[NormalizedCost], scope: str
) -> list[NormalizedCost]:
    """Keep resource rows, and add the service-total gap the resource query omitted."""
    if not resource_rows:
        return list(service_rows)
    if not service_rows:
        return list(resource_rows)
    resource_by_day: dict[date, float] = defaultdict(float)
    for row in resource_rows:
        resource_by_day[row.usage_date] += float(row.cost or 0)
    service_by_day: dict[date, float] = defaultdict(float)
    for row in service_rows:
        service_by_day[row.usage_date] += float(row.cost or 0)
    sample = service_rows[0]
    extras: list[NormalizedCost] = []
    for day, total in sorted(service_by_day.items()):
        gap = round(total - resource_by_day.get(day, 0.0), 6)
        if gap <= 0.05:
            continue
        extras.append(
            NormalizedCost(
                usage_date=day,
                account_id=sample.account_id,
                account_name=sample.account_name,
                resource_group="",
                resource_id=_clip(f"{scope}/unallocated/{day.isoformat()}", 1024),
                resource_name="Charges without a resource",
                resource_type="Unallocated",
                service="Unallocated",
                category="Other",
                meter="Unallocated",
                region="",
                tags={},
                cost=gap,
                amortized_cost=gap,
                currency=sample.currency,
            )
        )
    return [*resource_rows, *extras]


def _parse_tags(raw: str) -> dict[str, str]:
    if not raw or raw in {"{}", "null"}:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _clip(value: str, limit: int) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit]
