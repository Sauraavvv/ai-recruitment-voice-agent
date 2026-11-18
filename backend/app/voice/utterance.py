"""Turns a stream of `TranscriptEvent`s into finished utterances (plan P4 §5.3).

- `final` segments accumulate into the current utterance; `partial`s only update `preview`.
- The utterance completes on `endpoint` (speech_final) **or** `utterance_end`, whichever comes
  first. The other signal for the same utterance is then ignored, because nothing new has
  accumulated.
- An `utterance_end` that arrives while words are still only in a partial (no final yet) marks
  the end as pending, and the next final completes the utterance.
- Confidence is the minimum across segments. Empty finals are ignored. Filler-only utterances
  ("uh", "hmm") are dropped, unless `expect_short_answer` is set (the agent asked a yes/no
  question, where "mm-hmm" or even "hmm" means something).
- Timing for P6's turn manager: `speech_started_at`, `last_speech_at`, `in_speech`.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.providers.stt.base import TranscriptEvent

# Hesitation sounds only. Not "mm-hmm"/"uh-huh"/"hmm okay": those can be answers.
FILLERS = frozenset(
    {"uh", "uhh", "uhm", "um", "umm", "hmm", "hm", "hmmm", "er", "erm", "ah", "ahh", "eh", "mm"}
)
Trigger = Literal["speech_final", "utterance_end", "flush"]


@dataclass(frozen=True)
class Utterance:
    session_id: str
    text: str
    confidence: float | None
    started_at: float | None  # session audio seconds
    ended_at: float | None
    completed_at: float  # time.monotonic() when it completed
    trigger: Trigger
    segments: int


def is_filler(text: str) -> bool:
    words = re.findall(r"[a-z'-]+", text.lower())  # "mm-hmm" stays one word
    return bool(words) and all(w in FILLERS for w in words)


class UtteranceAssembler:
    def __init__(self, session_id: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.session_id = session_id
        self.expect_short_answer = False
        self.speech_started_at: float | None = None  # monotonic, current/last utterance
        self.last_speech_at: float | None = None  # monotonic, last event with words in it
        self.dropped_fillers = 0
        self._clock = clock
        self._segments: list[TranscriptEvent] = []
        self._partial = ""
        self._end_pending = False
        self._start_pending = False  # SpeechStarted seen, no words yet

    @property
    def preview(self) -> str:
        """What has been heard of the current utterance, including the live partial."""
        return " ".join([*(s.text for s in self._segments), self._partial]).strip()

    @property
    def in_speech(self) -> bool:
        return bool(self._segments or self._partial)

    def feed(self, event: TranscriptEvent) -> Utterance | None:
        if event.session_id != self.session_id:
            raise ValueError(f"event for session {event.session_id} fed to {self.session_id}")
        at = event.received_at or self._clock()
        if event.kind == "speech_started":
            if not self.in_speech:
                self.speech_started_at = at
                self._start_pending = True
            return None
        if event.kind == "partial":
            self._heard(event)
            self._partial = event.text
            return None
        if event.kind == "final":
            if event.text:
                self._heard(event)
                self._segments.append(event)
            self._partial = ""
            if event.endpoint or self._end_pending:
                return self._complete("speech_final" if event.endpoint else "utterance_end", at)
            return None
        if event.kind == "utterance_end":
            if self._segments and not self._partial:
                return self._complete("utterance_end", at)
            if self._partial:
                self._end_pending = True  # the final for these words is still on its way
            return None
        if event.kind in ("closed", "error"):
            return self.flush()
        return None

    def flush(self) -> Utterance | None:
        """Complete whatever finals have accumulated (stream closing)."""
        self._partial = ""
        return self._complete("flush", self._clock()) if self._segments else None

    def _heard(self, event: TranscriptEvent) -> None:
        if not event.text:
            return
        now = event.received_at or self._clock()
        if not self.in_speech:
            # A SpeechStarted with no words for a while was noise: this is a new start.
            recent = self._start_pending and now - (self.speech_started_at or now) < 3.0
            if not recent:
                self.speech_started_at = now
        self._start_pending = False
        self.last_speech_at = now

    def _complete(self, trigger: Trigger, at: float) -> Utterance | None:
        segments, self._segments = self._segments, []
        self._end_pending = False
        self._start_pending = False
        text = " ".join(s.text for s in segments).strip()
        if not text:
            return None
        if is_filler(text) and not self.expect_short_answer:
            self.dropped_fillers += 1
            return None
        confidences = [s.confidence for s in segments if s.confidence is not None]
        return Utterance(
            session_id=self.session_id,
            text=text,
            confidence=min(confidences) if confidences else None,
            started_at=segments[0].start_s,
            ended_at=segments[-1].end_s,
            completed_at=at,
            trigger=trigger,
            segments=len(segments),
        )
