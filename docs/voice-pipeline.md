# Voice pipeline (Phase 6)

How one screening call works, from the phone's audio to the agent's voice and back. Plan: [phases/phase-06-voice-conversation.md](phases/phase-06-voice-conversation.md). Telephony protocol: [telephony.md](telephony.md). Agent logic: [agent.md](agent.md).

## 1. Shape

```text
Exotel Voicebot WS ─► websocket_handler ─► InboundQueue (2 s, drop-oldest)
                                               │
                     CallSession (voice/pipeline.py), one per call_attempt_id
                     ┌─────────────────────────┴───────────────────────────────────────┐
                     │ reader: 20 ms frames ─┬─► SpeechDetector (VAD) ─► end of speech:   │
                     │                       │                          STT finalize()   │
                     │                       │                       └► barge-in check    │
                     │                       └─► Deepgram STT ─► UtteranceAssembler       │
                     │                                                   │ UTTERANCE      │
                     │ events queue ─► driver ─► TurnManager.TABLE ─► actions             │
                     │   agent task (ConversationManager.handle_utterance, cancel-safe)   │
                     │   ack (cached "Okay.") ─┐                                          │
                     │   Player: TTS stream ───┴► 24→8 kHz ─► AudioSender (paced) ─► WS   │
                     │   mark echoed by Exotel ─► PLAYBACK_DONE                           │
                     │ timers: silence, wrap-up / time limit, event-loop lag              │
                     │ TranscriptWriter: after every turn → conversations (by seq)        │
                     └─────────────────────────────────────────────────────────────────────┘
```

