"""Recruiter authentication: Argon2 password hashes and server-side sessions in Redis.

Session key: rcai:session:<sha256(token)> -> user id, 12 h sliding TTL. Only the hash of the
token is stored, so a Redis dump can't be replayed as cookies.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.database.models import User
from app.repositories import user_repo
from app.utils.redis import KEY_PREFIX

SESSION_COOKIE = "rcai_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_ATTEMPTS_PER_MINUTE = 5

_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _session_key(token: str) -> str:
    return f"{KEY_PREFIX}session:{hashlib.sha256(token.encode()).hexdigest()}"


async def check_login_rate(redis: Redis, client_ip: str, email: str) -> None:
    digest = hashlib.sha256(f"{client_ip}|{email.strip().lower()}".encode()).hexdigest()[:32]
    key = f"{KEY_PREFIX}ratelimit:login:{digest}"
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, 60)
    if attempts > LOGIN_ATTEMPTS_PER_MINUTE:
        raise AppError(429, "too_many_attempts", "Too many login attempts; wait a minute")


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await user_repo.get_by_email(session, email)
    if user is None or not user.is_active:
        verify_password(_DUMMY_HASH, password)
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")
    if not verify_password(user.password_hash, password):
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    await session.commit()
    return user


async def create_session(redis: Redis, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(_session_key(token), str(user_id), ex=SESSION_TTL_SECONDS)
    return token


async def resolve_session(redis: Redis, token: str) -> uuid.UUID | None:
    """User id for a live session, extending its TTL (sliding expiry)."""
    key = _session_key(token)
    value = await redis.getex(key, ex=SESSION_TTL_SECONDS)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def delete_session(redis: Redis, token: str) -> None:
    await redis.delete(_session_key(token))
