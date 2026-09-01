from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLineItem, Recommendation

IDLE_TYPES = {"Virtual Machine", "EC2 Instance", "Compute Engine VM"}
DISK_TYPES = {"Managed Disk", "EBS Volume", "Persistent Disk"}
IP_TYPES = {"Public IP", "Elastic IP", "External IP"}


async def refresh_recommendations(session: AsyncSession) -> int:
    end = date.today()
    start = end - timedelta(days=14)

    rows = await session.execute(
        select(
            CostLineItem.connection_id,
            CostLineItem.provider,
            CostLineItem.account_id,
            CostLineItem.resource_id,
            CostLineItem.resource_name,
            CostLineItem.resource_type,
            CostLineItem.tags,
            CostLineItem.currency,
            func.sum(CostLineItem.cost).label("cost"),
            func.sum(CostLineItem.usage_quantity).label("usage"),
            func.count().label("days"),
        )
        .where(CostLineItem.usage_date >= start, CostLineItem.usage_date <= end)
        .group_by(
            CostLineItem.connection_id,
            CostLineItem.provider,
            CostLineItem.account_id,
            CostLineItem.resource_id,
            CostLineItem.resource_name,
            CostLineItem.resource_type,
            CostLineItem.tags,
            CostLineItem.currency,
        )
    )

    found: list[Recommendation] = []
    for r in rows.all():
        monthly = float(r.cost) * (30 / max(r.days, 1))
        tags = r.tags or {}
        if r.resource_type in DISK_TYPES and "attached_to" not in tags:
            found.append(
                _rec(
                    r,
                    "unattached_disk",
                    f"Unattached disk {r.resource_name}",
                    "This disk has no owner VM tag and is still incurring storage cost.",
                    monthly,
                    {"days": r.days, "period_cost": r.cost},
                )
            )
        if r.resource_type in IDLE_TYPES and float(r.usage or 0) < 2:
            found.append(
                _rec(
                    r,
                    "idle_compute",
                    f"Idle compute {r.resource_name}",
                    "Utilisation is near zero over the last 14 days while the instance remains billed.",
                    monthly * 0.7,
                    {"usage": r.usage, "period_cost": r.cost},
                )
            )
        if r.resource_type in IP_TYPES and "attached_to" not in tags:
            found.append(
                _rec(
                    r,
                    "orphan_ip",
                    f"Orphan public IP {r.resource_name}",
                    "Public IP is not associated with a running NIC/instance.",
                    monthly,
                    {"period_cost": r.cost},
                )
            )
        if not tags.get("team") and not tags.get("project"):
            found.append(
                _rec(
                    r,
                    "untagged",
                    f"Untagged spend on {r.resource_name}",
                    "Resource is missing team/project tags, so it cannot be allocated to an owner.",
                    0,
                    {"period_cost": r.cost},
                )
            )
        if r.resource_type in IDLE_TYPES and 2 <= float(r.usage or 0) < 20:
            found.append(
                _rec(
                    r,
                    "rightsize",
                    f"Right-size {r.resource_name}",
                    "Sustained low utilisation suggests a smaller SKU would cover the same workload.",
                    monthly * 0.35,
                    {"usage": r.usage, "period_cost": r.cost},
                )
            )

    existing = await session.execute(select(Recommendation))
    keep_status = {
        (row.connection_id, row.resource_id, row.category): row.status
        for row in existing.scalars().all()
    }
    await session.execute(delete(Recommendation).where(Recommendation.status == "open"))

    count = 0
    seen: set[tuple] = set()
    for rec in found:
        key = (rec.connection_id, rec.resource_id, rec.category)
        if key in seen:
            continue
        seen.add(key)
        if keep_status.get(key) in {"accepted", "dismissed"}:
            continue
        rec.status = "open"
        session.add(rec)
        count += 1
    await session.commit()
    return count


def _rec(row, category: str, title: str, description: str, savings: float, evidence: dict):
    return Recommendation(
        connection_id=row.connection_id,
        provider=row.provider,
        account_id=row.account_id,
        resource_id=row.resource_id,
        resource_name=row.resource_name,
        category=category,
        title=title,
        description=description,
        monthly_savings=round(max(savings, 0), 2),
        currency=row.currency,
        status="open",
        tags=row.tags or {},
        evidence=evidence,
    )
