from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.acl import recommendation_acl
from app.auth import require_privilege
from app.db import get_session
from app.models import Recommendation
from app.schemas import CurrentUser, RecommendationOut, RecommendationPatch

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[RecommendationOut])
async def list_recommendations(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.recommendations.read")),
    status: str = Query(default="open"),
    category: str | None = None,
):
    stmt = select(Recommendation).where(recommendation_acl(user)).order_by(
        Recommendation.monthly_savings.desc()
    )
    if status != "all":
        stmt = stmt.where(Recommendation.status == status)
    if category:
        stmt = stmt.where(Recommendation.category == category)
    rows = (await session.execute(stmt)).scalars().all()
    return [RecommendationOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/summary")
async def recommendation_summary(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.recommendations.read")),
):
    stmt = (
        select(
            Recommendation.category,
            func.count().label("count"),
            func.coalesce(func.sum(Recommendation.monthly_savings), 0).label("savings"),
        )
        .where(recommendation_acl(user), Recommendation.status == "open")
        .group_by(Recommendation.category)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"category": r.category, "count": int(r.count), "monthly_savings": round(float(r.savings), 2)}
        for r in rows
    ]


@router.patch("/{recommendation_id}", response_model=RecommendationOut)
async def patch_recommendation(
    recommendation_id: UUID,
    body: RecommendationPatch,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_privilege("finops.recommendations.write")),
):
    stmt = select(Recommendation).where(
        Recommendation.id == recommendation_id, recommendation_acl(user)
    )
    rec = (await session.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.status = body.status
    await session.commit()
    await session.refresh(rec)
    return RecommendationOut.model_validate(rec, from_attributes=True)
