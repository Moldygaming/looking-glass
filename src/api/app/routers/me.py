from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.schemas import CurrentUser

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
