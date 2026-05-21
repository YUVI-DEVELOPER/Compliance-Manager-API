from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_user
from app.core.database import get_db
from app.schemas.auth_schema import ChangePasswordRequest, CurrentUser, LoginRequest, LoginSuccessResponse
from app.services.auth_service import change_password, login, logout

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginSuccessResponse)
async def login_api(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginSuccessResponse:
    return await login(db, payload, request=request)


@router.get("/me", response_model=CurrentUser)
async def me_api(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return current_user


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout_api(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await logout(db, current_user, request=request)
    return {"success": True, "message": "Logout successful", "data": None}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password_api(
    payload: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await change_password(db, current_user, payload)
    return {"success": True, "message": "Password changed successfully", "data": None}
