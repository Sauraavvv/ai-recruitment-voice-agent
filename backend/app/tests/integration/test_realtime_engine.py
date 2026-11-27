"""The voice engine switch: Settings page / VOICE_ENGINE → the stream handler builds the right
session. The Phase 6 pipeline stays the default."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import CandidateContext, JobConfig
from app.config import Settings
from app.services import settings_service, transcript_service
from app.tests.conftest import make_settings
from app.voice import websocket_handler as wh
from app.voice.audio_processor import InboundQueue
from app.voice.pipeline import CallContext
from app.voice.playback import AudioSender, MarkTracker
from app.voice.realtime_session import RealtimeCallSession


class Sink:
    async def send_text(self, data: str) -> None:
        pass


def _parts() -> dict[str, Any]:
    return {
        "sender": AudioSender(
            Sink(), "s", encoding="slin", sample_rate=8000, frame_bytes=320, send_ahead_ms=20
        ),
        "inbound": InboundQueue(1000),
        "marks": MarkTracker(),
    }


async def test_settings_page_switches_the_engine(
    admin: AsyncClient, authed: AsyncClient, active_job: Any, db_session: AsyncSession
) -> None:
    data = (await admin.get("/api/v1/settings")).json()["data"]
    assert data["general"]["voice_engine"] is None
    assert data["limits"]["voice_engine_env"] == "pipeline"
    assert data["limits"]["realtime_model"] == "gpt-realtime-2.1-mini"

    response = await admin.patch("/api/v1/settings", json={"voice_engine": "realtime"})
    assert response.json()["data"]["general"]["voice_engine"] == "realtime"
    effective = await settings_service.effective(db_session, make_settings())
    assert effective.voice_engine == "realtime"

    bad = await admin.patch("/api/v1/settings", json={"voice_engine": "magic"})
    assert bad.status_code == 422
    back = await admin.patch("/api/v1/settings", json={"voice_engine": None})
    assert back.json()["data"]["general"]["voice_engine"] is None
    effective = await settings_service.effective(db_session, make_settings())
    assert effective.voice_engine == "pipeline"


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """No database or provider: the handler's context loading is stubbed."""
    seen: dict[str, Any] = {}
    job = JobConfig.from_dict({"job_title": "Dev", "company_name": "Co"})

    async def load_context(attempt_id: uuid.UUID, call_sid: Any, settings: Settings) -> Any:
        return CallContext(str(attempt_id), job, CandidateContext(name="Asha"))

    async def open_conversation(attempt_id: uuid.UUID) -> None:
        seen["opened"] = attempt_id

    monkeypatch.setattr(wh, "load_context", load_context)
    monkeypatch.setattr(transcript_service, "open_conversation", open_conversation)
    return seen


async def _build(engine: str, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Any:
    settings = make_settings(openai_api_key="sk-test", openai_model="m", **overrides)

    async def effective(env: Settings) -> Settings:
        return env.model_copy(update={"voice_engine": engine})

    monkeypatch.setattr(settings_service, "effective_new_session", effective)
    return await wh.build_conversation(settings, str(uuid.uuid4()), "sid", tts=None, **_parts())


async def test_realtime_engine_is_built_without_the_local_voice(
    monkeypatch: pytest.MonkeyPatch, stubbed: dict[str, Any]
) -> None:
    built = await _build("realtime", monkeypatch)
    assert isinstance(built, wh.Conversation)
    assert isinstance(built.session, RealtimeCallSession)
    assert built.session.client.model == "gpt-realtime-2.1-mini"  # type: ignore[attr-defined]
    assert stubbed["opened"]
    await built.llm.aclose()


async def test_pipeline_stays_the_default(
    monkeypatch: pytest.MonkeyPatch, stubbed: dict[str, Any]
) -> None:
    # no TTS loaded: the pipeline can't speak, exactly as before
    assert await _build("pipeline", monkeypatch) == "voice_unavailable"


async def test_realtime_needs_the_openai_key(
    monkeypatch: pytest.MonkeyPatch, stubbed: dict[str, Any]
) -> None:
    settings = make_settings()

    async def effective(env: Settings) -> Settings:
        return env.model_copy(update={"voice_engine": "realtime"})

    monkeypatch.setattr(settings_service, "effective_new_session", effective)
    built = await wh.build_conversation(settings, str(uuid.uuid4()), "sid", tts=None, **_parts())
    assert built == "llm_not_configured"
