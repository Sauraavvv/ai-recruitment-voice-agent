"""RealtimeCallSession against a scripted fake of the OpenAI Realtime API (no network)."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agent.prompts import CandidateContext, JobConfig, greeting, introduction
from app.tests.conftest import make_settings
from app.voice import audio_converter as ac
from app.voice.audio_processor import InboundQueue
from app.voice.pipeline import CallContext
from app.voice.playback import AudioSender, MarkTracker
from app.voice.realtime_session import (
    RealtimeCallSession,
    estimate_cost,
    session_config,
)


class FakeRealtime:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self.incoming.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        self.closed = True

    def push(self, *events: dict[str, Any] | None) -> None:
        for e in events:
            self.incoming.put_nowait(e)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.sent if e["type"] == kind]


class Line:
    """Exotel stand-in: records what we send and echoes marks at once."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.marks: MarkTracker | None = None

    async def send_text(self, data: str) -> None:
        message = json.loads(data)
        self.messages.append(message)
        if message["event"] == "mark" and self.marks is not None:
            self.marks.note_returned(message["mark"]["name"])

    def kinds(self) -> list[str]:
        return [m["event"] for m in self.messages]


JOB = JobConfig.from_dict({"job_title": "Backend Developer", "company_name": "Test Co"})
CANDIDATE = CandidateContext(name="Asha Verma", candidate_id="c1")


def make_session(**settings: Any) -> tuple[RealtimeCallSession, FakeRealtime, Line, InboundQueue]:
    cfg = make_settings(voice_engine="realtime", **settings)
    line = Line()
    sender = AudioSender(
        line, "s1", encoding="slin", sample_rate=8000, frame_bytes=320, send_ahead_ms=20
    )
    marks = MarkTracker()
    line.marks = marks
    inbound = InboundQueue(64000)
    client = FakeRealtime()
    ctx = CallContext(attempt_id="a1", job=JOB, candidate=CANDIDATE)
    session = RealtimeCallSession(
        ctx, settings=cfg, sender=sender, inbound=inbound, marks=marks, client=client
    )
    return session, client, line, inbound


def audio_delta(item: str, response: str, ms: int) -> dict[str, Any]:
    mulaw = ac.pcm16_to_mulaw(b"\x10\x00" * (8 * ms))
    return {
        "type": "response.output_audio.delta",
        "item_id": item,
        "response_id": response,
        "delta": base64.b64encode(mulaw).decode(),
    }


def assistant_item(item: str) -> dict[str, Any]:
    return {
        "type": "conversation.item.added",
        "item": {"id": item, "type": "message", "role": "assistant", "content": []},
    }


def user_item(item: str) -> dict[str, Any]:
    return {
        "type": "conversation.item.added",
        "item": {"id": item, "type": "message", "role": "user", "content": []},
    }


def tool_call(response: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "type": "response.function_call_arguments.done",
        "response_id": response,
        "call_id": f"call-{name}",
        "name": name,
        "arguments": json.dumps(args),
    }


def done(response: str, status: str = "completed", **usage: int) -> dict[str, Any]:
    return {
        "type": "response.done",
        "response": {
            "id": response,
            "status": status,
            "usage": {
                "input_token_details": {
                    "audio_tokens": usage.get("audio_in", 0),
                    "text_tokens": usage.get("text_in", 0),
                    "cached_tokens_details": {"audio_tokens": usage.get("audio_cached", 0)},
                },
                "output_token_details": {"audio_tokens": usage.get("audio_out", 0)},
            },
        },
    }


async def settle(times: int = 20) -> None:
    for _ in range(times):
        await asyncio.sleep(0.01)


