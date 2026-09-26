import calendar
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_privilege
from app.db import get_session
from app.models import Connection, CostLineItem, Recommendation
from app.schemas import (
    BreakdownRow,
    CostObjectFocus,
    CostObjectOut,
    CostObjectPage,
    CostPoint,
    CostQuery,
    CostSummary,
    CurrentUser,
    DimensionCatalogOut,
    DimensionOut,
    HierarchyNode,
    HierarchyPresetOut,
    LineItemOut,
    NamedSeries,
    RollupRow,
    SeriesPoint,
)
from app.services.hierarchy import build_tree, classify_category
from app.services.objects import (
    DEFAULT_PATH,
    PRESETS,
    dimension_payload,
    display_label,
    kind_label,
    next_kind,
    normalize_path,
    object_category,
    object_key,
    parse_focus,
    parse_object_key,
)
from app.services.query import (
    apply_cost_filters,
    bucket_expr,
    default_days,
    extra_lookback_days,
    group_expr,
    label_expr,
    normalize_granularity,
    period,
)

router = APIRouter(
    prefix="/costs",
    tags=["costs"],
    dependencies=[Depends(require_privilege("finops.costs.read"))],
)


def _query(
    from_date=None,
    to_date=None,
    provider=None,
    connection_id=None,
    account_id=None,
    service=None,
    region=None,
    group_by="service",
    tag_key=None,
    tag_value=None,
    q=None,
    keys=None,
    focus=None,
    path=None,
    granularity="day",
    limit=100,
    offset=0,
) -> CostQuery:
    grain = normalize_granularity(granularity)
    start, end = period(from_date, to_date, days=default_days(grain))
    key_list = None
    if isinstance(keys, str):
        key_list = [part.strip() for part in keys.split(",") if part.strip()]
    elif keys:
        key_list = list(keys)
    if isinstance(focus, str):
        focus_list = [part.strip() for part in focus.split("|") if part.strip()]
    elif focus:
        focus_list = list(focus)
    else:
        focus_list = []
    return CostQuery(
        from_date=start,
        to_date=end,
        provider=provider,
        connection_id=connection_id,
        account_id=account_id,
        service=service,
        region=region,
        group_by=group_by,
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        keys=key_list,
        focus=focus_list,
        path=normalize_path(path),
        granularity=grain,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=CostSummary)
async def summary(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    tag_key: str | None = None,
    tag_value: str | None = None,
    focus: str | None = None,
):
    q = _query(from_date, to_date, provider, connection_id, tag_key=tag_key, tag_value=tag_value, focus=focus)
    start, end = period(q.from_date, q.to_date)
    length = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length - 1)

    filtered = apply_cost_filters(select(CostLineItem), user, q)
    period_cost = float(
        await session.scalar(select(func.coalesce(func.sum(filtered.subquery().c.cost), 0))) or 0
    )
    prior_q = CostQuery(
        from_date=prior_start,
        to_date=prior_end,
        provider=provider,
        connection_id=connection_id,
        tag_key=tag_key,
        tag_value=tag_value,
    )
    prior_filtered = apply_cost_filters(select(CostLineItem), user, prior_q)
    prior_cost = float(
        await session.scalar(select(func.coalesce(func.sum(prior_filtered.subquery().c.cost), 0))) or 0
    )
    delta = 0.0 if prior_cost == 0 else ((period_cost - prior_cost) / prior_cost) * 100

    series_stmt = (
        apply_cost_filters(
            select(
                CostLineItem.usage_date,
                func.sum(CostLineItem.cost).label("cost"),
                func.sum(CostLineItem.amortized_cost).label("amortized_cost"),
            ),
            user,
            q,
        )
        .group_by(CostLineItem.usage_date)
        .order_by(CostLineItem.usage_date)
    )
    series_rows = (await session.execute(series_stmt)).all()
    series = [
        CostPoint(date=r.usage_date, cost=float(r.cost), amortized_cost=float(r.amortized_cost))
        for r in series_rows
    ]
    daily_avg = period_cost / max(length, 1)
    forecast = daily_avg * calendar.monthrange(end.year, end.month)[1]

    provider_stmt = apply_cost_filters(
        select(
            CostLineItem.provider,
            func.sum(CostLineItem.cost).label("cost"),
            func.sum(CostLineItem.amortized_cost).label("amortized"),
        ),
        user,
        q,
    ).group_by(CostLineItem.provider)
    provider_rows = (await session.execute(provider_stmt)).all()
    by_provider = _shares(provider_rows, period_cost, key_attr="provider")

    untagged_stmt = apply_cost_filters(select(func.coalesce(func.sum(CostLineItem.cost), 0)), user, q).where(
        or_(CostLineItem.tags["team"].astext.is_(None), CostLineItem.tags["team"].astext == "")
    )
    untagged = float(await session.scalar(untagged_stmt) or 0)

    rec_stmt = select(
        func.count(Recommendation.id),
        func.coalesce(func.sum(Recommendation.monthly_savings), 0),
    ).where(Recommendation.status == "open")
    if not user.is_admin:
        from app.acl import recommendation_acl

        rec_stmt = rec_stmt.where(recommendation_acl(user))
    rec_count, rec_save = (await session.execute(rec_stmt)).one()

    connections = await session.scalar(select(func.count()).select_from(Connection))
    currency = await session.scalar(apply_cost_filters(select(CostLineItem.currency), user, q).limit(1))

    return CostSummary(
        currency=currency or "GBP",
        period_cost=round(period_cost, 2),
        prior_period_cost=round(prior_cost, 2),
        delta_pct=round(delta, 1),
        forecast_month=round(forecast, 2),
        open_recommendations=int(rec_count or 0),
        potential_monthly_savings=round(float(rec_save or 0), 2),
        untagged_cost=round(untagged, 2),
        connections=int(connections or 0),
        series=series,
        by_provider=by_provider,
    )


