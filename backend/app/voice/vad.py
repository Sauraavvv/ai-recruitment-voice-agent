"""Local voice activity detection on inbound phone audio (phase-06 §5.3).

Two jobs, both faster than Deepgram's own endpointing on a real line (docs/benchmarks/stt.md):
- **End of turn**: speech followed by `end_silence_ms` of silence → the pipeline calls
  `STTProvider.finalize()`, so the transcript arrives ~0.85 s after the last word instead of
  1.6-2.3 s. Deepgram's endpointing and UtteranceEnd stay as backstops.
- **Barge-in**: how long the candidate has been speaking right now (`run_ms`), for
  `voice/interruption.py`.

A frame counts as speech when its level is above an energy gate **and** the classifier says so
(webrtcvad when installed, energy alone otherwise). While the agent is speaking, the gate rises
by `echo_margin_db` so a faint echo of our own voice isn't taken for the candidate.

Pure and frame-driven: the caller passes each 20 ms frame with its arrival time, so tests are
deterministic. One detector per call session.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.utils.log import get_logger

logger = get_logger(__name__)

Classifier = Callable[[bytes], bool]


def frame_dbfs(frame: bytes) -> float:
    """Level of a linear16 frame in dBFS (digital silence → -inf)."""
    if len(frame) < 2:
        return -math.inf
    samples = np.frombuffer(frame[: len(frame) // 2 * 2], dtype="<i2").astype(np.float32)
    rms = float(np.sqrt(np.mean(samples * samples)))
    return 20 * math.log10(rms / 32768.0) if rms > 0 else -math.inf


def webrtc_classifier(sample_rate: int, aggressiveness: int) -> Classifier | None:
    """webrtcvad's GMM speech classifier, or None if the package isn't installed."""
    try:
        import webrtcvad
    except ImportError:
        return None
    vad = webrtcvad.Vad(aggressiveness)

    def classify(frame: bytes) -> bool:
        try:
            return bool(vad.is_speech(frame, sample_rate))
        except Exception:  # wrong frame length: 10, 20 or 30 ms only
            return True  # let the energy gate decide

    return classify


def default_classifier(sample_rate: int, aggressiveness: int) -> tuple[Classifier, str]:
    classifier = webrtc_classifier(sample_rate, aggressiveness)
    if classifier is None:
        logger.warning("vad_webrtc_missing", detail="falling back to an energy-only VAD")
        return (lambda _frame: True), "energy"
    return classifier, f"webrtcvad-{aggressiveness}"


@dataclass(frozen=True)
class VadEvent:
    kind: Literal["speech_start", "speech_end"]
    at: float  # monotonic: when speech started / the last voiced frame ended (t0)
    speech_ms: float  # length of the speech run


@dataclass
class VadStats:
    frames: int = 0
    voiced_frames: int = 0
    speech_runs: int = 0
    gated_by_echo: int = 0  # frames that would have been speech without the echo margin


class SpeechDetector:
    def __init__(
        self,
        classifier: Classifier,
        *,
        frame_ms: float = 20.0,
        start_ms: float = 100.0,
        end_silence_ms: float = 400.0,
        min_dbfs: float = -45.0,
        echo_margin_db: float = 6.0,
        name: str = "custom",
    ) -> None:
        self.classifier = classifier
        self.frame_ms = frame_ms
        self.start_ms = start_ms
        self.end_silence_ms = end_silence_ms
        self.min_dbfs = min_dbfs
        self.echo_margin_db = echo_margin_db
        self.name = name
        self.echo = False  # the agent is speaking: raise the gate
        self.in_speech = False
        self.speech_started_at: float | None = None
        self.last_voice_at: float | None = None
        self._run_ms = 0.0  # voiced time accumulating towards a start (decays on silence)
        self._silence_ms = 0.0
        self.stats = VadStats()

    @property
    def gate_dbfs(self) -> float:
        return self.min_dbfs + (self.echo_margin_db if self.echo else 0.0)

    def run_ms(self, now: float) -> float:
        """How long the current speech has lasted (0 when not in speech)."""
        if not self.in_speech or self.speech_started_at is None:
            return 0.0
        return max(0.0, (now - self.speech_started_at) * 1000)

    def is_voiced(self, frame: bytes) -> bool:
        level = frame_dbfs(frame)
        if level < self.min_dbfs:
            return False
        voiced = self.classifier(frame)
        if voiced and level < self.gate_dbfs:
            self.stats.gated_by_echo += 1
            return False
        return voiced

    def process(self, frame: bytes, at: float) -> VadEvent | None:
        """Feed one frame that finished arriving at monotonic time `at`."""
        voiced = self.is_voiced(frame)
        self.stats.frames += 1
        if voiced:
            self.stats.voiced_frames += 1
        if not self.in_speech:
            if voiced:
                self._run_ms += self.frame_ms
                if self._run_ms >= self.start_ms:
                    self.in_speech = True
                    self.speech_started_at = at - self._run_ms / 1000
                    self.last_voice_at = at
                    self._silence_ms = 0.0
                    self.stats.speech_runs += 1
                    return VadEvent("speech_start", self.speech_started_at, self._run_ms)
            else:
                self._run_ms = max(0.0, self._run_ms - self.frame_ms)
            return None
        if voiced:
            self.last_voice_at = at
            self._silence_ms = 0.0
            return None
        self._silence_ms += self.frame_ms
        if self._silence_ms >= self.end_silence_ms:
            return self._end()
        return None

    def reset(self) -> VadEvent | None:
        """Forget the current run (e.g. after barge-in was handled). Returns the end event if
        speech was in progress."""
        event = self._end() if self.in_speech else None
        self._run_ms = 0.0
        return event

    def _end(self) -> VadEvent:
        started = self.speech_started_at or 0.0
        ended = self.last_voice_at or started
        self.in_speech = False
        self._run_ms = 0.0
        self._silence_ms = 0.0
        return VadEvent("speech_end", ended, max(0.0, (ended - started) * 1000))