def test_session_config_uses_phone_audio_and_fixed_lines() -> None:
    cfg = session_config(CallContext("a1", JOB, CANDIDATE), make_settings())
    assert cfg["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert cfg["audio"]["output"]["format"] == {"type": "audio/pcmu"}
    assert cfg["model"] == "gpt-realtime-2.1-mini" and cfg["audio"]["output"]["voice"] == "marin"
    assert cfg["audio"]["input"]["turn_detection"]["type"] == "server_vad"
    transcription = cfg["audio"]["input"]["transcription"]
    assert transcription["model"] == "gpt-4o-transcribe"
    assert "Latin" in transcription["prompt"] and "Asha Verma" in transcription["prompt"]
    assert introduction(CANDIDATE, JOB) in cfg["instructions"]  # the AI disclosure, verbatim
    assert "Test Co" in cfg["instructions"]
    names = {t["name"] for t in cfg["tools"]}
    assert names == {
        "confirm_identity",
        "confirm_permission",
        "record_answer",
        "record_status",
        "confirm_fields",
        "request_callback",
        "note_question",
        "end_call",
    }
    fields = cfg["tools"][2]["parameters"]["properties"]["field"]["enum"]
    assert "current_ctc" in fields and "notice_period" in fields


async def test_full_call_flow() -> None:
    session, client, line, inbound = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    # configured, then the greeting word for word
    assert client.sent[0]["type"] == "session.update"
    say = client.of("response.create")[0]["response"]["instructions"]
    assert greeting(CANDIDATE) in say

    # the agent's audio reaches the phone as slin frames
    client.push({"type": "response.created", "response": {"id": "r1"}}, assistant_item("i1"))
    client.push(audio_delta("i1", "r1", 200), done("r1", audio_out=40))
    client.push(
        {
            "type": "response.output_audio_transcript.done",
            "item_id": "i1",
            "transcript": greeting(CANDIDATE),
        }
    )
    await settle()
    assert line.kinds().count("media") >= 9

    # the candidate's audio goes up as μ-law
    inbound.put(b"\x00\x01" * 800)  # 100 ms of slin
    await settle()
    append = client.of("input_audio_buffer.append")
    assert append and len(base64.b64decode(append[0]["audio"])) == 800

    # an answer arrives as a tool call in a response that also speaks
    client.push(
        user_item("u1"),
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1",
            "transcript": "I get twelve lakhs per annum.",
        },
        {"type": "response.created", "response": {"id": "r2"}},
        tool_call(
            "r2",
            "record_answer",
            field="current_ctc",
            number_value=12,
            candidate_words="twelve lakhs per annum",
        ),
        tool_call(
            "r2",
            "record_answer",
            field="current_ctc",
            number_value=5000,
            candidate_words="nonsense",
        ),
        assistant_item("i2"),
        audio_delta("i2", "r2", 100),
        done("r2", audio_in=50, audio_out=30),
    )
    await settle()
    outputs = [
        json.loads(e["item"]["output"])
        for e in client.of("conversation.item.create")
        if e["item"]["type"] == "function_call_output"
    ]
    assert outputs[0]["ok"] is True
    assert outputs[1] == {"ok": False, "error": "value not valid; ask again"}
    assert session.state.fields["current_ctc"].value == 12
    # it spoke in that response: no extra response.create
    assert len(client.of("response.create")) == 1

    # declined, then the goodbye with end_call in the same response → hang up after playout
    client.push(
        {"type": "response.created", "response": {"id": "r3"}},
        tool_call("r3", "record_status", field="expected_ctc", status="declined"),
        tool_call("r3", "end_call", reason="completed"),
        assistant_item("i3"),
        audio_delta("i3", "r3", 100),
        done("r3", audio_out=20),
    )
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.ended_by == "agent"
    assert outcome.end_reason.value == "agent_completed"
    assert outcome.result.fields["expected_ctc"]["status"] == "declined"
    assert outcome.result.collected_data["current_ctc"] == 12
    assert outcome.result.screening_status.value == "partially_completed"
    speakers = [e["speaker"] for e in outcome.result.transcript]
    assert speakers[:2] == ["assistant", "candidate"]
    assert outcome.result.transcript[1]["text"] == "I get twelve lakhs per annum."
    assert outcome.stats["engine"] == "realtime"
    assert outcome.stats["usage"]["audio_out"] == 90
    assert "mark" in line.kinds()
    assert client.closed