@router.get("/series", response_model=list[CostPoint])
async def series(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    group_by: str = "service",
    granularity: str = "day",
):
    q = _query(from_date, to_date, provider, connection_id, group_by=group_by, granularity=granularity)
    bucket = bucket_expr(q.granularity)
    stmt = (
        apply_cost_filters(
            select(
                bucket.label("period_start"),
                func.sum(CostLineItem.cost).label("cost"),
                func.sum(CostLineItem.amortized_cost).label("amortized_cost"),
            ),
            user,
            q,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        CostPoint(date=r.period_start, cost=float(r.cost), amortized_cost=float(r.amortized_cost))
        for r in (await session.execute(stmt)).all()
    ]


@router.get("/breakdown", response_model=list[BreakdownRow])
async def breakdown(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    group_by: str = Query(default="service"),
    tag_key: str | None = None,
    tag_value: str | None = None,
    focus: str | None = None,
    q: str | None = None,
    limit: int = 12,
):
    q = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        group_by=group_by,
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        focus=focus,
        limit=limit,
    )
    key = group_expr(group_by)
    label = label_expr(group_by)
    stmt = (
        apply_cost_filters(
            select(
                key.label("key"),
                label.label("label"),
                func.sum(CostLineItem.cost).label("cost"),
                func.sum(CostLineItem.amortized_cost).label("amortized"),
            ),
            user,
            q,
        )
        .group_by(key, label)
        .order_by(func.sum(CostLineItem.cost).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    total = sum(float(r.cost) for r in rows) or 1
    return [
        BreakdownRow(
            key=str(r.key or "untagged"),
            label=str(r.label or r.key or "untagged"),
            cost=round(float(r.cost), 2),
            amortized_cost=round(float(r.amortized), 2),
            share=round(float(r.cost) / total, 4),
        )
        for r in rows
    ]


@router.get("/rollups", response_model=list[RollupRow])
async def rollups(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    group_by: str = Query(default="resource"),
    granularity: str = Query(default="day"),
    tag_key: str | None = None,
    tag_value: str | None = None,
    q: str | None = None,
    keys: str | None = None,
    limit: int = 80,
):
    grain = normalize_granularity(granularity)
    query = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        group_by=group_by,
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        keys=keys,
        granularity=grain,
        limit=limit,
    )
    visible_start, visible_end = query.from_date, query.to_date
    buckets = await _bucket_rows(session, user, query, grain)
    latest: dict[str, RollupRow] = {}
    for row in buckets:
        if row.period_start < visible_start or row.period_start > visible_end:
            continue
        current = latest.get(row.key)
        if current is None or row.period_start >= current.period_start:
            latest[row.key] = row
    ranked = sorted(latest.values(), key=lambda item: item.cost, reverse=True)
    return ranked[: min(limit, 200)]


@router.get("/tree", response_model=list[HierarchyNode])
async def tree(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    granularity: str = Query(default="day"),
    tag_key: str | None = None,
    tag_value: str | None = None,
    q: str | None = None,
    focus: str | None = None,
    path: str | None = None,
):
    grain = normalize_granularity(granularity)
    query = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        group_by="resource",
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        focus=focus,
        path=path,
        granularity=grain,
        limit=500,
    )
    visible_start, visible_end = query.from_date, query.to_date
    buckets = await _bucket_rows(session, user, query, grain)
    latest: dict[str, RollupRow] = {}
    for row in buckets:
        if row.period_start < visible_start or row.period_start > visible_end:
            continue
        current = latest.get(row.key)
        if current is None or row.period_start >= current.period_start:
            latest[row.key] = row
    return [HierarchyNode.model_validate(node) for node in build_tree([row.model_dump() for row in latest.values()])]


