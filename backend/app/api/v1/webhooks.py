"""Provider webhooks and the media stream (phase-05 P5-T3/T5/T6).

No recruiter session here. Each URL carries an unguessable token derived from APP_SECRET_KEY,
compared in constant time; a wrong token gets 403 (HTTP) or an immediate close (WebSocket).
"""

import hmac
import json
from typing import Any

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse

from app.api.deps import RedisDep, SessionDep, SettingsDep
from app.providers.telephony import exotel_models as em
from app.providers.telephony import stream_token, webhook_token
from app.services import call_service, sync_service
from app.utils.log import get_logger
from app.voice.websocket_handler import handle_exotel_stream

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _token_ok(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


async def _payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.body()
        data = json.loads(body) if body else {}
        return data if isinstance(data, dict) else {"_body": data}
    form = await request.form()
    return em.flatten_form([(k, str(v)) for k, v in form.multi_items()])


callback_router = APIRouter(tags=["webhooks"])


@callback_router.post("/cb/{token}", include_in_schema=False)
@router.post("/exotel/status/{token}", include_in_schema=False)
async def exotel_status(
    token: str, request: Request, session: SessionDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    if not _token_ok(token, webhook_token(settings)):
        logger.warning("webhook_forbidden", client=request.client.host if request.client else None)
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        payload = await _payload(request)
    except ValueError:
        logger.warning("webhook_unparseable")
        return JSONResponse({"ok": False}, status_code=400)
    try:
        outcome = await call_service.handle_status_callback(session, redis, settings, payload)
    except Exception:
        # Answer 200 anyway so Exotel doesn't retry into the same failure; the reconciler and
        # the stored event cover the gap.
        logger.exception("webhook_processing_failed", provider_call_id=payload.get("CallSid"))
        outcome = "error"
    if outcome == "applied":
        await sync_service.request_sync(settings)  # a final status may have been recorded
    return JSONResponse({"ok": True, "outcome": outcome})


@router.websocket("/exotel/stream/{token}")
async def exotel_stream(websocket: WebSocket, token: str, settings: SettingsDep) -> None:
    if not _token_ok(token, stream_token(settings)):
        logger.warning("stream_forbidden")
        await websocket.close(code=1008)
        return
    await handle_exotel_stream(websocket, settings)
