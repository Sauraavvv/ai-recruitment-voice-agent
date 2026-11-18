"""Shared API dependencies: DB session, current user, CSRF origin check."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.config import Settings, get_settings
from app.database.connection import get_session
from app.database.models import User
from app.repositories import user_repo
from app.services import auth_service
from app.utils.redis import get_redis

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


async def verify_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF guard: state-changing requests must come from the frontend's origin.

    Cookies are SameSite=Lax as well; this blocks cross-site form posts and fetches.
    """
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin") or _origin_of(request.headers.get("referer", ""))
    if origin != settings.frontend_origin.rstrip("/"):
        raise AppError(403, "csrf_failed", "Request origin not allowed")


async def require_user(request: Request, session: SessionDep, redis: RedisDep) -> User:
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if not token:
        raise AppError(401, "not_authenticated", "Log in to continue")
    user_id = await auth_service.resolve_session(redis, token)
    user = await user_repo.get(session, user_id) if user_id else None
    if user is None or not user.is_active:
        raise AppError(401, "not_authenticated", "Your session has expired; log in again")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
