# Phase 4: STT integration (Deepgram streaming)

| | |
|---|---|
| Source | plan.md §10 Phase 4, Module D (STT service, VAD) |
| Depends on | P0; P2 for P4-T7 (transcripts → agent) |
| Unlocks | P6 |
| Size / risk | M / Medium |

## 1. Goal

Per-session streaming transcription through Deepgram, behind `STTProvider`: audio goes in; partial and final transcripts and end-of-utterance events come out. It's robust to silence and errors, and every transcript is tied to its session. Final utterances drive the P2 agent in a local microphone loop.

## 2. Entry criteria

P0 accepted; P2 agent working (for P4-T7). `DEEPGRAM_API_KEY` with streaming access. A microphone and headphones.

## 3. Scope

- **In:** plan.md tasks 1–7, utterance assembly, recorded test audio, accuracy and latency benchmarks, a local voice loop.
- **Out:** telephony audio (P5), barge-in and local VAD for interruption (P6).

## 4. Deliverables

```text
backend/app/providers/stt/  base.py  deepgram_provider.py
backend/app/voice/          utterance.py (UtteranceAssembler)  local_loop.py
backend/app/scripts/        stt_file.py  stt_mic.py
backend/app/tests/          unit/voice/test_utterance.py  integration/test_deepgram.py (marked stt)
                            fixtures/deepgram_events/*.json   (recorded, sanitized)
docs/benchmarks/stt.md
```

Test audio recordings are stored per the decision in §10.

## 5. Design

### 5.1 Interface

plan.md's interface, with events returned as a typed stream:

```python
@dataclass(frozen=True)
class TranscriptEvent:
    session_id: str
    kind: Literal["partial", "final", "speech_started", "utterance_end", "error", "closed"]
    text: str = ""
    confidence: float | None = None
    start_s: float | None = None
    end_s: float | None = None
    endpoint: bool = False          # provider says the speaker finished (speech_final)
    received_at: float = 0.0        # monotonic clock

class STTProvider(ABC):
    async def start_stream(self, *, session_id: str, encoding: str, sample_rate: int, channels: int = 1) -> None
    async def send_audio(self, audio_chunk: bytes) -> None
    async def get_transcription(self) -> TranscriptEvent     # next event (plan.md's name)
    def events(self) -> AsyncIterator[TranscriptEvent]       # iterator over get_transcription
    async def close(self) -> None                            # flush, then close
```

One provider instance per call session. Streams are never shared.

### 5.2 Deepgram streaming specifics [Verify all against current Deepgram docs]

- WebSocket `wss://api.deepgram.com/v1/listen`, header `Authorization: Token <key>`.
- Starting query parameters:
  - `model`: compare `nova-3` + `language=en` with `nova-2` + `language=en-IN`
  - `encoding`, `sample_rate`: match the input (telephony format confirmed in P5; likely 8 kHz linear16)
  - `channels=1`, `interim_results=true`, `endpointing=<ms>`, `utterance_end_ms=1000`, `vad_events=true`, `smart_format=true`, `punctuate=true`
  - keyword/keyterm boosting for company names, cities, "CTC", "LPA", "lakhs"
- Server messages used: `Results` (`is_final`, `speech_final`, alternative transcript and confidence), `UtteranceEnd`, `SpeechStarted`, `Metadata`, errors.
- Client control messages: `KeepAlive` while no audio is being sent (the connection closes after roughly 10 s idle), `CloseStream` to flush on close.
- Client: a plain `websockets` client is recommended over the SDK. The protocol surface is small and SDK major versions have changed APIs. Pin whichever you use.

### 5.3 Utterance assembly (`voice/utterance.py`)

- Accumulate `is_final` segments into the current utterance; partials only update a live preview.
- The utterance completes on `speech_final=true` **or** `UtteranceEnd`, whichever comes first; the second signal for the same utterance is ignored.
- Emit `Utterance(text, confidence, started_at, ended_at, session_id)`; confidence is the minimum across segments.
- Ignore empty finals. Ignore filler-only utterances ("uh", "hmm") unless the agent is waiting on a yes/no answer.
- Unit-tested with **recorded** Deepgram event sequences captured in this phase (real data, sanitized).

## 6. Tasks

### P4-T1 Create the STT provider interface

As in 5.1.

