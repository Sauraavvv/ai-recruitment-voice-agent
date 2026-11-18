# Phase 6: Complete voice conversation

| | |
|---|---|
| Source | plan.md §10 Phase 6, Module D (pipeline, VAD, interruption), Module F (call lifecycle), Module G (transcript) |
| Depends on | P2 (agent), P3 (TTS), P4 (STT), P5 (go decision and verified protocol) |
| Unlocks | P7 |
| Size / risk | XL / **High** |

## 1. Goal

Real screening calls work end to end. The candidate's speech reaches the agent and the agent's voice reaches the candidate with natural turn-taking, interruption handling, silence and timeout handling and a clean ending. The transcript is stored as the call happens, and calls are strictly isolated from each other.

## 2. Entry criteria

P2 acceptance passed; P3 voice chosen; P4 Deepgram settings chosen; P5 go decision with the media protocol documented.

## 3. Scope

- **In:** plan.md tasks 1–10, latency instrumentation, a real-call test programme.
- **Out:** post-call extraction, summary persistence and Sheets (P7); UI (P8).

## 4. Deliverables

```text
backend/app/voice/
  pipeline.py           # CallSession
  websocket_handler.py  # production handler (replaces the P5 PoC)
  audio_processor.py    # decode, frame
  vad.py  interruption.py  turn_manager.py  playback.py  session_registry.py
backend/app/agent/conversation_manager.py   # silence, interruption, resume hooks
backend/app/services/transcript_service.py
docs/voice-pipeline.md
docs/test-calls/phase-06.md
```

## 5. Design

### 5.1 One session per call

