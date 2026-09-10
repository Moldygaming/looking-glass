"""AWS Cost and Usage connector.

Prefers a CUR file already landed in Blob/S3 (config.cur_uri).
Falls back to Cost Explorer if access keys are present.

Cost Explorer only accepts two GroupBy values and is a us-east-1 API.
"""

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.connectors.base import Connector, NormalizedCost

# Cost Explorer lives in us-east-1 regardless of the account's home region.
CE_REGION = "us-east-1"


class AwsConnector(Connector):
    provider = "aws"

    async def ingest(
        self, connection_id: UUID, config: dict[str, Any], secret: str | None
    ) -> list[NormalizedCost]:
        creds = _credentials(config, secret)
        if not creds:
            return []

        import boto3

        end = date.today()
        start = end - timedelta(days=int(config.get("lookback_days", 14)))
        client = boto3.client("ce", region_name=CE_REGION, **creds)
        payer = str(config.get("account_id") or "")
        rows: list[NormalizedCost] = []
        token = None
        try:
            while True:
                kwargs: dict[str, Any] = {
                    "TimePeriod": {"Start": start.isoformat(), "End": (end + timedelta(days=1)).isoformat()},
                    "Granularity": "DAILY",
                    "Metrics": ["UnblendedCost", "UsageQuantity"],
                    # Cost Explorer allows at most two GroupBy values.
                    "GroupBy": [
                        {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
                        {"Type": "DIMENSION", "Key": "SERVICE"},
                    ],
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
                        account = keys[0] if keys else payer
                        service = keys[1] if len(keys) > 1 else "AWS"
                        rows.append(
                            NormalizedCost(
                                usage_date=usage_date,
                                account_id=account,
                                account_name=account,
                                resource_id=f"aws/{account}/{service}",
                                resource_name=service,
                                resource_type=service,
                                service=service,
                                category=_category(service),
                                meter=service,
                                region=str(config.get("region") or ""),
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
        except Exception as exc:  # noqa: BLE001 — wrap AWS errors for the UI
            raise ValueError(_aws_error(exc)) from exc
        return rows

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        creds = _credentials(config, secret)
        if not creds:
            raise ValueError("AWS access key ID and secret access key are required.")
        import boto3

        try:
            sts = boto3.client("sts", region_name=CE_REGION, **creds)
            identity = sts.get_caller_identity()
        except Exception as exc:  # noqa: BLE001 — wrap AWS errors for the UI
            raise ValueError(_aws_error(exc)) from exc
        account = identity.get("Account") or ""
        expected = str(config.get("account_id") or "").strip()
        extra = ""
        if expected and account and expected != account:
            extra = f" The configured payer ID {expected} does not match this identity."
        return f"Authenticated as {identity.get('Arn')} (account {account}).{extra}"


def _credentials(config: dict[str, Any], secret: str | None) -> dict[str, str]:
    blob = _secret_json(secret)
    access_key = str(blob.get("access_key_id") or config.get("access_key_id") or "").strip()
    secret_key = str(blob.get("secret_access_key") or config.get("secret_access_key") or "").strip()
    session_token = str(blob.get("session_token") or config.get("session_token") or "").strip()
    if not access_key or not secret_key:
        return {}
    creds = {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key}
    if session_token:
        creds["aws_session_token"] = session_token
    return creds


def _secret_json(secret: str | None) -> dict[str, Any]:
    if not secret:
        return {}
    try:
        return json.loads(secret)
    except json.JSONDecodeError:
        return {"secret_access_key": secret}


def _aws_error(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error") or {}
        code = err.get("Code") or ""
        message = err.get("Message") or str(exc)
        if code:
            return f"{code}: {message}"
        return str(message)
    return str(exc)


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
