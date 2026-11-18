import json
from pathlib import Path

import pytest

from app.database.models import CallEndReason, CallStatus
from app.providers.telephony import exotel_models as em

FIXTURES = Path(__file__).parents[2] / "fixtures" / "exotel"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    ("raw", "status", "reason"),
    [
        ("queued", CallStatus.INITIATING, None),
        ("ringing", CallStatus.RINGING, None),
        ("in-progress", CallStatus.IN_PROGRESS, None),
        ("completed", CallStatus.COMPLETED, None),
        ("busy", CallStatus.BUSY, CallEndReason.BUSY),
        ("no-answer", CallStatus.NO_ANSWER, CallEndReason.NO_ANSWER),
        ("failed", CallStatus.FAILED, CallEndReason.PROVIDER_FAILED),
        ("canceled", CallStatus.CANCELLED, CallEndReason.CANCELLED),
        ("Completed ", CallStatus.COMPLETED, None),
    ],
)
def test_status_map(raw: str, status: CallStatus, reason: CallEndReason | None) -> None:
    assert em.map_status(raw) == (status, reason)


def test_unknown_status_is_none() -> None:
    assert em.map_status("teleported") is None
    assert em.map_status(None) is None


def test_parse_terminal_callback() -> None:
    payload = _load("docs_status_terminal.json")
    assert isinstance(payload, dict)
    cb = em.parse_status_callback(payload, tz="Asia/Kolkata")
    assert cb.call_sid == "b6cfaf0e5d8a4f1fb5b1docs0001"
    assert cb.event_type == "terminal"
    assert cb.raw_status == "completed"
    assert cb.duration_seconds == 320
    assert cb.recording_url is None
    assert cb.custom_field is None  # empty string → None
    assert cb.start_time is not None and cb.start_time.utcoffset().total_seconds() == 19800  # type: ignore[union-attr]
    assert cb.legs[0]["Status"] == "completed"


def test_dedupe_key_same_for_redelivery_and_differs_per_event() -> None:
    terminal = _load("docs_status_terminal.json")
    answered = _load("docs_status_answered.json")
    assert isinstance(terminal, dict) and isinstance(answered, dict)
    a = em.parse_status_callback(terminal, tz="UTC").dedupe_key()
    assert a == em.parse_status_callback(dict(terminal), tz="UTC").dedupe_key()
    assert a != em.parse_status_callback(answered, tz="UTC").dedupe_key()


def test_flatten_form_nested_legs() -> None:
    out = em.flatten_form(
        [
            ("CallSid", "abc"),
            ("Legs[0][Status]", "completed"),
            ("Legs[0][OnCallDuration]", "12"),
            ("Legs[1][Status]", "null"),
        ]
    )
    assert out == {
        "CallSid": "abc",
        "Legs": [{"Status": "completed", "OnCallDuration": "12"}, {"Status": "null"}],
    }


def test_parse_stream_start_and_format_check() -> None:
    sequence = _load("docs_stream_sequence.json")
    assert isinstance(sequence, list)
    start = em.parse_stream_start(sequence[1])
    assert start.stream_sid == "docs-stream-1"
    assert start.call_sid == "b6cfaf0e5d8a4f1fb5b1docs0001"
    assert (start.encoding, start.sample_rate) == ("raw", 8000)
    assert em.media_format_matches(start, encoding="slin", sample_rate=8000)
    assert not em.media_format_matches(start, encoding="slin", sample_rate=16000)
    assert not em.media_format_matches(start, encoding="mulaw", sample_rate=8000)


def test_start_without_media_format_is_accepted() -> None:
    start = em.parse_stream_start({"event": "start", "start": {"call_sid": "x"}})
    assert em.media_format_matches(start, encoding="slin", sample_rate=8000)


def test_message_shape_hides_content() -> None:
    shape = em.message_shape({"event": "media", "media": {"payload": "QUJD", "chunk": 1}})
    assert shape == {"event": "str[5]", "media": {"payload": "str[4]", "chunk": "int"}}


def test_real_exotel_announces_base64_for_slin() -> None:
    # As seen on the first real call (2026-11-19)
    start = em.parse_stream_start(
        {
            "event": "start",
            "start": {
                "media_format": {"encoding": "base64", "sample_rate": "8000", "bit_rate": "128kbps"}
            },
        }
    )
    assert em.media_format_matches(start, encoding="slin", sample_rate=8000)
