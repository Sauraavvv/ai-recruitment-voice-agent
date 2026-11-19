"""OpenAI Realtime API over a server-side WebSocket (GA protocol, checked 2026-11-19).

    wss://api.openai.com/v1/realtime?model=<OPENAI_REALTIME_MODEL>
    Authorization: Bearer <OPENAI_API_KEY>

JSON events both ways; audio is base64 inside them. This module only moves events: the call
logic (session config, audio, tools, barge-in) is in voice/realtime_session.py.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from app.utils.log import get_logger

logger = get_logger(__name__)

URL = "wss://api.openai.com/v1/realtime?model={model}"
CONNECT_TIMEOUT_S = 10.0


class RealtimeError(RuntimeError):
    pass


class RealtimeClient(Protocol):
    async def connect(self) -> None: ...
    async def send(self, event: dict[str, Any]) -> None: ...
    def events(self) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


class OpenAIRealtimeClient:
    def __init__(self, api_key: str, model: str, *, safety_identifier: str | None = None) -> None:
        self._key = api_key
        self.model = model
        self._safety_id = safety_identifier
        self._ws: ClientConnection | None = None
        self._send_lock = asyncio.Lock()
        self.events_received = 0
        self.events_sent = 0

    async def connect(self) -> None:
        headers = {"Authorization": f"Bearer {self._key}"}
        if self._safety_id:
            headers["OpenAI-Safety-Identifier"] = self._safety_id
        try:
            self._ws = await asyncio.wait_for(
                connect(
                    URL.format(model=self.model),
                    additional_headers=headers,
                    max_size=16 * 1024 * 1024,
                    ping_interval=20,
                ),
                CONNECT_TIMEOUT_S,
            )
        except InvalidStatus as exc:
            code = exc.response.status_code
            raise RealtimeError(f"Realtime connection refused ({code})") from None
        except (TimeoutError, InvalidHandshake, OSError) as exc:
            raise RealtimeError(f"Can't reach the Realtime API ({type(exc).__name__})") from None

    async def send(self, event: dict[str, Any]) -> None:
        if self._ws is None:
            raise RealtimeError("not connected")
        async with self._send_lock:
            try:
                await self._ws.send(json.dumps(event))
            except ConnectionClosed:
                raise RealtimeError("Realtime connection closed") from None
        self.events_sent += 1

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self._ws is None:
            raise RealtimeError("not connected")
        try:
            async for raw in self._ws:
                self.events_received += 1
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
        except ConnectionClosed as exc:
            logger.info("realtime_closed", code=exc.rcvd.code if exc.rcvd else None)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