- `websocket_handler.py`: accepts the stream, attaches it to the attempt (P5), builds the session (job, candidate, STT, LLM, the shared TTS, VAD, transcript writer) and runs it next to the receive loop. The agent ends the call by closing the socket (the flow's Hangup step drops the phone); a `stop` message or a dropped socket means the caller is gone.
- `pipeline.py` `CallSession`: everything that happens becomes a `TurnEvent` on the session's own queue. One driver task looks each event up in `turn_manager.TABLE` and runs the actions. No other task makes decisions, so there are no races between "the reply is ready" and "the candidate spoke again".
- All of a session's tasks run in one `asyncio.TaskGroup`. A failing task becomes a `FAILURE` event (apology, technical_failure). When the call ends the group is cancelled, the STT stream closed, the transcript flushed and the result stored. Tasks are counted before and after each stream (`stream_ended` log: `tasks_before`, `tasks_after`).
- Isolation: every queue, buffer, timer, provider stream, VAD and assembler is created by the session. `AudioSender` and `Player` carry the session id and refuse audio for another session (`CrossSessionAudioError`). The registry (`session_registry.py`) refuses a second session for the same attempt. The only shared object is the TTS provider (stateless per call apart from the fallback's sticky choice, released with `forget_call`).

## 2. Turns

| State | Meaning |
|---|---|
| `starting` | stream up, greeting not yet played |
| `listening` | the candidate's turn; silence timer running |
| `thinking` | the agent is working on a reply; an acknowledgement may be playing |
| `speaking` | the reply's audio is going out |
| `ending` | the closing line plays to the end; then hang up |

The full table is `voice/turn_manager.py` (`TABLE`, `ANY`) and is tested row by row (`test_turn_parts.py`). The main rules:

- **Greeting.** Synthesized as soon as the stream starts, played when the candidate's "Hello?" ends or after `GREETING_WAIT_MS` (1.2 s). A "hello" said before the greeting starts is dropped. An answer given while it plays ("yes, speaking") is kept and handled when it ends. The greeting is never interrupted.
- **Utterance while listening** → thinking: the agent runs, and a cached acknowledgement ("Okay.", "Got it.", "Right.", "Thank you.", "Sure."; random, never the same twice in a row) plays at once. No acknowledgement in the identity phase (the next line is a template) or after a low-confidence utterance (the reply is "sorry, could you say that again?"). A leading "Got it." in the reply is not spoken when an acknowledgement was played (the transcript keeps the full text, plus `ack`).
- **Another utterance while thinking** (the candidate paused, then went on): the agent's request is cancelled, the conversation is rolled back to before the turn (`ConversationManager.checkpoint/restore`; `handle_utterance` also undoes itself when cancelled), and the turn runs again on both utterances joined. This also covers a reply that was ready but hadn't started playing.
- **Barge-in while speaking** (`voice/interruption.py`): speech shorter than `BARGE_IN_MIN_MS` (300 ms) never interrupts. From then on it interrupts as soon as STT has a word that isn't a backchannel ("yes", "okay", "hmm", "haan", "achha"…), and after `BACKCHANNEL_MAX_MS` (600 ms) whatever it is. A finished utterance that isn't a backchannel interrupts too. On barge-in: the reply task is cancelled (the TTS request closes), `clear` is sent (Exotel drops its queued audio and never returns that mark), the heard share is estimated and the agent's turn is recorded as `interrupted` with `heard_text` (`ConversationManager.handle_interruption`), so the LLM knows its question may not have been heard. If the candidate had already heard 85% of the reply, it's counted as answering at the end of the question, not as an interruption.
- **Backchannels while speaking** are held. When the reply has played they're dropped, unless the reply asked a yes/no question (identity, permission, confirmations) or they came over its last 15%: then they're the answer.
- **Playback finished** = the `mark` sent after the reply comes back from Exotel (about 0.5 s after the audio ended at our side, P5). Timeout: buffered audio + 5 s.

## 3. End of turn and the VAD

- Deepgram's own endpointing is slow on real lines (1.6–2.3 s at p50, [benchmarks/stt.md](benchmarks/stt.md)). The local VAD (`voice/vad.py`) decides instead: speech followed by `VAD_END_SILENCE_MS` (400 ms) of silence → `DeepgramSTTProvider.finalize()`, which returns the final transcript about 0.85 s after the last word. Deepgram's endpointing (300 ms) and UtteranceEnd stay as backstops.
- A frame is speech when it is above an energy gate (`VAD_MIN_DBFS`, −45 dBFS) **and** webrtcvad (aggressiveness 2) says so. While our audio is playing (plus the playout lag), the gate rises by `VAD_ECHO_MARGIN_DB` (6 dB), so a faint echo of the agent isn't the candidate. Speech starts after `VAD_SPEECH_START_MS` (100 ms) of voiced frames (short clicks decay).
- `MAX_UTTERANCE_S` (30 s) of continuous speech forces a `finalize()` so the agent can respond.
- Without `webrtcvad-wheels` installed the VAD falls back to the energy gate alone (logged as `vad_webrtc_missing`).

## 4. Silence, limits and failures

| Situation | What happens | `end_reason` |
|---|---|---|
| No speech for `SILENCE_TIMEOUT_S` (7 s) after the agent finished | 1st: the question again in its short form ("Sorry, I'll ask again. …"); 2nd: "Are you still there? …"; 3rd: polite close | `silence_timeout` |
| The candidate is talking when the timer fires | the timer waits for the utterance (VAD or STT in speech) | |
| `CALL_WRAP_UP_S` (600 s) | after the candidate's next answer, the agent reads back what it has (`request_wrap_up`) and closes on the confirmation | `agent_completed` |
| `MAX_CALL_DURATION_S` − 20 s (880 s by default) | whatever is happening stops; closing line | `max_duration` |
| STT error (no stream for 5 s, bad key, connect failure) | apology clip, hang up | `technical_failure` |
| TTS failure (after the Kitten fallback) | apology clip, hang up | `technical_failure` |
| LLM error | the agent's P2 handling: "Sorry, could you repeat that?", then on a second failure its error close | `technical_failure` |
| Any task crashes | apology, hang up | `technical_failure` |
| Candidate hangs up | the agent gets up to 4 s to finish a turn in flight (their last answer is kept); the result is stored | `candidate_hangup` |
| Socket drops without a `stop` | as above | `technical_failure` (`failure_reason=stream_dropped`) |
| No voice loaded or no OpenAI key when the stream starts | socket closed (1011) | `technical_failure` (`voice_unavailable` / `llm_not_configured`) |

Agent outcomes map to `call_attempts.end_reason` (`pipeline.END_REASONS`): completed → `agent_completed`, callback → `callback_scheduled`, declined → `declined`, opted out → `opted_out`, wrong person → `wrong_person`, escalated → `escalated`. Migration `0004` adds these values. The terminal call status still comes from Exotel's callback.

Starting a call is refused (`voice_unavailable`) while the voice model is still loading.

## 5. Persistence

- Stream start: a `conversations` row (`transcript_service.open_conversation`).
- After every agent turn (played or interrupted): new or changed transcript entries are merged into `conversations.transcript` **by `seq`** in one UPDATE (replace same seq, append the rest, keep seq order), and the live state goes into `extracted_data.live` (field states and turn metrics). Re-sending is a no-op; an entry that changes later (interrupted) is replaced. A crash mid-call keeps everything up to the last turn.
- Entry: `{seq, speaker, text, timestamp, interrupted?, heard_text?, stt_confidence?, latency_ms?, ack?}` (empty keys dropped).
- Call end: `screening_store.store_outcome` writes the final transcript, the full result (`extracted_data.result`, plus a flat copy), `turn_metrics`, session stats and `end_reason`, and the candidate's standard fields, `screening_field_meta`, provisional `screening_status` and `opted_out`. Then `finalize_call(attempt_id)` is queued. The worker writes the recruiter summary (idempotent; Phase 7 adds the extraction pass and Sheets).

## 6. Latency

Per turn (`TurnMetrics`, logged as `voice_turn_latency`, stored in `extracted_data.turn_metrics`, printed by `make test-call`):

| Mark | Meaning |
|---|---|
| t0 | candidate stopped speaking: when the last word's audio reached STT (`STTProvider.sent_at`), or the VAD's last voiced frame |
| t1 | utterance complete (after `finalize()`) |
| t2 | agent reply ready |
| t3 | first TTS audio of the reply |
| t4 | first reply frame sent |
| t_ack | first acknowledgement frame sent |

Segments: `stt_ms` t0→t1, `llm_ms` t1→t2, `tts_ms` t2→t3, `send_ms` t3→t4, `total_ms` t0→t4, `ack_ms` t0→t_ack, `first_sound_ms` (the earlier of ack and reply). Targets (plan §5.8): STT ≤ 600 ms, LLM ≤ 2.5 s, first TTS ≤ 300 ms, first sound ≤ 1.0 s, full reply ≤ 3.5 s at p50. Measured values: [test-calls/phase-06.md](test-calls/phase-06.md).

The candidate hears our audio about `PLAYOUT_LAG_MS` (400 ms) after our playhead; the heard-portion estimate subtracts it.

**Voice.** Since 2026-11-19 Kitten TTS (Iris, local) speaks and Deepgram Aura is the fallback (user's choice after live calls; `providers/tts/__init__.py`). Kitten renders a sentence whole (p95 ~450 ms on the dev Mac), so the warm-up below matters for it too.

**TTS warm-up.** On 2026-11-19 Deepgram's first audio took about 1.0 s from this network, whatever the text length (TCP connect alone ~330 ms; even `GET /v1/projects` took ~1.1 s), against 340 ms in the Phase 3 benchmark. Connection reuse doesn't change it (measured: 5 s vs 120 s keep-alive). But the agent nearly always ends its reply with the job's question word for word, and the acknowledgement already covers "Got it." / "Thanks." So while the greeting plays, the session synthesizes the job's question prompts and a few openers into the provider's cache (`VOICE_TTS_WARM`, about 600 characters, ~$0.02 per call). A reply that matches plays in ~1 ms. Re-measure Deepgram from the production VM in Phase 10.

**Simulated calls** (`make voice-sim`: the real `CallSession` with real Deepgram STT, OpenAI and the Deepgram voice; macOS `say` as the candidate at phone quality with a faint noise floor; a loopback line that paces audio and echoes marks like Exotel; nothing written to the database):

| Run (2026-11-19) | Turns | First sound p50 / p95 | Reply (t0→t4) p50 / p95 | STT p50 | LLM p50 | TTS p50 | Result |
|---|---|---|---|---|---|---|---|
| s14 happy path, Rishi, no warm-up | 12 | 783 / 939 ms | 4 425 / 4 977 ms | 763 ms | 2 483 ms | 992 ms | all 10 fields right, completed |
| s14 happy path, Rishi, warm-up | 12 | 778 / 915 ms | **3 210** / 4 407 ms | 754 ms | 2 448 ms | 1 ms | all 10 fields right, completed |
| s07 callback tomorrow 5 PM, Tara | 2 | | | | | | "Friday, 20 November at 5 PM", `callback_scheduled` |

Only linear scenarios suit the simulator: it plays the script's lines in order, whatever the agent asked.

Event-loop lag is sampled every 0.5 s per session (`event_loop_lag` warning over 100 ms; `max_loop_lag_ms` in the session stats).

## 7. Tests

- `tests/unit/voice/test_turn_parts.py`: VAD, barge-in rules, backchannels, heard portion, the turn table row by row, playback (frames, marks, prefetch split, `clear`, heard estimate, cross-session refusal), registry.
- `tests/unit/voice/test_call_session.py`: the session harness (`session_harness.py`, test only: fake STT, TTS and phone line, scripted LLM, audio feeder). Turn order and acknowledgements, hello handling, merging, barge-in, backchannels, yes-at-the-end, silence escalation, STT/TTS failures, agent close, hang-up while thinking, socket drop, time limit, two parallel sessions (isolation), 20 sequential sessions (no tasks left behind).
- `tests/integration/test_telephony.py`: the real stream handler running a conversation (fake providers, real Postgres/Redis): transcript, result, `end_reason`, slot released, `finalize_call` queued; no voice → technical failure; calls refused while the voice loads.
- `tests/integration/test_transcript_service.py`: merge by seq, idempotency, replacement; `finalize_call` writes the summary once.
- `make voice-sim [SCRIPT=…] [VOICE=…]`: a whole call with real providers and no phone (host; a few cents). Writes a stereo WAV (left the candidate, right the agent) to `backend/artifacts/voice-sim/`.
- Real calls: [test-calls/phase-06.md](test-calls/phase-06.md).
