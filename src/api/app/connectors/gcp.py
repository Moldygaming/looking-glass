"""GCP Cloud Billing connector.

Reads a BigQuery billing export when `billing_table` is set
(project.dataset.table). Service account JSON lives in secret_ref.

Config keys:
  billing_table, project_id, lookback_days
"""

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.connectors.base import Connector, NormalizedCost


class GcpConnector(Connector):
    provider = "gcp"

    async def ingest(
        self, connection_id: UUID, config: dict[str, Any], secret: str | None
    ) -> list[NormalizedCost]:
        table = config.get("billing_table")
        if not table or not secret:
            return []

        from google.cloud import bigquery
        from google.oauth2 import service_account

        info = json.loads(secret)
        credentials = service_account.Credentials.from_service_account_info(info)
        client = bigquery.Client(project=info.get("project_id") or config.get("project_id"), credentials=credentials)
        end = date.today()
        start = end - timedelta(days=int(config.get("lookback_days", 14)))
        sql = f"""
            SELECT
              DATE(usage_start_time) AS usage_date,
              project.id AS account_id,
              project.name AS account_name,
              resource.name AS resource_name,
              resource.global_name AS resource_id,
              service.description AS service,
              sku.description AS meter,
              location.location AS region,
              currency,
              SUM(cost) AS cost,
              SUM(usage.amount) AS usage_quantity,
              ANY_VALUE(usage.unit) AS usage_unit
            FROM `{table}`
            WHERE DATE(usage_start_time) BETWEEN @start AND @end
            GROUP BY 1,2,3,4,5,6,7,8,9
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start", "DATE", start.isoformat()),
                bigquery.ScalarQueryParameter("end", "DATE", end.isoformat()),
            ]
        )
        rows: list[NormalizedCost] = []
        for row in client.query(sql, job_config=job_config).result():
            service = row["service"] or "GCP"
            rows.append(
                NormalizedCost(
                    usage_date=row["usage_date"],
                    account_id=row["account_id"] or "",
                    account_name=row["account_name"] or row["account_id"] or "",
                    resource_id=row["resource_id"] or row["resource_name"] or service,
                    resource_name=row["resource_name"] or service,
                    resource_type=service,
                    service=service,
                    category=_category(service),
                    meter=row["meter"] or "",
                    region=row["region"] or "",
                    tags=dict(config.get("default_tags") or {}),
                    cost=float(row["cost"] or 0),
                    amortized_cost=float(row["cost"] or 0),
                    currency=row["currency"] or "GBP",
                    usage_quantity=float(row["usage_quantity"] or 0),
                    usage_unit=row["usage_unit"] or "",
                )
            )
        return rows

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        if not config.get("billing_table"):
            raise ValueError("BigQuery billing export table is required (project.dataset.table).")
        if not secret:
            raise ValueError("Service account JSON is required.")
        info = json.loads(secret)
        email = info.get("client_email") or "service account"
        project = info.get("project_id") or config.get("project_id") or "unknown project"
        return f"Parsed credentials for {email} in {project}."


def _category(service: str) -> str:
    lowered = service.lower()
    if any(k in lowered for k in ("compute", "gke", "run", "functions", "gce")):
        return "Compute"
    if any(k in lowered for k in ("storage", "filestore", "gcs")):
        return "Storage"
    if any(k in lowered for k in ("sql", "spanner", "bigquery", "firestore", "memorystore")):
        return "Database"
    if any(k in lowered for k in ("vpc", "network", "load balancing", "cloud cdn")):
        return "Network"
    return "Other"
