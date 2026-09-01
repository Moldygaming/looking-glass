from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acl import dashboard_visible
from app.auth import require_privilege
from app.db import get_session
from app.models import Dashboard
from app.schemas import CurrentUser, DashboardIn, DashboardOut

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("", response_model=list[DashboardOut])
async def list_dashboards(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.dashboards.read")),
):
    rows = (await session.execute(select(Dashboard).order_by(Dashboard.updated_at.desc()))).scalars().all()
    visible = [
        d
        for d in rows
        if dashboard_visible(user, d.owner_user_id, d.visibility, d.shared_group_id)
    ]
    return [DashboardOut.model_validate(d, from_attributes=True) for d in visible]


@router.post("", response_model=DashboardOut)
async def create_dashboard(
    body: DashboardIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.dashboards.write")),
):
    dashboard = Dashboard(owner_user_id=user.id, **body.model_dump())
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)
    return DashboardOut.model_validate(dashboard, from_attributes=True)


@router.get("/{dashboard_id}", response_model=DashboardOut)
async def get_dashboard(
    dashboard_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.dashboards.read")),
):
    dashboard = await _get_visible(session, user, dashboard_id)
    return DashboardOut.model_validate(dashboard, from_attributes=True)


@router.put("/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: UUID,
    body: DashboardIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.dashboards.write")),
):
    dashboard = await _get_visible(session, user, dashboard_id)
    if dashboard.owner_user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can edit this dashboard")
    for key, value in body.model_dump().items():
        setattr(dashboard, key, value)
    await session.commit()
    await session.refresh(dashboard)
    return DashboardOut.model_validate(dashboard, from_attributes=True)


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.dashboards.write")),
):
    dashboard = await _get_visible(session, user, dashboard_id)
    if dashboard.owner_user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can delete this dashboard")
    await session.delete(dashboard)
    await session.commit()
    return {"ok": True}


async def _get_visible(session: AsyncSession, user: CurrentUser, dashboard_id: UUID) -> Dashboard:
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if not dashboard_visible(user, dashboard.owner_user_id, dashboard.visibility, dashboard.shared_group_id):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dashboard
