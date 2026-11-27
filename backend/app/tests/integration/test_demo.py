"""Browser demo call: the refusals and limits around the voice pipeline (the pipeline itself is
covered by the voice tests). Real Redis, fake WebSocket."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.tests.conftest import make_settings
from app.tests.integration.test_telephony import FakeWebSocket
from app.utils.redis import get_redis
from app.voice import demo_session as demo


@pytest.fixture(autouse=True)
async def _clean(client: AsyncClient) -> AsyncIterator[None]:
    redis = get_redis()

    async def wipe() -> None:
        for key in await redis.keys("rcai:demo:*"):
            await redis.delete(key)

    await wipe()
    yield
    await wipe()


class _ReadyVoice:
    def status(self) -> Any:
        return type("S", (), {"ready": True})()

    def forget_call(self, _id: str) -> None:
        pass


class _State:
    def __init__(self, tts: Any = None) -> None:
        self.tts = tts


def _events(ws: FakeWebSocket) -> list[dict[str, Any]]:
    return [m for m in ws.sent if m.get("event") == "error"]


def test_demo_job_and_names() -> None:
    job = demo.demo_job()
    assert [q.key for q in job.questions] == list(demo.DEMO_QUESTIONS)
    assert demo.clean_name("  Asha   Rao ") == "Asha Rao"
    assert demo.clean_name("<script>alert(1)</script>") == "scriptalertscript"
    assert demo.clean_name("") == demo.clean_name(None) == "there"
    assert len(demo.clean_name("x" * 100)) == demo.MAX_NAME


async def test_refusals_before_the_call() -> None:
    off = make_settings(demo_enabled=False)
    ws = FakeWebSocket([{"event": "start", "name": "A"}], _State())
    await demo.handle_demo_stream(ws, off, client_ip="1.2.3.4")  # type: ignore[arg-type]
    assert _events(ws)[0]["code"] == "disabled"

    settings = make_settings(deepgram_api_key="dg")
    ws = FakeWebSocket([{"event": "hello"}], _State(_ReadyVoice()))
    await demo.handle_demo_stream(ws, settings, client_ip="1.2.3.4")  # type: ignore[arg-type]
    assert _events(ws)[0]["code"] == "bad_start"

    ws = FakeWebSocket([{"event": "start", "name": "A"}], _State(None))  # voice not loaded
    await demo.handle_demo_stream(ws, settings, client_ip="1.2.3.4")  # type: ignore[arg-type]
    assert _events(ws)[0]["code"] == "unavailable"
    assert await get_redis().get(demo.ACTIVE_KEY) is None  # refused before taking a place


async def test_one_call_per_visitor_and_concurrent_limit() -> None:
    settings: Settings = make_settings(demo_calls_per_ip=1, demo_max_concurrent=1)
    await demo.claim(settings, "9.9.9.9")
    # One line only: a second visitor waits, and it doesn't use up their call
    with pytest.raises(demo.DemoRefused) as busy:
        await demo.claim(settings, "8.8.8.8")
    assert busy.value.code == "busy"
    await demo.release()

    # The first visitor has had their call
    with pytest.raises(demo.DemoRefused) as used:
        await demo.claim(settings, "9.9.9.9")
    assert used.value.code == "used"
    assert int(await get_redis().get(demo.ACTIVE_KEY) or 0) == 0

    # The second one still has theirs; a call that failed on our side is given back
    await demo.claim(settings, "8.8.8.8")
    await demo.release()
    await demo.give_back("8.8.8.8")
    await demo.claim(settings, "8.8.8.8")
    await demo.release()
    with pytest.raises(demo.DemoRefused):
        await demo.claim(settings, "8.8.8.8")
    ttl = await get_redis().ttl(demo._ip_key("8.8.8.8"))
    assert 29 * 86400 < ttl <= 30 * 86400


async def test_route_requires_the_site_origin(client: AsyncClient) -> None:
    app: Any = client.app  # type: ignore[attr-defined]
    with TestClient(app) as tc:
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            tc.websocket_connect(
                "/api/v1/demo/stream", headers={"origin": "https://evil.example"}
            ) as ws,
        ):
            ws.receive_text()
        assert closed.value.code == 1008
