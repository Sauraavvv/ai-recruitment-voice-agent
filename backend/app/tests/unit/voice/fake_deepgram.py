"""A local stand-in for Deepgram's streaming endpoint, for provider tests without the network.

Per connection it records the query, audio bytes and control messages, and runs a `script`
coroutine that decides what to send back (e.g. replay recorded messages, drop the socket).
"""

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "deepgram_events"
GOOD_KEY = "good-key"


def load_messages(name: str) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    messages: list[dict[str, Any]] = data["messages"]
    return messages


@dataclass
class Connection:
    ws: ServerConnection
    query: dict[str, list[str]]
    audio: bytearray = field(default_factory=bytearray)
    controls: list[str] = field(default_factory=list)
    got_audio: asyncio.Event = field(default_factory=asyncio.Event)
    got_close_stream: asyncio.Event = field(default_factory=asyncio.Event)

    async def send(self, msg: dict[str, Any]) -> None:
        await self.ws.send(json.dumps({k: v for k, v in msg.items() if k != "_t"}))


Script = Callable[[Connection], Coroutine[Any, Any, None]]


async def wait_close_stream(conn: Connection) -> None:
    """Default script: say nothing until CloseStream, then close normally."""
    await conn.got_close_stream.wait()


class FakeDeepgram:
    def __init__(self, script: Script = wait_close_stream, *, status: int | None = None) -> None:
        self.script = script
        self.status = status  # reject the handshake with this HTTP status
        self.connections: list[Connection] = []
        self.handshakes = 0
        self._server: Server | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        port = next(iter(self._server.sockets)).getsockname()[1]
        return f"ws://127.0.0.1:{port}/v1/listen"

    async def __aenter__(self) -> "FakeDeepgram":
        self._server = await serve(self._handler, "127.0.0.1", 0, process_request=self._check)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    def _check(self, _conn: ServerConnection, request: Request) -> Response | None:
        self.handshakes += 1
        if self.status is not None:
            return Response(self.status, "Rejected", Headers({"dg-error": "nope"}), b"nope")
        if request.headers.get("Authorization") != f"Token {GOOD_KEY}":
            return Response(401, "Unauthorized", Headers(), b"bad key")
        return None

    async def _handler(self, ws: ServerConnection) -> None:
        assert ws.request is not None
        conn = Connection(ws, parse_qs(urlsplit(ws.request.path).query))
        self.connections.append(conn)

        async def receive() -> None:
            async for message in ws:
                if isinstance(message, bytes):
                    conn.audio.extend(message)
                    conn.got_audio.set()
                else:
                    kind = json.loads(message)["type"]
                    conn.controls.append(kind)
                    if kind == "CloseStream":
                        conn.got_close_stream.set()

        receiver = asyncio.create_task(receive())
        script = asyncio.create_task(self.script(conn))
        # the script ends the connection, or the client goes away
        await asyncio.wait({receiver, script}, return_when=asyncio.FIRST_COMPLETED)
        for task in (receiver, script):
            task.cancel()
        await asyncio.gather(receiver, script, return_exceptions=True)