@router.get("/compare", response_model=list[NamedSeries])
async def compare(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    group_by: str = Query(default="resource"),
    granularity: str = Query(default="day"),
    tag_key: str | None = None,
    tag_value: str | None = None,
    q: str | None = None,
    keys: str | None = None,
    focus: str | None = None,
    limit: int = 8,
):
    grain = normalize_granularity(granularity)
    parsed: list[tuple[str, str, str]] = []
    for raw in (keys or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        kind, value = parse_object_key(raw)
        parsed.append((kind or group_by, value, raw))
    if parsed and len({item[0] for item in parsed}) > 1:
        series: list[NamedSeries] = []
        for kind, value, raw in parsed[:8]:
            part = await _compare_series(
                session,
                user,
                _query(
                    from_date,
                    to_date,
                    provider,
                    connection_id,
                    group_by=kind,
                    tag_key=tag_key,
                    tag_value=tag_value,
                    q=q,
                    keys=value,
                    focus=focus,
                    granularity=grain,
                    limit=limit,
                ),
                grain,
            )
            for item in part:
                item.key = raw
                item.kind = kind
                item.category = item.category or classify_category(item.label)
                item.label = f"{kind_label(kind)} · {item.label}"
            series.extend(part)
        return series[:8]
    if parsed:
        group_by = parsed[0][0]
        keys = ",".join(item[1] for item in parsed)
    query = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        group_by=group_by,
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        keys=keys,
        focus=focus,
        granularity=grain,
        limit=limit,
    )
    series = await _compare_series(session, user, query, grain)
    for item in series:
        item.kind = group_by
    return series[: min(limit, 8)]


@router.get("/line-items")
async def line_items(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    account_id: str | None = None,
    service: str | None = None,
    region: str | None = None,
    tag_key: str | None = None,
    tag_value: str | None = None,
    q: str | None = None,
    focus: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    query = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        account_id,
        service,
        region,
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        focus=focus,
        limit=limit,
        offset=offset,
    )
    filtered = apply_cost_filters(select(CostLineItem), user, query)
    total = await session.scalar(select(func.count()).select_from(filtered.subquery()))
    rows = (
        await session.execute(
            filtered.order_by(CostLineItem.usage_date.desc(), CostLineItem.cost.desc())
            .limit(min(limit, 200))
            .offset(offset)
        )
    ).scalars().all()
    return {
        "total": int(total or 0),
        "items": [LineItemOut.model_validate(r, from_attributes=True) for r in rows],
    }