async def test_barge_in_clears_and_truncates() -> None:
    session, client, line, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push({"type": "response.created", "response": {"id": "r1"}}, assistant_item("i1"))
    client.push(audio_delta("i1", "r1", 2000))  # 2 s queued on the line
    await settle(5)
    client.push({"type": "input_audio_buffer.speech_started", "item_id": "u1"})
    await settle()
    assert "clear" in line.kinds()
    (truncate,) = client.of("conversation.item.truncate")
    assert truncate["item_id"] == "i1" and 0 <= truncate["audio_end_ms"] < 2000
    assert session.transcript[0]["interrupted"] is True
    session.caller_hung_up("stop")
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.ended_by == "caller" and outcome.end_reason.value == "candidate_hangup"
    assert outcome.stats["barge_ins"] == 1


async def test_end_call_without_goodbye_says_the_closing_line() -> None:
    session, client, _line, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(
        {"type": "response.created", "response": {"id": "r1"}},
        tool_call("r1", "end_call", reason="opted_out"),
        done("r1"),
    )
    await settle()
    last_say = client.of("response.create")[-1]["response"]["instructions"]
    assert "not contacted again" in last_say
    client.push(
        {"type": "response.created", "response": {"id": "r2", "metadata": {"source": "hirecall"}}},
        assistant_item("i2"),
        audio_delta("i2", "r2", 100),
        done("r2"),
    )
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.result.opted_out is True
    assert outcome.result.screening_status.value == "opted_out"
    assert outcome.end_reason.value == "opted_out"


async def test_tools_only_response_continues_the_conversation() -> None:
    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(
        {"type": "response.created", "response": {"id": "r1"}},
        tool_call(
            "r1", "record_answer", field="interested", bool_value=True, candidate_words="yes"
        ),
        done("r1"),
    )
    await settle()
    assert len(client.of("response.create")) == 2  # greeting + "continue"
    assert session.state.fields["interested"].value is True
    session.caller_hung_up("stop")
    await asyncio.wait_for(runner, 5)


async def test_recruiter_end_and_api_closing() -> None:
    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    assert session.end_by_recruiter() is True
    await settle()
    assert client.of("response.cancel")
    assert "pass what we've covered" in client.of("response.create")[-1]["response"]["instructions"]
    assert session.end_by_recruiter() is False
    client.push(
        {"type": "response.created", "response": {"id": "r9", "metadata": {"source": "hirecall"}}},
        assistant_item("i9"),
        audio_delta("i9", "r9", 100),
        done("r9"),
    )
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.failure_reason == "ended_by_recruiter"
    assert outcome.end_reason.value == "max_duration"


async def test_server_closing_the_socket_is_a_technical_failure() -> None:
    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(None)  # connection closed
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.failure_reason == "realtime_closed"
    assert outcome.end_reason.value == "technical_failure"


def test_estimate_cost() -> None:
    usage = {
        "audio_in": 1_000_000,
        "audio_cached": 500_000,
        "audio_out": 100_000,
        "text_in": 0,
        "text_cached": 0,
        "text_out": 0,
    }
    # 0.5M fresh x $10 + 0.5M cached x $0.30 + 0.1M out x $20 = 5 + 0.15 + 2
    assert estimate_cost(usage) == pytest.approx(7.15)


async def test_identity_confirmed_plays_the_introduction_word_for_word() -> None:
    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(
        {"type": "response.created", "response": {"id": "r1"}},
        tool_call("r1", "confirm_identity", confirmed=True),
        done("r1"),
    )
    await settle()
    say = client.of("response.create")[-1]["response"]["instructions"]
    assert introduction(CANDIDATE, JOB) in say
    assert session.state.identity_confirmed is True
    # a second confirmation doesn't replay it
    client.push(
        {"type": "response.created", "response": {"id": "r2"}},
        tool_call("r2", "confirm_identity", confirmed=True),
        done("r2"),
    )
    await settle()
    assert (
        sum(
            introduction(CANDIDATE, JOB) in e.get("response", {}).get("instructions", "")
            for e in client.of("response.create")
        )
        == 1
    )
    session.caller_hung_up("stop")
    await asyncio.wait_for(runner, 5)