### P4-T2 Integrate Deepgram streaming transcription

- Connect with a 3 s timeout, up to 3 attempts with backoff.
- Reader task parses server messages into `TranscriptEvent`s; keepalive task runs during silence.
- `close()` sends `CloseStream` and waits up to 2 s for final results.

### P4-T3 Send test microphone audio

- `scripts/stt_mic.py`: microphone (sounddevice, 16 kHz mono) → STT, live console view.
- `scripts/stt_file.py --realtime`: streams a WAV in 20 ms chunks at real-time pace, which mimics a live call.
- Test the **8 kHz** version of every clip too. Production audio is narrowband.

### P4-T4 Receive partial and final transcripts

Event mapping plus the UtteranceAssembler (5.3). The console shows partials live and finals with latency.

### P4-T5 Handle silence

- Keepalive while no audio flows; long silence never closes the stream.
- Expose speech-start and last-speech timing so P6's turn manager can run silence timeouts.

### P4-T6 Handle transcription errors

| Error | Handling |
|---|---|
| Mid-stream disconnect | Reconnect and resume; buffer up to 2 s of audio in a bounded queue (oldest dropped, logged) |
| No working stream for > 5 s | Emit an `error` event; the session apologizes and ends (P6) |
| Invalid key | Fail fast at session start with a clear error |
| Low confidence | Pass confidence to the agent, which asks for clarification (P2-T8) |
| Empty final | Ignored |

### P4-T7 Connect final transcripts to the screening agent

`voice/local_loop.py`: microphone → STT → UtteranceAssembler → `ConversationManager.handle_utterance` → print the reply (optionally speak it with Kitten through headphones). Every log line carries `session_id`.

### P4-T8 Test audio set (added)

Record 15–20 clips from at least 3 consenting speakers with Indian-English accents:
- screening answers with numbers, company names and cities
- several answers in one sentence
- long pauses mid-answer
- background noise (fan, traffic, TV)

### P4-T9 Benchmark and tune (added)

For each configuration (model × language × 8 kHz/16 kHz), measure:
- **key-entity accuracy:** numbers, companies and cities transcribed correctly (more useful here than generic WER)
- **latency** from end of speech to utterance complete (p50/p95)
- **false endpoints:** utterances cut mid-thought

Tune `endpointing` between 300 and 800 ms using the recordings; candidates pause while recalling numbers. Record results and the chosen defaults in docs/benchmarks/stt.md.

## 7. Tests

- **Unit:** event parsing from recorded JSON; UtteranceAssembler (speech_final first, UtteranceEnd first, both, empty finals, filler); bounded buffer during reconnect.
- **Integration** (live Deepgram, `@pytest.mark.stt`):
  - each fixture streamed at real-time pace → transcript contains the expected entities
  - silence-only file → no utterances, no crash, stream alive after 30 s
  - socket killed mid-stream → reconnect, session continues
  - invalid key → clean error
- **Isolation:** two sessions at once with different files → each session's utterances come only from its own file.

## 8. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P4-AC1 | Spoken English is transcribed | Entity accuracy on the fixture set recorded; live mic demo |
| P4-AC2 | Final transcripts reach the agent | Local loop: every finished utterance produces exactly one agent reply; logs show the pairs |
| P4-AC3 | Empty or failed transcription doesn't crash the session | Silence, disconnect and bad-key tests pass |
| P4-AC4 | Each transcript is linked to its correct call session | Concurrent two-session test passes |
| P4-AC5 (added) | Latency is known | End-of-speech → utterance-complete p50/p95 at 8 kHz recorded |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Accuracy on numbers and names in narrowband audio | Compare models; keyword boosting; agent confirms key numbers (P2) |
| Endpointing cuts candidates off | Tune with real recordings; UtteranceEnd backstop; P6 merges quick follow-ups |
| Provider protocol or SDK changes | Thin adapter; recorded-fixture tests |
| Cost of idle streams | Close streams as soon as the session ends |

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| Model / language | Chosen from the P4-T9 benchmark |
| Commit voice recordings to the repo | No; keep them in a private folder or bucket, with speaker consent |

## 11. Manual setup

Deepgram API key; consent from the people recording test clips.

## 12. Exit

[Phase exit report](README.md#phase-exit-report) with the benchmark table and the chosen Deepgram settings.
