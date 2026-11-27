"""The home page's browser demo call (voice/demo_session.py). Public: no login, no token. Only
the website itself may open it (Origin check), and the session limits each visitor."""

from fastapi import APIRouter, WebSocket

from app.api.deps import SettingsDep
from app.utils.log import get_logger
from app.voice.demo_session import handle_demo_stream

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.websocket("/stream")
async def demo_stream(websocket: WebSocket, settings: SettingsDep) -> None:
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin != settings.frontend_origin.rstrip("/"):
        logger.warning("demo_forbidden_origin", origin=origin or None)
        await websocket.close(code=1008)
        return
    client_ip = websocket.client.host if websocket.client else "unknown"
    await handle_demo_stream(websocket, settings, client_ip=client_ip)