@router.get("/dimensions", response_model=DimensionCatalogOut)
async def list_dimensions(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    tags = await _tag_map(session, user)
    return DimensionCatalogOut(
        dimensions=[DimensionOut(**item) for item in dimension_payload(list(tags.keys()))],
        presets=[HierarchyPresetOut(**item) for item in PRESETS],
        default_path=list(DEFAULT_PATH),
    )


@router.get("/objects", response_model=CostObjectPage)
async def list_objects(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    from_date=None,
    to_date=None,
    provider: str | None = None,
    connection_id=None,
    path: str | None = None,
    focus: str | None = None,
    granularity: str = Query(default="day"),
    tag_key: str | None = None,
    tag_value: str | None = None,
    q: str | None = None,
    limit: int = 200,
):
    grain = normalize_granularity(granularity)
    levels = normalize_path(path)
    focus_pairs = parse_focus(focus)
    child_kind = next_kind(levels, focus_pairs)
    query = _query(
        from_date,
        to_date,
        provider,
        connection_id,
        group_by=child_kind or "service",
        tag_key=tag_key,
        tag_value=tag_value,
        q=q,
        focus=focus,
        path=levels,
        granularity=grain,
        limit=limit,
    )
    start, end = period(query.from_date, query.to_date)
    length = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length - 1)

    current_rows = await _grouped_totals(session, user, query)
    prior_query = query.model_copy(deep=True)
    prior_query.from_date = prior_start
    prior_query.to_date = prior_end
    prior_rows = await _grouped_totals(session, user, prior_query)
    prior_by_key = {row["key"]: row["cost"] for row in prior_rows}

    names = await _connection_names(session) if child_kind == "connection" else {}
    period_cost = sum(row["cost"] for row in current_rows)
    prior_period = sum(prior_by_key.values())
    following = next_kind(levels, focus_pairs + ([(child_kind, "")] if child_kind else []))
    leaf = following is None or following == child_kind
    objects: list[CostObjectOut] = []
    for row in current_rows[: min(max(limit, 1), 400)]:
        value = row["key"]
        label = row["label"]
        if child_kind == "connection":
            label = names.get(value, label)
        label = display_label(child_kind or "service", value, label)
        prior_cost = float(prior_by_key.get(value, 0))
        cost = float(row["cost"])
        delta = None if prior_cost == 0 else round(((cost - prior_cost) / prior_cost) * 100, 1)
        objects.append(
            CostObjectOut(
                key=object_key(child_kind or "service", value),
                kind=child_kind or "service",
                label=label,
                provider=row["provider"],
                path=" / ".join([*[item[1] or display_label(item[0], item[1]) for item in focus_pairs], label]),
                cost=round(cost, 2),
                prior_cost=round(prior_cost, 2),
                delta_pct=delta,
                share=round(cost / period_cost, 4) if period_cost else 0,
                currency=row["currency"],
                service=row["service"],
                category=object_category(child_kind or "", row["service"], row["resource_type"]),
                has_children=not leaf,
            )
        )

    focus_out: list[CostObjectFocus] = []
    for kind, value in focus_pairs:
        focus_out.append(
            CostObjectFocus(
                key=object_key(kind, value),
                kind=kind,
                label=display_label(kind, value, names.get(value) if kind == "connection" else value),
            )
        )

    delta_pct = None if prior_period == 0 else round(((period_cost - prior_period) / prior_period) * 100, 1)
    currency = objects[0].currency if objects else "GBP"
    return CostObjectPage(
        path=levels,
        current_kind=child_kind,
        next_kind=None if leaf else following,
        focus=focus_out,
        objects=objects,
        currency=currency,
        period_cost=round(period_cost, 2),
        prior_period_cost=round(prior_period, 2),
        delta_pct=delta_pct,
        object_count=len(objects),
    )


@router.get("/tags")
async def tag_keys(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    return await _tag_map(session, user)


async def _compare_series(
    session: AsyncSession, user: CurrentUser, query: CostQuery, grain: str
) -> list[NamedSeries]:
    visible_start, visible_end = query.from_date, query.to_date
    buckets = await _bucket_rows(session, user, query, grain)
    if not query.keys:
        totals: dict[str, float] = defaultdict(float)
        for row in buckets:
            if visible_start <= row.period_start <= visible_end:
                totals[row.key] += row.cost
        keep = {key for key, _ in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]}
        buckets = [row for row in buckets if row.key in keep]
    grouped: dict[str, list[RollupRow]] = defaultdict(list)
    for row in buckets:
        grouped[row.key].append(row)
    series: list[NamedSeries] = []
    for key, rows in grouped.items():
        visible = [row for row in rows if visible_start <= row.period_start <= visible_end]
        if not visible:
            continue
        latest = max(visible, key=lambda item: item.period_start)
        series.append(
            NamedSeries(
                key=key,
                label=latest.label,
                kind=query.group_by,
                category=classify_category(latest.service),
                cost=latest.cost,
                prior_cost=latest.prior_cost,
                delta_pct=latest.delta_pct,
                points=[
                    SeriesPoint(date=row.period_start, cost=row.cost, amortized_cost=row.cost)
                    for row in sorted(visible, key=lambda item: item.period_start)
                ],
            )
        )
    series.sort(key=lambda item: item.cost, reverse=True)
    return series


