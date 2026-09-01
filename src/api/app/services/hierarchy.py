"""Cloud resource hierarchy helpers (Azure / AWS / GCP)."""

from __future__ import annotations

import re
from typing import Any

from app.models import Connection, CostLineItem

def classify_category(service: str, resource_type: str = "") -> str:
    text = f"{service} {resource_type}".lower()
    if any(k in text for k in ("virtual machine", "compute", "aks", "kubernetes", "eks", "gke", "ec2", "ecs", "lambda", "app service", "functions", "cloud run", "container")):
        return "Compute"
    if any(k in text for k in ("storage", "blob", "disk", "ebs", "s3", "filestore", "backup", "glacier")):
        return "Storage"
    if any(k in text for k in ("sql", "cosmos", "database", "rds", "aurora", "dynamo", "spanner", "firestore", "cache", "redis")):
        return "Database"
    if any(k in text for k in ("bandwidth", "network", "vnet", "vpc", "gateway", "load balancer", "elb", "cdn", "ip", "nat", "dns")):
        return "Network"
    if any(k in text for k in ("key vault", "iam", "security", "firewall", "sentinel", "secret")):
        return "Security"
    if any(k in text for k in ("synapse", "bigquery", "analytics", "databricks", "monitor", "logging")):
        return "Analytics"
    return "Other"


KIND_LABELS = {
    "management_group": "Management group",
    "subscription": "Subscription",
    "account": "AWS account",
    "project": "GCP project",
    "resource_group": "Resource group",
    "resource": "Resource",
    "connection": "Connection",
}

_RG_RE = re.compile(r"resourcegroups/([^/]+)", re.I)
_SUB_RE = re.compile(r"subscriptions/([^/]+)", re.I)


def parse_resource_scope(resource_id: str, provider: str, account_id: str) -> dict[str, str]:
    text = resource_id or ""
    subscription = account_id or ""
    resource_group = ""
    sub_match = _SUB_RE.search(text)
    if sub_match:
        subscription = sub_match.group(1)
    rg_match = _RG_RE.search(text)
    if rg_match:
        resource_group = rg_match.group(1)
    elif provider == "azure" and "/rg-" in text.lower():
        parts = [p for p in text.split("/") if p]
        if len(parts) >= 2:
            resource_group = parts[-2]
    return {"account_id": subscription, "resource_group": resource_group}


def org_from_connection(connection: Connection) -> tuple[str, str]:
    config = connection.config or {}
    if connection.provider == "azure":
        scope = str(config.get("scope") or "")
        if config.get("scope_kind") == "management_group" and config.get("scope_value"):
            value = str(config["scope_value"])
            return value, connection.name or value
        if "managementgroups" in scope.lower():
            value = scope.rstrip("/").split("/")[-1]
            return value, connection.name or value
        tenant = str(config.get("tenant_id") or connection.name)
        return tenant, connection.name or tenant
    if connection.provider == "aws":
        payer = str(config.get("account_id") or connection.name)
        return payer, connection.name
    project = str(config.get("project_id") or connection.name)
    return project, connection.name


def account_kind(provider: str) -> str:
    if provider == "azure":
        return "subscription"
    if provider == "aws":
        return "account"
    return "project"


def account_kind_label(provider: str) -> str:
    return KIND_LABELS[account_kind(provider)]


def node_key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def parse_node_key(raw: str) -> tuple[str | None, str]:
    kind, sep, rest = raw.partition(":")
    if sep and kind in KIND_LABELS:
        return kind, rest
    return None, raw


def enrich_line(row: CostLineItem, connection: Connection | None) -> None:
    parsed = parse_resource_scope(row.resource_id, row.provider, row.account_id)
    if parsed["account_id"] and not row.account_id:
        row.account_id = parsed["account_id"]
    if parsed["resource_group"]:
        row.resource_group = parsed["resource_group"]
    if connection:
        org_id, org_name = org_from_connection(connection)
        if not row.org_id:
            row.org_id = org_id
        if not row.org_name or row.org_name == row.org_id:
            row.org_name = org_name


