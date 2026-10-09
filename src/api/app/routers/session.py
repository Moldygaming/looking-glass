from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import accept_sso, require_internal_key
from app.db import get_session
from app.schemas import SsoIn, SsoOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/sso", response_model=SsoOut)
async def entra_sso(
    body: SsoIn,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_internal_key),
):
    return await accept_sso(session, body)