```text
┌─────────────────────────────── CallSession (one per call_attempt_id) ───────────────────────────────┐
│ WS in ─► inbound reader ─► decode ─┬─► local VAD ───────────────► barge-in signal ─┐                  │
│                                    └─► STT stream ─► UtteranceAssembler ───────────┴─► TurnManager     │
│                                                                                         │            │
│ WS out ◄─ paced sender ◄─ frame queue ◄─ converter ◄─ Kitten TTS ◄─ chunker ◄─ Agent ◄──┘            │
│ timers: silence, max duration          transcript writer: per turn → Postgres                        │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- The session's tasks run in one `asyncio.TaskGroup`. Any fatal error → `session.end(reason)` → group cancelled → cleanup (close STT, flush transcript, stop timers, unregister, release slot).
- Every queue, buffer, timer and provider stream is created by the session and referenced only by it. No module-level mutable audio state (plan.md: no audio crossing between candidates).
- Outbound frames carry the session id; the sender checks it matches before writing.

### 5.2 Turn manager

States: `LISTENING`, `THINKING`, `SPEAKING`, `ENDING`.

| Event | In state | Action |
|---|---|---|
| Stream starts | — | Wait up to 1.2 s for the candidate's "Hello?", then play the greeting (pre-synthesized when the provider reports ringing or answer) |
| Utterance complete | LISTENING | → THINKING; `agent.handle_utterance` |
| First TTS chunk ready | THINKING | → SPEAKING; start playback |
| Another utterance before playback starts | THINKING | Cancel the in-flight agent request, merge the texts, run again (the candidate was still talking) |
| Playback finished (mark acknowledgement or computed duration) | SPEAKING | → LISTENING; start the silence timer |
| Candidate speaks during playback (barge-in) | SPEAKING | Stop playback (5.4); → LISTENING |
| Agent action `end_call` | any | Play the closing; → ENDING; hang up after playback |

### 5.3 Voice activity detection (`voice/vad.py`)

- End of utterance comes from Deepgram endpointing and UtteranceEnd (P4).
- **Measured in P4 (2026-11-18, docs/benchmarks/stt.md):** on a realistic line (a faint noise floor rather than digital silence) Deepgram's own endpointing takes about 1.6–2.3 s at p50 from the last word, far over the 600 ms budget below. When a local end-of-speech detector calls `DeepgramSTTProvider.finalize()` 400 ms after speech stops, the final arrives about 0.85 s after the last word (p50; p95 1.35 s). So use the local VAD for end of turn too: VAD silence ≥ 400 ms after speech → `finalize()`; Deepgram's endpointing (300 ms) and UtteranceEnd stay as backstops. Merge an utterance that follows within about 1 s (the candidate was only pausing) before the agent replies. Alternative to evaluate here: Deepgram Flux (`/v2/listen`, model-based end of turn, p50 about 1.1 s, but missed turns under continuous background noise and Deepgram refused many connections with HTTP 503 during P4).
- Barge-in needs a faster local signal. Run a lightweight VAD on inbound frames: start with `webrtcvad` (20 ms frames, aggressiveness 2–3); try Silero VAD (ONNX, more robust to noise) if false triggers show up.
- Minimum 300 ms of speech before barge-in. Short backchannels ("yes", "okay", "hmm", under about 600 ms) while the agent speaks don't interrupt.
- Raise the threshold during SPEAKING if the agent's own voice leaks back as echo; measure on real calls.
- Maximum utterance 30 s, then force end of turn so the agent can respond.

### 5.4 Interruption (`voice/interruption.py`)

1. Stop dequeuing outbound frames and drop the rest of the current reply.
2. Send the protocol's buffer-clear message if P5 confirmed it exists. Otherwise rely on the small send-ahead buffer (≤ 200 ms) so audio stops quickly.
3. Estimate how much of the reply was heard (frames sent minus frames still buffered) and record the agent turn as `interrupted`, with the heard portion.
4. Call `agent.handle_interruption(heard_portion)` so the agent knows its question may not have been heard.

Target: audio stops within 500 ms of the candidate starting to speak, where the protocol allows it.

### 5.5 Silence, timeouts and failures

| Situation | Handling |
|---|---|
| No speech 7 s after the agent finishes | Re-prompt with a shorter version of the question |
| Second silence | "Are you still there?" |
| Third silence | Polite close; `end_reason=silence_timeout`; screening partially completed |
| Call longer than 10 min (configurable) | Wrap up, confirm, close |
| STT unavailable > 5 s | Apology, end; `technical_failure` (retry-eligible in P9) |
| LLM timeout or error after one retry | One short holding phrase, retry; still failing → apology, end, `technical_failure` |
| TTS failure | Retry once; apology clip; end |
| Candidate hangs up | Finalize immediately with the data collected so far |
| WebSocket drops while the call is alive | Hang up via the provider API; `technical_failure` |

All fallback audio is pre-synthesized by Kitten at startup (P3-T9). A scripted fake conversation is never used.

### 5.6 Call completion

- Agent `end_call` or a terminal phase → closing template → wait for playback to finish → hang up through the provider → end the session.
- `end_reason` values: `agent_completed`, `candidate_hangup`, `declined`, `opted_out`, `callback_scheduled`, `wrong_person`, `silence_timeout`, `max_duration`, `technical_failure`.
- On end: write the final state snapshot, set a provisional `screening_status`, and enqueue `finalize_call(attempt_id)` (completed in P7).

### 5.7 Transcript persistence (Module G)

- A `conversations` row is created when the stream starts.
- After every turn, append atomically to `conversations.transcript` (JSONB `||`) an entry `{seq, speaker, text, ts, interrupted?, stt_confidence?, latency_ms?}`, and save the state snapshot to `conversations.extracted_data`. A crash mid-call keeps everything up to the last turn (plan.md: partial calls preserve information).
- Appends are idempotent by `seq`.

### 5.8 Latency budget and instrumentation

Per turn, record:
- **t0** candidate stops speaking (VAD)
- **t1** utterance complete (STT)
- **t2** agent reply ready (LLM)
- **t3** first TTS chunk ready
- **t4** first audio frame sent

| Segment | Proposed p50 target |
|---|---|
| t0 → t1 (STT endpoint) | ≤ 600 ms |
| t1 → t2 (LLM) | ≤ 2,500 ms (revised after P2; measured p50 2.3 s, p95 3.5 s) |
| t2 → t3 (first TTS chunk) | ≤ 300 ms |
| t0 → t4 (total) | ≤ 3.5 s for the full reply; **≤ 1.0 s to the first sound** (the acknowledgement below) |

**Masking the LLM wait (decided in P2, 2026-11-18).** One OpenAI turn takes about 2.3 s at p50 (3.5 s at p95) with `gpt-5.4-mini`. The round trip alone is about 1 s, so neither a smaller model nor a smaller schema reaches 1.2 s (see docs/agent.md). Instead, as soon as STT finalizes an utterance, play a short pre-synthesized acknowledgement from the phrase cache ("Okay.", "Got it.", "Mm-hmm, one second."). Pick it at random and avoid repeating the previous one. Then speak the agent's reply. Skip it when the reply is a fixed template (greeting, introduction, exits) or comes from a low-confidence re-prompt. Strip a leading acknowledgement from the LLM reply when one was already played, so the caller doesn't hear "Got it. Got it." Measure t0 → first acknowledgement frame as its own segment.

Ways to hit the targets: short first chunk, synthesize chunk N+1 while N plays, phrase cache, pre-synthesized greeting, compact prompts.

**TTS from Phase 3 (2026-11-18):** the primary voice is Deepgram Aura (Harmonia), with Kitten as fallback (`FallbackTTSProvider`). Play replies with `tts.stream(text, call_attempt_id=…)`, never `synthesize()`. Deepgram's first audio comes after about 350 ms but the whole clip takes about half its duration (docs/benchmarks/tts.md), so t2 → t3 is about 350 ms with Deepgram and 200–400 ms with Kitten. On barge-in, stop iterating the stream: the provider closes the HTTP request. At call end, call `tts.forget_call(call_attempt_id)`. Use `tts.apology_clip(call_attempt_id=…)` so the apology matches the voice the call is using. Log each turn with `candidate_id`, `call_attempt_id` and `provider_call_id` (plan.md §12), and monitor event-loop lag.

### 5.9 Resuming with known data

`ConversationManager` can start with fields already known for the candidate, so callbacks and retries (P9) don't re-ask them. In this phase, first calls start empty apart from identity and job context.

## 6. Tasks

| ID | Plan task | Work |
|---|---|---|
| P6-T1 | Connect incoming audio to VAD | Decode, frame to 20 ms, VAD per frame |
| P6-T2 | Connect VAD to STT | Forward all inbound audio to STT (it does its own endpointing); VAD drives barge-in and timing |
| P6-T3 | Connect STT to the screening agent | UtteranceAssembler → TurnManager → ConversationManager |
| P6-T4 | Connect agent output to Kitten TTS | Normalizer → chunker → TTS executor; chunk N+1 synthesized during playback of N |
| P6-T5 | Connect TTS audio to the telephony stream | Converter → framer → paced sender (P5) |
| P6-T6 | Conversational turn management | 5.2 |
| P6-T7 | Interruption handling | 5.3 and 5.4 |
| P6-T8 | Silence and timeout handling | 5.5 |
| P6-T9 | Call completion logic | 5.6 |
| P6-T10 | Save transcript messages | 5.7 |
| P6-T11 (added) | Latency instrumentation | 5.8 |
| P6-T12 (added) | Session registry and cleanup | Registry keyed by attempt id; after each session, tasks, streams and buffers are released |
| P6-T13 (added) | Real-call test programme | §7.2 |

## 7. Tests

### 7.1 Automated

- **Unit:** turn-manager transitions (table-driven), barge-in thresholds, backchannel filter, silence escalation, merge-on-new-utterance, playback-position estimate, idempotent transcript append.
- **Session harness (tests only):** drives `CallSession` with recorded inbound audio and captured protocol messages, using real STT, LLM and TTS. Checks turn order, transcript and cleanup. It's clearly labelled as a harness and never writes call outcomes to the production database.
- **Isolation:** two harness sessions in parallel with different candidates and audio → each session's outbound text and transcript contain only its own candidate's name and answers; no shared objects (identity checks on queues and streams).
- **Leak test:** 20 sequential harness sessions → task count and memory return to baseline.

### 7.2 Real calls

Testers follow scenario cards (persona, answers, behaviour to perform):

1. Happy path, clear speech
2. Two answers in one sentence
3. Refuses to share salary
4. Busy; asks for a callback tomorrow at 5 PM
5. Not interested
6. "Don't call me again"
7. Interrupts the agent mid-question
8. Long pauses while thinking
9. Noisy background (street, fan, TV)
10. Fast speech, short answers
11. Corrects an earlier answer
12. Hangs up halfway

Log each call in docs/test-calls/phase-06.md: attempt id, tester, network, expected vs captured fields, latency p50/p95, interruption handling, issues.

## 8. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P6-AC1 | Candidate can complete a real screening call | At least 3 complete calls by different testers (Definition of Done requires three) |
| P6-AC2 | Agent can ask the required questions | Each transcript covers every required field, asked once or answered unprompted |
| P6-AC3 | Agent understands candidate answers | Captured vs scenario-card values: ≥ 90% field accuracy across the programme |
| P6-AC4 | Agent handles natural variations | Cards 2, 3, 8, 10 and 11 pass |
| P6-AC5 | Agent stops playback when interrupted, where the protocol supports it | Card 7: measured stop latency ≤ 500 ms, or the protocol limit documented |
| P6-AC6 | No audio crosses between sessions | Isolation test passes; two simultaneous real calls (if the account allows) each hear only their own conversation |
| P6-AC7 (added) | Transcript saved per turn | Card 12: transcript and answers up to the hang-up are in the database |
| P6-AC8 (added) | Latency measured | Per-turn table in the docs; t0 → t4 p50 reported against the target |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Slow responses make the agent feel robotic | Per-segment budget; overlap TTS with playback; faster model |
| False barge-in from echo or noise | VAD thresholds, minimum duration, backchannel filter; Silero if needed |
| Barge-in slow without a clear message | Small send-ahead buffer |
| STT errors on numbers | Confirmation step (P2); clarification on low confidence |
| Event loop blocked | TTS on an executor; lag monitoring |
| Resource leaks over many calls | Registry and leak test |

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| Silence timeout and max call length | 7 s and 10 minutes |
| Filler phrases when the agent is slow | Off by default |
| Wait for "Hello?" before greeting | Yes, up to 1.2 s |

## 11. Manual setup

Testers available on different networks and devices; scenario cards printed or shared.

## 12. Exit

[Phase exit report](README.md#phase-exit-report) with the test-call log and latency table.
