"""Cost objects: typed dimensions you can stack into any hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, or_
from sqlalchemy.sql import ColumnElement

from app.models import CostLineItem
from app.services.hierarchy import classify_category

NONE_LABEL = "(none)"


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    group: str
    description: str


CORE_DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("provider", "Cloud", "Platform", "Azure, AWS or GCP."),
    Dimension("connection", "Connection", "Platform", "A connected billing organisation."),
    Dimension("org", "Organisation", "Platform", "Tenant, management group, payer or billing org."),
    Dimension("account", "Account", "Scope", "Azure subscription, AWS account or GCP project."),
    Dimension("resource_group", "Resource group", "Scope", "Azure resource group. Empty on AWS/GCP."),
    Dimension("region", "Region", "Scope", "Cloud region."),
    Dimension("category", "Category", "Usage", "Compute, storage, database, network, and so on."),
    Dimension("service", "Service", "Usage", "Billed product or service."),
    Dimension("resource_type", "Resource type", "Usage", "VM, disk, database, and so on."),
    Dimension("meter", "Meter", "Usage", "SKU / meter name from the bill."),
    Dimension("resource", "Resource", "Usage", "Individual billed resource."),
)

CORE_KEYS = {item.key for item in CORE_DIMENSIONS}

PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "cloud",
        "name": "Cloud hierarchy",
        "description": "Cloud → connection → organisation → account → resource group → resource.",
        "path": ["provider", "connection", "org", "account", "resource_group", "resource"],
    },
    {
        "id": "workload",
        "name": "Workload",
        "description": "Cloud → service → region → resource.",
        "path": ["provider", "service", "region", "resource"],
    },
    {
        "id": "sku",
        "name": "SKU",
        "description": "Service → meter → resource.",
        "path": ["service", "meter", "resource"],
    },
    {
        "id": "account",
        "name": "Accounts",
        "description": "Organisation → account → service.",
        "path": ["org", "account", "service"],
    },
)

DEFAULT_PATH = list(PRESETS[0]["path"])

KIND_LABELS: dict[str, str] = {
    **{item.key: item.label for item in CORE_DIMENSIONS},
    "management_group": "Organisation",
    "subscription": "Account",
    "project": "Account",
}


def dimension_payload(tag_keys: list[str] | None = None) -> list[dict[str, str]]:
    rows = [
        {"key": item.key, "label": item.label, "group": item.group, "description": item.description}
        for item in CORE_DIMENSIONS
    ]
    for key in tag_keys or []:
        rows.append(
            {
                "key": f"tag:{key}",
                "label": f"Tag · {key}",
                "group": "Tags",
                "description": f"Values of the {key} tag.",
            }
        )
    return rows


def normalize_path(raw: str | list[str] | None) -> list[str]:
    if raw is None or raw == "":
        return list(DEFAULT_PATH)
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    cleaned: list[str] = []
    for part in parts:
        key = (part or "").strip()
        if not key or key in cleaned:
            continue
        if key in {"management_group", "subscription", "project"}:
            key = {"management_group": "org", "subscription": "account", "project": "account"}[key]
        if key in CORE_KEYS or key.startswith("tag:"):
            cleaned.append(key)
    return cleaned or list(DEFAULT_PATH)


def parse_object_key(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        return "", ""
    if text.startswith("tag:"):
        rest = text[4:]
        if "=" in rest:
            key, value = rest.split("=", 1)
            return f"tag:{key}", value
        return "tag", rest
    kind, sep, value = text.partition(":")
    if not sep:
        return "resource", text
    aliases = {"management_group": "org", "subscription": "account", "project": "account"}
    return aliases.get(kind, kind), value


def object_key(kind: str, value: str) -> str:
    if kind.startswith("tag:"):
        tag = kind.split(":", 1)[1]
        return f"tag:{tag}={value}"
    return f"{kind}:{value}"


def parse_focus(raw: str | list[str] | None) -> list[tuple[str, str]]:
    if not raw:
        return []
    parts = raw.split("|") if isinstance(raw, str) else list(raw)
    parsed: list[tuple[str, str]] = []
    for part in parts:
        kind, value = parse_object_key(part.strip())
        if kind:
            parsed.append((kind, value))
    return parsed


def next_kind(path: list[str], focus: list[tuple[str, str]]) -> str | None:
    used = [kind for kind, _ in focus]
    for kind in path:
        if kind not in used:
            return kind
    return None


def _blank(column) -> ColumnElement:
    return func.coalesce(func.nullif(func.trim(cast(column, String)), ""), "")


def dimension_expr(kind: str) -> ColumnElement:
    if kind.startswith("tag:"):
        key = kind.split(":", 1)[1]
        return _blank(CostLineItem.tags[key].astext)
    mapping = {
        "provider": _blank(CostLineItem.provider),
        "connection": cast(CostLineItem.connection_id, String),
        "org": _blank(CostLineItem.org_id),
        "management_group": _blank(CostLineItem.org_id),
        "account": _blank(CostLineItem.account_id),
        "subscription": _blank(CostLineItem.account_id),
        "project": _blank(CostLineItem.account_id),
        "resource_group": _blank(CostLineItem.resource_group),
        "region": _blank(CostLineItem.region),
        "category": _blank(CostLineItem.category),
        "service": _blank(CostLineItem.service),
        "resource_type": _blank(CostLineItem.resource_type),
        "meter": _blank(CostLineItem.meter),
        "resource": _blank(CostLineItem.resource_id),
        "resource_name": _blank(CostLineItem.resource_name),
    }
    return mapping.get(kind, _blank(CostLineItem.service))


def dimension_label_expr(kind: str) -> ColumnElement:
    if kind.startswith("tag:"):
        return dimension_expr(kind)
    labels = {
        "org": func.coalesce(func.nullif(CostLineItem.org_name, ""), dimension_expr("org")),
        "management_group": func.coalesce(func.nullif(CostLineItem.org_name, ""), dimension_expr("org")),
        "account": func.coalesce(func.nullif(CostLineItem.account_name, ""), dimension_expr("account")),
        "subscription": func.coalesce(func.nullif(CostLineItem.account_name, ""), dimension_expr("account")),
        "project": func.coalesce(func.nullif(CostLineItem.account_name, ""), dimension_expr("account")),
        "resource": func.coalesce(func.nullif(CostLineItem.resource_name, ""), dimension_expr("resource")),
        "connection": cast(CostLineItem.connection_id, String),
        "provider": CostLineItem.provider,
    }
    return labels.get(kind, dimension_expr(kind))


def dimension_filter(kind: str, value: str) -> ColumnElement:
    expr = dimension_expr(kind)
    if value in {"", NONE_LABEL}:
        return or_(expr.is_(None), expr == "")
    if kind == "connection":
        try:
            return CostLineItem.connection_id == UUID(value)
        except (ValueError, TypeError):
            return expr == value
    return expr == value


def display_label(kind: str, value: str, raw_label: str | None = None) -> str:
    text = (raw_label or value or "").strip()
    if not text or text == value and not value:
        return NONE_LABEL
    if kind == "provider":
        return {"azure": "Azure", "aws": "AWS", "gcp": "GCP"}.get(text.lower(), text)
    return text


def kind_label(kind: str) -> str:
    if kind.startswith("tag:"):
        return f"Tag · {kind.split(':', 1)[1]}"
    return KIND_LABELS.get(kind, kind.replace("_", " ").title())


def object_category(kind: str, service: str, resource_type: str = "") -> str:
    if kind == "resource":
        return classify_category(service, resource_type)
    if kind == "category":
        return service or ""
    return ""
