"""Provider status for the Settings page (phase-08 §5.4): configured, reachable, message.

Each check is the cheapest authenticated read the provider has, cached in Redis for 60 s
(`refresh` bypasses the cache):

  OpenAI     GET /v1/models               the key works
  Deepgram   GET /v1/projects             the key works (STT and the fallback voice)
  Exotel     GET /v1/Accounts/{sid}.json  the key/token work for this account
  Voice      the loaded TTS in this process (Kitten Iris + Deepgram Aura fallback), no call

Messages never contain a key, a token or a response body: only HTTP status codes and our own
text. (The test asserts that no configured secret value appears in the response.)
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis

from app.config import Settings
from app.utils.log import get_logger
from app.utils.redis import KEY_PREFIX

logger = get_logger(__name__)

CACHE_KEY = KEY_PREFIX + "provider-status:{name}"
CACHE_TTL_S = 60
TIMEOUT_S = 5.0

Transport = httpx.AsyncBaseTransport | None


def _result(
    name: str,
    label: str,
    *,
    configured: bool,
    reachable: bool | None,
    message: str | None,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "configured": configured,
        "reachable": reachable,
        "message": message,
        "detail": detail,
        "last_checked": datetime.now(UTC).isoformat(),
    }


def _http_message(response: httpx.Response) -> tuple[bool, str | None]:
    if response.is_success:
        return True, None
    if response.status_code in (401, 403):
        return False, f"The key was refused ({response.status_code})"
    if response.status_code == 429:
        return True, "Rate limited right now (429); the key works"
    return False, f"Unexpected response ({response.status_code})"


async def _get(url: str, transport: Transport, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
        return await client.get(url, **kwargs)


async def check_openai(settings: Settings, transport: Transport = None) -> dict[str, Any]:
    label = "OpenAI (screening agent)"
    if not (settings.openai_api_key and settings.openai_model):
        return _result(
            "openai", label, configured=False, reachable=None, message="OPENAI_API_KEY not set"
        )
    try:
        response = await _get(
            "https://api.openai.com/v1/models",
            transport,
            headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
        )
    except httpx.HTTPError as exc:
        return _result("openai", label, configured=True, reachable=False, message=_network(exc))
    reachable, message = _http_message(response)
    return _result(
        "openai",
        label,
        configured=True,
        reachable=reachable,
        message=message,
        detail=f"model {settings.openai_model}",
    )


async def check_deepgram(settings: Settings, transport: Transport = None) -> dict[str, Any]:
    label = "Deepgram (speech recognition)"
    if not settings.deepgram_api_key:
        return _result(
            "deepgram", label, configured=False, reachable=None, message="DEEPGRAM_API_KEY not set"
        )
    try:
        response = await _get(
            "https://api.deepgram.com/v1/projects",
            transport,
            headers={"Authorization": f"Token {settings.deepgram_api_key.get_secret_value()}"},
        )
    except httpx.HTTPError as exc:
        return _result("deepgram", label, configured=True, reachable=False, message=_network(exc))
    reachable, message = _http_message(response)
    return _result(
        "deepgram",
        label,
        configured=True,
        reachable=reachable,
        message=message,
        detail=f"{settings.deepgram_stt_model} {settings.deepgram_stt_language}",
    )


async def check_exotel(settings: Settings, transport: Transport = None) -> dict[str, Any]:
    label = "Exotel (telephony)"
    if not settings.exotel_configured:
        missing = (
            "PUBLIC_BACKEND_URL not set"
            if settings.exotel_api_key and not settings.public_backend_url
            else "EXOTEL_* settings incomplete"
        )
        return _result("exotel", label, configured=False, reachable=None, message=missing)
    assert settings.exotel_api_key and settings.exotel_api_token and settings.exotel_subdomain
    host = settings.exotel_subdomain.removeprefix("https://").strip("/")
    try:
        response = await _get(
            f"https://{host}/v1/Accounts/{settings.exotel_account_sid}.json",
            transport,
            auth=httpx.BasicAuth(
                settings.exotel_api_key.get_secret_value(),
                settings.exotel_api_token.get_secret_value(),
            ),
        )
    except httpx.HTTPError as exc:
        return _result("exotel", label, configured=True, reachable=False, message=_network(exc))
    reachable, message = _http_message(response)
    return _result(
        "exotel",
        label,
        configured=True,
        reachable=reachable,
        message=message,
        detail=f"caller id {settings.exotel_caller_id}",
    )


def check_voice(tts: Any) -> dict[str, Any]:
    """The voice loaded in this process (no network)."""
    label = "AI voice (Kitten TTS, Deepgram fallback)"
    if tts is None:
        return _result(
            "tts", label, configured=True, reachable=False, message="The voice isn't loaded"
        )
    status = tts.status()
    latency = getattr(status, "last_latency_ms", None)
    detail = f"last synthesis {round(latency)} ms" if latency is not None else None
    return _result(
        "tts",
        label,
        configured=True,
        reachable=bool(status.ready),
        message=None if status.ready else "Still loading, or failed to load",
        detail=detail,
    )


def _network(exc: Exception) -> str:
    return f"Can't reach the provider ({type(exc).__name__})"


Check = Callable[[], Awaitable[dict[str, Any]]]


async def cached(redis: Redis, name: str, check: Check, *, refresh: bool) -> dict[str, Any]:
    key = CACHE_KEY.format(name=name)
    if not refresh:
        try:
            raw = await redis.get(key)
        except Exception:
            raw = None
        if raw:
            result: dict[str, Any] = json.loads(raw)
            return result
    try:
        result = await asyncio.wait_for(check(), timeout=TIMEOUT_S + 1)
    except Exception as exc:
        logger.warning("provider_check_failed", provider=name, error=type(exc).__name__)
        result = _result(name, name, configured=True, reachable=False, message=_network(exc))
    try:
        await redis.set(key, json.dumps(result), ex=CACHE_TTL_S)
    except Exception:
        logger.warning("provider_status_cache_failed", provider=name)
    return result


async def all_statuses(
    redis: Redis, settings: Settings, *, tts: Any, refresh: bool, transport: Transport = None
) -> list[dict[str, Any]]:
    """OpenAI, Deepgram, Exotel and the voice."""
    checks: list[tuple[str, Check]] = [
        ("openai", lambda: check_openai(settings, transport)),
        ("deepgram", lambda: check_deepgram(settings, transport)),
        ("exotel", lambda: check_exotel(settings, transport)),
    ]
    results = list(await asyncio.gather(*(cached(redis, n, c, refresh=refresh) for n, c in checks)))
    results.append(check_voice(tts))  # local and instant: never cached
    return results