def build_tree(leaves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: dict[str, dict[str, Any]] = {}

    def ensure(store: dict[str, dict[str, Any]], key: str, **kwargs) -> dict[str, Any]:
        node = store.get(key)
        if node is None:
            node = {
                "key": key,
                "kind": kwargs["kind"],
                "label": kwargs["label"],
                "provider": kwargs["provider"],
                "path": kwargs["path"],
                "cost": 0.0,
                "prior_cost": 0.0,
                "currency": kwargs.get("currency") or "GBP",
                "service": kwargs.get("service") or "",
                "category": kwargs.get("category") or "",
                "children": {},
            }
            store[key] = node
        node["cost"] += kwargs.get("cost") or 0
        node["prior_cost"] += kwargs.get("prior_cost") or 0
        return node

    for leaf in leaves:
        provider = str(leaf.get("provider") or "")
        currency = str(leaf.get("currency") or "GBP")
        cost = float(leaf.get("cost") or 0)
        prior = float(leaf.get("prior_cost") or 0)
        org_id = str(leaf.get("org_id") or leaf.get("account_id") or "unknown")
        org_name = str(leaf.get("org_name") or org_id)
        account_id = str(leaf.get("account_id") or "")
        account_name = str(leaf.get("account_name") or account_id)
        resource_group = str(leaf.get("resource_group") or "")
        resource_id = str(leaf.get("key") or leaf.get("resource_id") or "")
        resource_name = str(leaf.get("label") or resource_id)
        service = str(leaf.get("service") or "")
        category = classify_category(service, str(leaf.get("resource_type") or ""))
        acct_kind = account_kind(provider)

        org = ensure(
            roots,
            node_key("management_group", org_id),
            kind="management_group",
            label=org_name,
            provider=provider,
            path=org_name,
            currency=currency,
            cost=cost,
            prior_cost=prior,
        )
        if not account_id:
            ensure(
                org["children"],
                node_key("resource", resource_id),
                kind="resource",
                label=resource_name,
                provider=provider,
                path=f"{org_name} / {resource_name}",
                currency=currency,
                cost=cost,
                prior_cost=prior,
                service=service,
                category=category,
            )
            continue
        account = ensure(
            org["children"],
            node_key(acct_kind, account_id),
            kind=acct_kind,
            label=account_name or account_id,
            provider=provider,
            path=f"{org_name} / {account_name or account_id}",
            currency=currency,
            cost=cost,
            prior_cost=prior,
        )
        parent = account
        parent_path = account["path"]
        if provider == "azure" and resource_group:
            parent = ensure(
                account["children"],
                node_key("resource_group", f"{account_id}/{resource_group}"),
                kind="resource_group",
                label=resource_group,
                provider=provider,
                path=f"{account['path']} / {resource_group}",
                currency=currency,
                cost=cost,
                prior_cost=prior,
            )
            parent_path = parent["path"]
        ensure(
            parent["children"],
            node_key("resource", resource_id),
            kind="resource",
            label=resource_name,
            provider=provider,
            path=f"{parent_path} / {resource_name}",
            currency=currency,
            cost=cost,
            prior_cost=prior,
            service=service,
            category=category,
        )

    def finalize(node: dict[str, Any]) -> dict[str, Any]:
        children = [finalize(child) for child in sorted(node["children"].values(), key=lambda item: item["cost"], reverse=True)]
        prior = node["prior_cost"]
        return {
            **{k: v for k, v in node.items() if k != "children"},
            "delta_pct": None if prior == 0 else round(((node["cost"] - prior) / prior) * 100, 1),
            "cost": round(node["cost"], 2),
            "prior_cost": round(prior, 2),
            "children": children,
        }

    return [finalize(node) for node in sorted(roots.values(), key=lambda item: item["cost"], reverse=True)]


def enrich_normalized(payload: dict[str, Any], provider: str, connection: Connection | None) -> dict[str, Any]:
    parsed = parse_resource_scope(str(payload.get("resource_id") or ""), provider, str(payload.get("account_id") or ""))
    if parsed["account_id"] and not payload.get("account_id"):
        payload["account_id"] = parsed["account_id"]
    payload["resource_group"] = parsed["resource_group"]
    if connection:
        org_id, org_name = org_from_connection(connection)
        payload["org_id"] = org_id
        payload["org_name"] = org_name
    else:
        payload.setdefault("org_id", "")
        payload.setdefault("org_name", "")
    return payload