async def _bucket_rows(
    session: AsyncSession, user: CurrentUser, query: CostQuery, granularity: str
) -> list[RollupRow]:
    lookback = extra_lookback_days(granularity)
    extended = query.model_copy(deep=True)
    if extended.from_date:
        extended.from_date = extended.from_date - timedelta(days=lookback)
    bucket = bucket_expr(granularity)
    key = group_expr(query.group_by)
    label = label_expr(query.group_by)
    stmt = apply_cost_filters(
        select(
            key.label("key"),
            label.label("label"),
            func.min(CostLineItem.provider).label("provider"),
            func.min(CostLineItem.account_id).label("account_id"),
            func.min(CostLineItem.account_name).label("account_name"),
            func.min(CostLineItem.resource_group).label("resource_group"),
            func.min(CostLineItem.org_id).label("org_id"),
            func.min(CostLineItem.org_name).label("org_name"),
            func.min(CostLineItem.service).label("service"),
            func.min(CostLineItem.currency).label("currency"),
            bucket.label("period_start"),
            func.sum(CostLineItem.cost).label("cost"),
        ),
        user,
        extended,
    ).group_by(key, label, bucket)
    raw = (await session.execute(stmt)).all()
    by_key: dict[str, list] = defaultdict(list)
    for row in raw:
        by_key[str(row.key or "untagged")].append(row)
    result: list[RollupRow] = []
    for key_value, rows in by_key.items():
        ordered = sorted(rows, key=lambda item: item.period_start)
        previous_cost = 0.0
        for row in ordered:
            cost = float(row.cost or 0)
            delta = None if previous_cost == 0 else round(((cost - previous_cost) / previous_cost) * 100, 1)
            period_start = row.period_start
            if hasattr(period_start, "date") and callable(period_start.date):
                period_start = period_start.date()
            elif not isinstance(period_start, date):
                period_start = date.fromisoformat(str(period_start)[:10])
            result.append(
                RollupRow(
                    key=key_value,
                    label=str(row.label or key_value),
                    provider=str(row.provider or ""),
                    account_id=str(row.account_id or ""),
                    account_name=str(row.account_name or ""),
                    resource_group=str(row.resource_group or ""),
                    org_id=str(row.org_id or ""),
                    org_name=str(row.org_name or ""),
                    service=str(row.service or ""),
                    period_start=period_start,
                    cost=round(cost, 2),
                    prior_cost=round(previous_cost, 2),
                    delta_pct=delta,
                    currency=str(row.currency or "GBP"),
                )
            )
            previous_cost = cost
    return result


async def _grouped_totals(session: AsyncSession, user: CurrentUser, query: CostQuery) -> list[dict]:
    kind = query.group_by or "service"
    key = group_expr(kind)
    label = label_expr(kind)
    stmt = (
        apply_cost_filters(
            select(
                key.label("key"),
                label.label("label"),
                func.min(CostLineItem.provider).label("provider"),
                func.min(CostLineItem.service).label("service"),
                func.min(CostLineItem.resource_type).label("resource_type"),
                func.min(CostLineItem.currency).label("currency"),
                func.sum(CostLineItem.cost).label("cost"),
            ),
            user,
            query,
        )
        .group_by(key, label)
        .order_by(func.sum(CostLineItem.cost).desc())
        .limit(400)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "key": str(row.key or ""),
            "label": str(row.label or row.key or ""),
            "provider": str(row.provider or ""),
            "service": str(row.service or ""),
            "resource_type": str(row.resource_type or ""),
            "currency": str(row.currency or "GBP"),
            "cost": float(row.cost or 0),
        }
        for row in rows
    ]


async def _connection_names(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Connection.id, Connection.name))).all()
    return {str(row.id): row.name for row in rows}


async def _tag_map(session: AsyncSession, user: CurrentUser) -> dict[str, list[str]]:
    stmt = apply_cost_filters(select(CostLineItem.tags), user, _query())
    tags: dict[str, set[str]] = {}
    for (blob,) in (await session.execute(stmt.limit(4000))).all():
        for key, value in (blob or {}).items():
            tags.setdefault(key, set()).add(str(value))
    return {key: sorted(values) for key, values in sorted(tags.items())}


def _shares(rows, total: float, key_attr: str) -> list[BreakdownRow]:
    denom = total or 1
    return [
        BreakdownRow(
            key=str(getattr(r, key_attr)),
            label=str(getattr(r, key_attr)),
            cost=round(float(r.cost), 2),
            amortized_cost=round(float(getattr(r, "amortized", r.cost)), 2),
            share=round(float(r.cost) / denom, 4),
        )
        for r in rows
    ]
