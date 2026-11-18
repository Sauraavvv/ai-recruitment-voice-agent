"""DeepgramSTTProvider against a local fake Deepgram server (no network, no cost)."""

import asyncio
import json
import socket
from typing import Any

import pytest

from app.config import Settings
from app.providers.stt import create_stt_provider
from app.providers.stt.base import STTConfigError, STTConnectionError, TranscriptEvent
from app.providers.stt.deepgram_provider import DeepgramSTTProvider
from app.tests.conftest import make_settings
from app.tests.unit.voice.fake_deepgram import GOOD_KEY, Connection, FakeDeepgram, load_messages

RATE = 8000
FRAME = b"\x01\x00" * (RATE // 50)  # 20 ms of linear16


def provider(url: str, **kwargs: Any) -> DeepgramSTTProvider:
    defaults: dict[str, Any] = {
        "api_key": GOOD_KEY,
        "url": url,
        "connect_timeout_s": 1.0,
        "backoff_s": 0.01,
        "keepalive_interval_s": 0.2,
        "close_timeout_s": 1.0,
    }
    return DeepgramSTTProvider(**{**defaults, **kwargs})


async def start(p: DeepgramSTTProvider, session_id: str = "s1") -> None:
    await p.start_stream(session_id=session_id, encoding="linear16", sample_rate=RATE)


async def collect(p: DeepgramSTTProvider, timeout: float = 5.0) -> list[TranscriptEvent]:
    async def run() -> list[TranscriptEvent]:
        return [e async for e in p.events()]

    return await asyncio.wait_for(run(), timeout)


def replay(name: str) -> Any:
    """Script: after the first audio arrives, send the recorded messages; close on CloseStream."""

    async def script(conn: Connection) -> None:
        await conn.got_audio.wait()
        for msg in load_messages(name):
            if msg["type"] != "Metadata":
                await conn.send(msg)
        await conn.got_close_stream.wait()
        await conn.send({"type": "Metadata"})

    return script


def free_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"ws://127.0.0.1:{port}/v1/listen"  # nothing listens here


async def test_query_parameters_nova3_keyterms() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url, model="nova-3", language="en-IN", keyterms=["CTC"])
        await p.start_stream(
            session_id="s1", encoding="mulaw", sample_rate=8000, keyterms=["Infosys", "CTC"]
        )
        await p.close()
    q = server.connections[0].query
    assert q["model"] == ["nova-3"] and q["language"] == ["en-IN"]
    assert q["encoding"] == ["mulaw"] and q["sample_rate"] == ["8000"]
    assert q["interim_results"] == ["true"] and q["vad_events"] == ["true"]
    assert q["utterance_end_ms"] == ["1000"] and q["endpointing"] == ["300"]
    assert q["keyterm"] == ["CTC", "Infosys"]  # de-duplicated
    assert "keywords" not in q


async def test_query_parameters_nova2_uses_keywords() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url, model="nova-2", keyterms=["LPA"])
        await start(p)
        await p.close()
    assert server.connections[0].query["keywords"] == ["LPA:2"]


async def test_bad_key_fails_fast_without_retrying() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url, api_key="wrong")
        with pytest.raises(STTConfigError, match="API key"):
            await start(p)
    assert server.handshakes == 1


async def test_bad_parameters_are_a_config_error() -> None:
    async with FakeDeepgram(status=400) as server:
        with pytest.raises(STTConfigError, match="parameters"):
            await start(provider(server.url))


async def test_unreachable_server_retries_then_fails() -> None:
    p = provider(free_port_url(), connect_attempts=3)
    with pytest.raises(STTConnectionError):
        await start(p)


async def test_unsupported_encoding() -> None:
    with pytest.raises(STTConfigError, match="encoding"):
        await provider("ws://unused").start_stream(
            session_id="s", encoding="opus", sample_rate=8000
        )


async def test_events_flow_and_close_flushes() -> None:
    async with FakeDeepgram(replay("recall_pause_8k")) as server:
        p = provider(server.url)
        await start(p, "call-7")
        for _ in range(10):
            await p.send_audio(FRAME)
        await asyncio.sleep(0.1)
        await p.close()
        events = await collect(p)
    assert events[-1].kind == "closed"
    assert {e.session_id for e in events} == {"call-7"}
    finals = [e.text for e in events if e.kind == "final" and e.text]
    assert finals == ["My current CTC is", "I think it is 9.2 lakhs."]
    conn = server.connections[0]
    assert len(conn.audio) == 10 * len(FRAME)
    assert conn.controls[-1] == "CloseStream"
    # after the end, get_transcription keeps answering `closed`
    assert (await p.get_transcription()).kind == "closed"


async def test_keepalive_during_silence() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url, keepalive_interval_s=0.05)
        await start(p)
        await asyncio.sleep(0.3)
        await p.close()
    assert server.connections[0].controls.count("KeepAlive") >= 3


