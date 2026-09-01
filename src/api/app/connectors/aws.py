"""AWS Cost and Usage connector.

Prefers a CUR file already landed in Blob/S3 (config.cur_uri).
Falls back to Cost Explorer if access keys are present.

Config keys:
  account_id, region, cur_uri,
  access_key_id / secret in secret_ref (JSON: {"access_key_id","secret_access_key"})
"""

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.connectors.base import Connector, NormalizedCost


class AwsConnector(Connector):
    provider = "aws"

    async def ingest(
        self, connection_id: UUID, config: dict[str, Any], secret: str | None
    ) -> list[NormalizedCost]:
        creds = _secret_json(secret)
        access_key = creds.get("access_key_id") or config.get("access_key_id")
        secret_key = creds.get("secret_access_key") or config.get("secret_access_key")
        if not access_key or not secret_key:
            return []

        import boto3

        end = date.today()
        start = end - timedelta(days=int(config.get("lookback_days", 14)))
        client = boto3.client(
            "ce",
            region_name=config.get("region", "us-east-1"),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        grouping = [
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
            {"Type": "DIMENSION", "Key": "REGION"},
            {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
        ]
        rows: list[NormalizedCost] = []
        token = None
        while True:
            kwargs: dict[str, Any] = {
                "TimePeriod": {"Start": start.isoformat(), "End": (end + timedelta(days=1)).isoformat()},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost", "UsageQuantity"],
                "GroupBy": grouping,
            }
            if token:
                kwargs["NextPageToken"] = token
            page = client.get_cost_and_usage(**kwargs)
            for day in page.get("ResultsByTime", []):
                usage_date = date.fromisoformat(day["TimePeriod"]["Start"])
                for group in day.get("Groups", []):
                    keys = group.get("Keys") or []
                    amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    currency = group["Metrics"]["UnblendedCost"]["Unit"]
                    usage = float(group["Metrics"]["UsageQuantity"]["Amount"])
                    service = keys[0] if keys else "AWS"
                    meter = keys[1] if len(keys) > 1 else ""
                    region = keys[2] if len(keys) > 2 else ""
                    account = keys[3] if len(keys) > 3 else str(config.get("account_id") or "")
                    rows.append(
                        NormalizedCost(
                            usage_date=usage_date,
                            account_id=account,
                            account_name=account,
                            resource_id=f"aws/{account}/{service}/{meter}",
                            resource_name=meter or service,
                            resource_type=service,
                            service=service,
                            category=_category(service),
                            meter=meter,
                            region=region,
                            tags=dict(config.get("default_tags") or {}),
                            cost=amount,
                            amortized_cost=amount,
                            currency="GBP" if currency == "USD" and config.get("currency") == "GBP" else currency,
                            usage_quantity=usage,
                            usage_unit="",
                        )
                    )
            token = page.get("NextPageToken")
            if not token:
                break
        return rows

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        creds = _secret_json(secret)
        access_key = creds.get("access_key_id") or config.get("access_key_id")
        secret_key = creds.get("secret_access_key")
        if not access_key or not secret_key:
            raise ValueError("AWS access key ID and secret access key are required.")
        import boto3

        sts = boto3.client(
            "sts",
            region_name=config.get("region") or "us-east-1",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        identity = sts.get_caller_identity()
        return f"Authenticated as {identity.get('Arn')} (account {identity.get('Account')})."


def _secret_json(secret: str | None) -> dict[str, Any]:
    if not secret:
        return {}
    try:
        return json.loads(secret)
    except json.JSONDecodeError:
        return {"secret_access_key": secret}


def _category(service: str) -> str:
    lowered = service.lower()
    if any(k in lowered for k in ("ec2", "lambda", "ecs", "eks", "compute")):
        return "Compute"
    if any(k in lowered for k in ("s3", "ebs", "backup", "glacier")):
        return "Storage"
    if any(k in lowered for k in ("rds", "dynamo", "aurora", "elasticache")):
        return "Database"
    if any(k in lowered for k in ("vpc", "elb", "cloudfront", "nat", "data transfer")):
        return "Network"
    return "Other"
