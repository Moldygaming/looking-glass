import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.aws import AwsConnector
from app.connectors.azure import AzureConnector
from app.connectors.base import NormalizedCost
from app.connectors.gcp import GcpConnector
from app.models import Connection, CostLineItem
from app.services.hierarchy import org_from_connection, parse_resource_scope

SECRET_CONFIG_KEYS = {
    "client_secret",
    "access_key_id",
    "secret_access_key",
    "service_account_json",
}

CONNECTORS = {
    "azure": AzureConnector(),
    "aws": AwsConnector(),
    "gcp": GcpConnector(),
}


async def run_connection_ingest(session: AsyncSession, connection_id: UUID) -> int:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        return 0
    connector = CONNECTORS.get(connection.provider)
    if connector is None:
        connection.status = "error"
        connection.last_error = f"Unknown provider {connection.provider}"
        await session.commit()
        return 0
    if not _has_live_credentials(connection):
        return 0
    try:
        rows = await connector.ingest(
            connection.id, public_config(connection.config or {}), connector_secret(connection)
        )
        written = await persist_costs(session, connection, rows)
        connection.status = "connected"
        connection.last_error = None
        connection.last_ingest_at = datetime.now(UTC)
        await session.commit()
        return written
    except Exception as exc:  # noqa: BLE001 — surface connector errors on the connection record
        await session.rollback()
        connection = await session.get(Connection, connection_id)
        if connection is not None:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            await session.commit()
        raise


async def persist_costs(session: AsyncSession, connection: Connection, rows: list[NormalizedCost]) -> int:
    if not rows:
        return 0
    dates = {row.usage_date for row in rows}
    await session.execute(
        delete(CostLineItem).where(
            CostLineItem.connection_id == connection.id,
            CostLineItem.usage_date.in_(dates),
        )
    )
    org_id, org_name = org_from_connection(connection)
    for row in rows:
        parsed = parse_resource_scope(row.resource_id, connection.provider, row.account_id)
        session.add(
            CostLineItem(
                usage_date=row.usage_date,
                connection_id=connection.id,
                provider=connection.provider,
                account_id=parsed["account_id"] or row.account_id,
                account_name=row.account_name,
                resource_group=row.resource_group or parsed["resource_group"],
                org_id=row.org_id or org_id,
                org_name=row.org_name or org_name,
                resource_id=row.resource_id,
                resource_name=row.resource_name,
                resource_type=row.resource_type,
                service=row.service,
                category=row.category,
                meter=row.meter,
                region=row.region,
                tags=row.tags,
                cost=row.cost,
                amortized_cost=row.amortized_cost,
                currency=row.currency,
                usage_quantity=row.usage_quantity,
                usage_unit=row.usage_unit,
            )
        )
    return len(rows)


def public_config(config: dict | None) -> dict:
    return {k: v for k, v in (config or {}).items() if k not in SECRET_CONFIG_KEYS}


def merge_secrets(existing: dict | None, incoming: dict | None) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value is None or value == "":
            continue
        merged[key] = value
    return merged


def credentials_configured(connection: Connection) -> bool:
    return _has_live_credentials(connection)


def connector_secret(connection: Connection) -> str | None:
    secrets = connection.secrets or {}
    config = connection.config or {}
    if connection.provider == "azure":
        return secrets.get("client_secret") or config.get("client_secret")
    if connection.provider == "aws":
        payload = {
            "access_key_id": secrets.get("access_key_id") or config.get("access_key_id"),
            "secret_access_key": secrets.get("secret_access_key") or config.get("secret_access_key"),
        }
        if not payload["access_key_id"] and not payload["secret_access_key"]:
            return None
        return json.dumps(payload)
    if connection.provider == "gcp":
        return secrets.get("service_account_json") or config.get("service_account_json")
    return None


def _has_live_credentials(connection: Connection) -> bool:
    config = connection.config or {}
    secrets = connection.secrets or {}
    if connection.provider == "azure":
        return bool(
            config.get("tenant_id")
            and config.get("client_id")
            and config.get("scope")
            and (secrets.get("client_secret") or config.get("client_secret"))
        )
    if connection.provider == "aws":
        return bool(
            (secrets.get("access_key_id") or config.get("access_key_id"))
            and (secrets.get("secret_access_key") or config.get("secret_access_key"))
        )
    if connection.provider == "gcp":
        return bool(config.get("billing_table") and (secrets.get("service_account_json") or config.get("service_account_json")))
    return False


async def test_connection(connection: Connection) -> str:
    connector = CONNECTORS.get(connection.provider)
    if connector is None:
        raise ValueError(f"Unknown provider {connection.provider}")
    return await connector.test(public_config(connection.config or {}), connector_secret(connection))


async def ingest_all(session: AsyncSession) -> dict[str, int]:
    ids = (await session.execute(select(Connection.id))).scalars().all()
    results: dict[str, int] = {}
    for connection_id in ids:
        results[str(connection_id)] = await run_connection_ingest(session, connection_id)
    return results
