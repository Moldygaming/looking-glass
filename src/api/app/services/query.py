from datetime import date, timedelta

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.acl import cost_acl
from app.models import CostLineItem
from app.schemas import CostQuery, CurrentUser


def normalize_granularity(value: str | None) -> str:
    raw = (value or "day").lower()
    if raw in {"week", "weekly"}:
        return "week"
    if raw in {"month", "monthly"}:
        return "month"
    return "day"


def default_days(granularity: str) -> int:
    return {"day": 30, "week": 84, "month": 365}[normalize_granularity(granularity)]


def extra_lookback_days(granularity: str) -> int:
    return {"day": 1, "week": 7, "month": 31}[normalize_granularity(granularity)]


def bucket_expr(granularity: str) -> ColumnElement:
    grain = normalize_granularity(granularity)
    if grain == "week":
        return cast(func.date_trunc("week", CostLineItem.usage_date), Date)
    if grain == "month":
        return cast(func.date_trunc("month", CostLineItem.usage_date), Date)
    return CostLineItem.usage_date


def period(from_date: date | None, to_date: date | None, days: int = 30) -> tuple[date, date]:
    end = to_date or date.today()
    start = from_date or (end - timedelta(days=days - 1))
    return start, end


def apply_cost_filters(stmt: Select, user: CurrentUser, q: CostQuery) -> Select:
    stmt = stmt.where(cost_acl(user))
    start, end = period(q.from_date, q.to_date)
    stmt = stmt.where(CostLineItem.usage_date >= start, CostLineItem.usage_date <= end)
    if q.provider:
        stmt = stmt.where(CostLineItem.provider == q.provider)
    if q.connection_id:
        stmt = stmt.where(CostLineItem.connection_id == q.connection_id)
    if q.account_id:
        stmt = stmt.where(CostLineItem.account_id == q.account_id)
    if q.service:
        stmt = stmt.where(CostLineItem.service == q.service)
    if q.region:
        stmt = stmt.where(CostLineItem.region == q.region)
    if q.tag_key and q.tag_value:
        stmt = stmt.where(CostLineItem.tags[q.tag_key].astext == q.tag_value)
    if q.q:
        like = f"%{q.q}%"
        stmt = stmt.where(
            CostLineItem.resource_name.ilike(like)
            | CostLineItem.account_name.ilike(like)
            | CostLineItem.account_id.ilike(like)
            | CostLineItem.resource_group.ilike(like)
            | CostLineItem.org_name.ilike(like)
            | CostLineItem.service.ilike(like)
            | CostLineItem.meter.ilike(like)
            | CostLineItem.resource_id.ilike(like)
        )
    if q.keys:
        stmt = stmt.where(group_expr(q.group_by).in_(q.keys))
    return stmt


def group_expr(group_by: str):
    mapping = {
        "provider": CostLineItem.provider,
        "connection": CostLineItem.connection_id,
        "account": CostLineItem.account_id,
        "subscription": CostLineItem.account_id,
        "project": CostLineItem.account_id,
        "management_group": CostLineItem.org_id,
        "resource_group": func.concat(CostLineItem.account_id, "/", CostLineItem.resource_group),
        "service": CostLineItem.service,
        "category": CostLineItem.category,
        "region": CostLineItem.region,
        "resource": CostLineItem.resource_id,
        "resource_name": CostLineItem.resource_name,
        "meter": CostLineItem.meter,
        "resource_type": CostLineItem.resource_type,
    }
    if group_by.startswith("tag:"):
        key = group_by.split(":", 1)[1]
        return CostLineItem.tags[key].astext
    return mapping.get(group_by, CostLineItem.service)


def label_expr(group_by: str):
    labels = {
        "resource": CostLineItem.resource_name,
        "account": CostLineItem.account_name,
        "subscription": CostLineItem.account_name,
        "project": CostLineItem.account_name,
        "management_group": func.nullif(CostLineItem.org_name, ""),
        "resource_group": func.nullif(CostLineItem.resource_group, ""),
        "connection": CostLineItem.provider,
    }
    if group_by in labels and labels[group_by] is not None:
        return func.coalesce(labels[group_by], group_expr(group_by))
    return group_expr(group_by)


async def sum_cost(session: AsyncSession, stmt: Select) -> float:
    total = await session.scalar(select(func.coalesce(func.sum(stmt.subquery().c.cost), 0)))
    return float(total or 0)