async def test_permission_plays_the_role_line_and_first_question() -> None:
    from app.agent.prompts import role_line

    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(
        {"type": "response.created", "response": {"id": "r1"}},
        tool_call("r1", "confirm_permission", granted=True),
        done("r1"),
    )
    await settle()
    say = client.of("response.create")[-1]["response"]["instructions"]
    assert role_line(JOB) in say and JOB.questions[0].prompt in say
    session.caller_hung_up("stop")
    await asyncio.wait_for(runner, 5)


def test_tool_values_are_coerced_like_the_pipeline() -> None:
    session, _, _, _ = make_session()
    out = session.apply_tool(
        "record_answer", {"field": "notice_period", "number_value": 60, "candidate_words": "sixty"}
    )
    assert out["ok"] and session.state.fields["notice_period"].value == "60 days"
    assert session.state.fields["notice_period"].meta.get("days") == 60
    session.apply_tool(
        "record_answer", {"field": "total_experience", "text_value": "6", "candidate_words": "six"}
    )
    assert session.state.fields["total_experience"].value == 6.0
    session.apply_tool(
        "record_answer", {"field": "interested", "text_value": "yes", "candidate_words": "yes"}
    )
    assert session.state.fields["interested"].value is True
    bad = session.apply_tool(
        "record_answer",
        {"field": "current_company", "text_value": "Working at.", "candidate_words": "working at"},
    )
    assert bad["ok"] is False  # no name in it: asked again, like the pipeline
    assert session.apply_tool("record_answer", {"field": "nope", "candidate_words": "x"}) == {
        "ok": False,
        "error": "unknown field",
    }


async def test_opt_out_words_end_the_call_whatever_the_model_does() -> None:
    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    client.push(
        user_item("u1"),
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1",
            "transcript": "Actually, please don't call me again. Remove my number.",
        },
    )
    await settle()
    assert client.of("response.cancel")
    assert "not contacted again" in client.of("response.create")[-1]["response"]["instructions"]
    # the model answering anyway is dropped and doesn't end the call early
    client.push(
        {"type": "response.created", "response": {"id": "model"}},
        assistant_item("im"),
        audio_delta("im", "model", 100),
        done("model"),
    )
    await settle()
    assert not runner.done()
    assert session.transcript[-1]["dropped"] is True
    client.push(
        {
            "type": "response.created",
            "response": {"id": "ours", "metadata": {"source": "hirecall"}},
        },
        assistant_item("io"),
        audio_delta("io", "ours", 100),
        done("ours"),
    )
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.result.opted_out and outcome.end_reason.value == "opted_out"
    assert all("model" not in e.get("text", "") for e in outcome.result.transcript)


async def test_callback_plays_the_confirmation_and_ends() -> None:
    from datetime import UTC, datetime, timedelta

    session, client, _, _ = make_session()
    runner = asyncio.create_task(session.run())
    await settle()
    when = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
    client.push(
        {"type": "response.created", "response": {"id": "r1"}},
        tool_call("r1", "request_callback", time_text="tomorrow at 5", time_iso=when),
        done("r1"),
    )
    await settle()
    assert "we'll call you back on" in client.of("response.create")[-1]["response"]["instructions"]
    client.push(
        {"type": "response.created", "response": {"id": "r2", "metadata": {"source": "hirecall"}}},
        assistant_item("i2"),
        audio_delta("i2", "r2", 100),
        done("r2"),
    )
    outcome = await asyncio.wait_for(runner, 5)
    assert outcome.end_reason.value == "callback_scheduled"
    assert outcome.result.screening_status.value == "callback_requested"
    assert outcome.result.callback["time_iso"] and not outcome.result.callback["needs_recruiter"]


def test_vague_or_past_callback_needs_a_recruiter() -> None:
    session, _, _, _ = make_session()
    session.apply_tool("request_callback", {"time_text": "evening", "time_iso": None})
    assert session.state.callback.needs_recruiter is True
    session.apply_tool(
        "request_callback", {"time_text": "yesterday", "time_iso": "2020-01-01T10:00:00+05:30"}
    )
    assert session.state.callback.time_iso is None