async def test_reconnects_after_drop_and_keeps_timestamps_continuous() -> None:
    final = {
        "type": "Results",
        "is_final": True,
        "speech_final": True,
        "start": 0.0,
        "duration": 0.5,
        "channel": {
            "alternatives": [
                {
                    "transcript": "Hello.",
                    "confidence": 0.9,
                    "words": [{"word": "hello", "start": 0.1, "end": 0.4}],
                }
            ]
        },
    }

    async def script(conn: Connection) -> None:
        await conn.got_audio.wait()
        await conn.send(final)
        await conn.got_close_stream.wait()

    async with FakeDeepgram(script) as server:
        p = provider(server.url)
        await start(p)
        for _ in range(50):  # 1 s of audio
            await p.send_audio(FRAME)
        await asyncio.sleep(0.2)
        p.simulate_network_drop()
        await asyncio.sleep(0.05)
        for _ in range(25):  # 0.5 s more, buffered while reconnecting
            await p.send_audio(FRAME)
        for _ in range(50):
            if len(server.connections) == 2 and server.connections[1].audio:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        await p.close()
        events = await collect(p)

    assert p.stats.reconnects == 1 and p.stats.connects == 2
    assert len(server.connections) == 2
    assert len(server.connections[1].audio) >= 25 * len(
        FRAME
    )  # nothing sent after the drop was lost
    starts = [e.start_s for e in events if e.kind == "final"]
    assert starts[0] == pytest.approx(0.1)
    assert starts[1] == pytest.approx(1.1, abs=0.05)  # offset by the first connection's audio
    assert not any(e.kind == "error" for e in events)


async def test_buffer_is_bounded_while_disconnected() -> None:
    async def drop_at_once(conn: Connection) -> None:
        conn.ws.transport.abort()

    async with FakeDeepgram(drop_at_once) as server:
        p = provider(server.url, buffer_s=0.5, reconnect_window_s=0.3)
        await start(p)
        await asyncio.sleep(0.05)
        for _ in range(100):  # 2 s while there is no working stream
            await p.send_audio(FRAME)
        events = await collect(p)
    assert p.stats.dropped_audio_s == pytest.approx(1.5, abs=0.1)
    assert [e.kind for e in events][-2:] == ["error", "closed"]
    assert "lost" in (events[-2].detail or "")


async def test_no_stream_for_too_long_emits_error_then_closed() -> None:
    async def drop(conn: Connection) -> None:
        await conn.got_audio.wait()
        conn.ws.transport.abort()

    async with FakeDeepgram(drop) as server:
        p = provider(server.url, reconnect_window_s=0.3)
        await start(p)
        await p.send_audio(FRAME)
        server.status = 503  # every reconnect fails
        events = await collect(p)
    assert [e.kind for e in events] == ["error", "closed"]
    await p.close()  # still safe


async def test_send_after_close_is_ignored() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url)
        await start(p)
        await p.close()
        await p.send_audio(FRAME)
        await p.close()
    assert not server.connections[0].audio


async def test_sent_at_maps_audio_time_to_wall_clock() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url)
        await start(p)
        await p.send_audio(FRAME)  # 0.00-0.02
        t = p._mark_times[0]
        await p.send_audio(FRAME)  # 0.02-0.04
        await p.close()
    assert p.sent_at(0.01) == pytest.approx(t - 0.01)
    assert p.sent_at(5.0) is None


async def test_two_sessions_stay_separate() -> None:
    async def echo_session(conn: Connection) -> None:
        await conn.got_audio.wait()
        await asyncio.sleep(0.05)
        # tell each session how much audio *it* sent
        await conn.send(
            {
                "type": "Results",
                "is_final": True,
                "speech_final": True,
                "start": 0,
                "duration": 1,
                "channel": {
                    "alternatives": [{"transcript": f"bytes {len(conn.audio)}", "confidence": 1}]
                },
            }
        )
        await conn.got_close_stream.wait()

    async with FakeDeepgram(echo_session) as server:
        a, b = provider(server.url), provider(server.url)
        await asyncio.gather(start(a, "A"), start(b, "B"))
        await a.send_audio(FRAME * 3)
        await b.send_audio(FRAME)
        await asyncio.sleep(0.2)
        await asyncio.gather(a.close(), b.close())
        ea, eb = await asyncio.gather(collect(a), collect(b))
    assert [e.text for e in ea if e.kind == "final"] == [f"bytes {3 * len(FRAME)}"]
    assert [e.text for e in eb if e.kind == "final"] == [f"bytes {len(FRAME)}"]
    assert {e.session_id for e in ea} == {"A"} and {e.session_id for e in eb} == {"B"}


async def test_one_provider_per_session() -> None:
    async with FakeDeepgram() as server:
        p = provider(server.url)
        await start(p)
        with pytest.raises(RuntimeError):
            await start(p)
        await p.close()


def test_factory(settings: Settings) -> None:
    with pytest.raises(STTConfigError):
        create_stt_provider(settings)
    configured = make_settings(deepgram_api_key="k", deepgram_stt_keyterms="CTC, LPA ,")
    p = create_stt_provider(configured, keyterms=["Infosys"])
    assert isinstance(p, DeepgramSTTProvider)
    assert p.keyterms == ["CTC", "LPA", "Infosys"]
    assert p.model == "nova-3" and p.language == "en-IN"
    assert p.endpointing_ms == 300 and p.smart_format is False


def test_fixtures_are_sanitized() -> None:
    from app.tests.unit.voice.fake_deepgram import FIXTURES

    for path in FIXTURES.glob("*.json"):
        text = path.read_text()
        assert "request_id" not in text and "sha256" not in text, path.name
        json.loads(text)
