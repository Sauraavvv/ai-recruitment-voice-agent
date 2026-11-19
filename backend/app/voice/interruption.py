"""Barge-in: when the candidate's speech during the agent's playback is an interruption
(phase-06 §5.3, §5.4).

Rules while the agent speaks:
- Speech shorter than `min_ms` never interrupts (clicks, coughs, line noise).
- From `min_ms` on, it interrupts as soon as the live transcript has a word that isn't a
  backchannel ("yes", "okay", "hmm", "haan"...).
- Speech that keeps going past `backchannel_max_ms` interrupts whatever the transcript says
  (Deepgram's partials can lag behind the audio).
- A finished utterance that arrives during playback and isn't a backchannel interrupts too
  (a short "no, fifteen" can finish before the rules above fire).

The steps after a barge-in (`clear`, heard portion, `ConversationManager.handle_interruption`)
are in `voice/pipeline.py`; `Player.interrupt()` sends `clear`.
"""

import re
from dataclasses import dataclass

BACKCHANNELS = frozenset(
    {
        "yes", "yeah", "yep", "ya", "yah", "ok", "okay", "k", "hmm", "hm", "mm", "mhm", "mmhmm",
        "mm-hmm", "uh-huh", "uh", "um", "right", "sure", "fine", "alright", "correct", "haan",
        "han", "ha", "ji", "achha", "acha", "accha", "theek", "thik", "hai", "hello", "hi",
    }
)  # fmt: skip

_WORDS = re.compile(r"[a-z'-]+")


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def is_backchannel(text: str) -> bool:
    """Empty, or only backchannel words (at most 3 of them: "yes yes okay")."""
    ws = words(text)
    return len(ws) <= 3 and all(w in BACKCHANNELS for w in ws)


@dataclass(frozen=True)
class BargeInDecision:
    interrupt: bool
    reason: str = ""


class BargeInPolicy:
    def __init__(self, *, min_ms: float = 300.0, backchannel_max_ms: float = 600.0) -> None:
        self.min_ms = min_ms
        self.backchannel_max_ms = max(backchannel_max_ms, min_ms)

    def check(self, speech_ms: float, preview: str) -> BargeInDecision:
        """While the agent speaks: `speech_ms` of continuous candidate speech so far, `preview`
        = what STT has heard of it."""
        if speech_ms < self.min_ms:
            return BargeInDecision(False)
        if not is_backchannel(preview):
            return BargeInDecision(True, "words")
        if speech_ms >= self.backchannel_max_ms:
            return BargeInDecision(True, "long_speech")
        return BargeInDecision(False)

    @staticmethod
    def utterance_interrupts(text: str) -> bool:
        return not is_backchannel(text)


def heard_portion(text: str, heard_ms: float, total_ms: float) -> str:
    """The words of `text` the candidate probably heard, by playback time."""
    tokens = text.split()
    if not tokens or total_ms <= 0:
        return ""
    share = max(0.0, min(1.0, heard_ms / total_ms))
    n = round(len(tokens) * share)
    return " ".join(tokens[:n])
