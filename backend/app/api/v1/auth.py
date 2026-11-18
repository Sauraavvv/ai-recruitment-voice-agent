from typing import Any

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.config import AppEnv
from app.schemas.auth import LoginRequest, UserOut
from app.schemas.common import DataResponse
from app.services import auth_service

# Login is the only /api/v1 route reachable without a session.
public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"])


@public_router.post("/login", response_model=DataResponse[UserOut])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    await auth_service.check_login_rate(redis, client_ip, body.email)
    user = await auth_service.authenticate(session, body.email, body.password)
    token = await auth_service.create_session(redis, user.id)
    response.set_cookie(
        auth_service.SESSION_COOKIE,
        token,
        max_age=auth_service.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.app_env is AppEnv.PRODUCTION,
        path="/",
    )
    return ok(UserOut.model_validate(user))


@router.post("/logout", response_model=DataResponse[None])
async def logout(
    _user: CurrentUser, request: Request, response: Response, redis: RedisDep
) -> dict[str, Any]:
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        await auth_service.delete_session(redis, token)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")
    return ok(None)


@router.get("/me", response_model=DataResponse[UserOut])
async def me(user: CurrentUser) -> dict[str, Any]:
    return ok(UserOut.model_validate(user))
