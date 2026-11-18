"""UtteranceAssembler, on recorded Deepgram sequences (tests/fixtures/deepgram_events) and on
constructed edge cases."""

import pytest

from app.providers.stt.base import TranscriptEvent
from app.providers.stt.deepgram_provider import DeepgramSTTProvider
from app.tests.unit.voice.fake_deepgram import load_messages
from app.voice.utterance import Utterance, UtteranceAssembler, is_filler

SID = "s1"


def parse(name: str) -> list[TranscriptEvent]:
    """Recorded raw messages → TranscriptEvents, through the provider's own parser."""
    provider = DeepgramSTTProvider(api_key="x")
    provider.session_id = SID
    for msg in load_messages(name):
        provider._handle(msg)
    events = []
    while not provider._events.empty():
        events.append(provider._events.get_nowait())
    return events


def assemble(events: list[TranscriptEvent], **flags: bool) -> list[Utterance]:
    assembler = UtteranceAssembler(SID)
    for key, value in flags.items():
        setattr(assembler, key, value)
    out = [u for e in events if (u := assembler.feed(e)) is not None]
    if (last := assembler.flush()) is not None:
        out.append(last)
    return out


def ev(
    kind: str,
    text: str = "",
    *,
    endpoint: bool = False,
    conf: float = 0.9,
    start: float = 0.0,
    end: float = 1.0,
    at: float = 0.0,
) -> TranscriptEvent:
    return TranscriptEvent(SID, kind, text, conf, start, end, endpoint, at)  # type: ignore[arg-type]


# --- recorded sequences --------------------------------------------------------------------


def test_parser_maps_recorded_messages() -> None:
    events = parse("recall_pause_8k")
    kinds = [e.kind for e in events]
    assert kinds[0] == "speech_started"
    assert "utterance_end" in kinds
    final = next(e for e in events if e.kind == "final" and e.text)
    assert final.text == "My current CTC is"
    assert final.endpoint is True
    # word timings, not the segment (which runs on into the silence)
    assert final.start_s == pytest.approx(0.0)
    assert final.end_s == pytest.approx(1.68)
    assert final.end_s is not None and final.end_s < 2.0


def test_speech_final_first_then_utterance_end_is_ignored() -> None:
    utterances = assemble(parse("recall_pause_8k"))
    assert [u.text for u in utterances] == ["My current CTC is", "I think it is 9.2 lakhs."]
    assert all(u.trigger == "speech_final" for u in utterances)


def test_segments_join_into_one_utterance() -> None:
    [utterance] = assemble(parse("multi_answer_8k"))
    assert utterance.segments == 2
    assert utterance.text == (
        "I am at Tata Consultancy Services, Hyderabad office, and my notice period is thirty days."
    )
    assert utterance.confidence is not None and utterance.confidence > 0.9
    assert utterance.started_at is not None and utterance.ended_at is not None
    assert utterance.started_at < utterance.ended_at


@pytest.mark.parametrize("name", ["silence_8k", "filler_8k"])
def test_silence_and_filler_give_no_utterance(name: str) -> None:
    events = parse(name)
    assert any(e.kind == "final" and not e.text for e in events)  # empty finals were sent
    assert assemble(events) == []


def test_noisy_and_nova2_recordings_assemble() -> None:
    assert len(assemble(parse("ctc_pair_tv_8k"))) == 1
    [u] = assemble(parse("experience_nova2_16k"))
    assert "six point five years" in u.text


# --- constructed edge cases ----------------------------------------------------------------


def test_utterance_end_first_then_late_speech_final_is_ignored() -> None:
    events = [
        ev("partial", "my notice"),
        ev("final", "My notice period is", conf=0.95),
        ev("utterance_end", end=2.0),
        ev("final", "", endpoint=True),  # late, empty
    ]
    [u] = assemble(events)
    assert u.trigger == "utterance_end"
    assert u.text == "My notice period is"


def test_both_signals_give_one_utterance() -> None:
    events = [ev("final", "Sixty days.", endpoint=True), ev("utterance_end")]
    assembler = UtteranceAssembler(SID)
    results = [assembler.feed(e) for e in events]
    assert [r.text if r else None for r in results] == ["Sixty days.", None]


def test_utterance_end_with_only_a_partial_waits_for_the_final() -> None:
    assembler = UtteranceAssembler(SID)
    assert assembler.feed(ev("partial", "thirty")) is None
    assert assembler.feed(ev("utterance_end")) is None
    u = assembler.feed(ev("final", "Thirty days."))
    assert u is not None and u.text == "Thirty days." and u.trigger == "utterance_end"


def test_confidence_is_the_minimum_and_preview_includes_partial() -> None:
    assembler = UtteranceAssembler(SID)
    assembler.feed(ev("final", "I am at Wipro,", conf=0.97))
    assembler.feed(ev("partial", "Noida"))
    assert assembler.preview == "I am at Wipro, Noida"
    assert assembler.in_speech
    u = assembler.feed(ev("final", "Noida.", conf=0.55, endpoint=True))
    assert u is not None and u.confidence == 0.55
    assert not assembler.in_speech and assembler.preview == ""


def test_filler_dropped_unless_short_answer_expected() -> None:
    events = [ev("final", "Umm, hmm.", endpoint=True)]
    assert assemble(events) == []
    [u] = assemble(events, expect_short_answer=True)
    assert u.text == "Umm, hmm."


@pytest.mark.parametrize(
    ("text", "filler"),
    [
        ("uh", True),
        ("Hmm...", True),
        ("um, uh", True),
        ("mm-hmm", False),
        ("uh-huh", False),
        ("hmm okay", False),
        ("", False),
    ],
)
def test_is_filler(text: str, filler: bool) -> None:
    assert is_filler(text) is filler


def test_closed_flushes_pending_finals() -> None:
    assembler = UtteranceAssembler(SID)
    assembler.feed(ev("final", "Ninety days"))
    u = assembler.feed(ev("closed"))
    assert u is not None and u.trigger == "flush"


def test_events_from_another_session_are_rejected() -> None:
    with pytest.raises(ValueError, match="fed to"):
        UtteranceAssembler("other").feed(ev("final", "x"))


def test_speech_timing() -> None:
    assembler = UtteranceAssembler(SID, clock=lambda: 99.0)
    assembler.feed(ev("speech_started", at=10.0))
    assembler.feed(ev("partial", "I have", at=10.8))
    assert assembler.speech_started_at == 10.0
    assert assembler.last_speech_at == 10.8
    u = assembler.feed(ev("final", "I have four years.", endpoint=True, at=11.5))
    assert u is not None and u.completed_at == 11.5
    # a spurious SpeechStarted long before the next words doesn't count as their start
    assembler.feed(ev("speech_started", at=20.0))
    assembler.feed(ev("partial", "yes", at=30.0))
    assert assembler.speech_started_at == 30.0
