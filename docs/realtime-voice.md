# Realtime voice engine (trial)

Added 2026-11-19 at the user's request, **next to** the Phase 6 pipeline, to compare the two on
real calls before deciding what to keep. Nothing in the pipeline was changed or removed.

| | Pipeline (default) | Realtime (trial) |
|---|---|---|
| Hearing | Deepgram nova-3 en-IN + local VAD | the Realtime model (server VAD) |
| Thinking | `OPENAI_MODEL` (gpt-5.4-mini), JSON turns | `OPENAI_REALTIME_MODEL` (gpt-realtime-2.1-mini), tool calls |
| Speaking | Kitten Iris (Deepgram Aura fallback) | the model's voice (`marin`) |
| Transcript | Deepgram | model output + `gpt-4o-mini-transcribe` for the candidate |
| Code | `voice/pipeline.py` | `voice/realtime_session.py`, `providers/realtime/` |

## Switching

- Settings page → **Voice engine** (applies to the next call), or `VOICE_ENGINE=realtime` in
  `.env` (default when the Settings page leaves it unset).
- Each call records the engine, token usage and an estimated cost in
  `conversations.extracted_data.session`; the candidate page's transcript shows a
  "Realtime · ~$0.05" tag.
- Without a phone: `make voice-sim ENGINE=realtime [SCRIPT=s09_opt_out]` (a few cents per run).

## How a call runs

```text
Exotel slin 8 kHz ─μ-law─► input_audio_buffer.append ─► Realtime ─► response.output_audio.delta
                                                                      │ μ-law 8 kHz
Exotel ◄─ AudioSender (paced, sliced) ◄─ playout queue ◄──────────────┘
```

- **Audio:** `audio/pcmu` both ways (the phone's own format), no resampling.
- **Fixed lines played by our code, word for word** (`response.create` "say exactly"): the
  greeting; the introduction with the AI disclosure (after `confirm_identity`); the role line +
  first question (after `confirm_permission`); the callback question/confirmation, the opt-out,
  wrong-person and time-limit goodbyes. Audio the model generates over these is cut.
- **The model asks the rest** in its own words and records answers with tools:
  `record_answer`, `record_status` (declined/unknown), `confirm_fields`, `request_callback`,
  `note_question`, `end_call`. Values go through the pipeline's `ScreeningState.merge` and
  `validate_field` (CTC/experience ranges, company/location need a name, notice period).
  After a tools-only turn the model gets a short note: what's already answered, the next
  question.
- **Opt-out safety net:** "don't call me", "remove my number", "stop calling"… in the
  candidate's transcript → the agent is stopped, the opt-out line plays, `opted_out`, hang up,
  whatever the model does.
- **Barge-in:** `speech_started` while our audio plays → Exotel `clear` +
  `conversation.item.truncate` at what was heard.
- **Silence:** our own timer from when the audio has *played* (`SILENCE_TIMEOUT_S`): "Are you
  still there?", then a goodbye (`silence_timeout`). The server's idle timer is off: it counts
  from when audio is generated and fired mid-sentence in the first trial.
- **Ending:** after the goodbye has played (mark echoed) the stream closes and the flow's
  Hangup step ends the call. The closing line without `end_call` also ends it.
- **After the call:** the same `ScreeningResult` → `store_outcome` → `finalize_call` (final
  pass over the transcript, evidence check, Sheets, summary) as the pipeline.

## Trial results (simulated calls, 2026-11-19, `make voice-sim ENGINE=realtime`)

Scripted candidate (macOS `say`, phone quality) against the real API. Earlier runs found and
fixed: introduction said twice (server idle timer), fillers ("let me note that"), re-asked
questions, paraphrased introduction, notice period sent as a number, opt-out and callback
ignored.

| Scenario | Result | First sound p50 / p95 | Est. cost | Length |
|---|---|---|---|---|
| s14 happy path | completed, 10/10 fields, all fixed lines verbatim | 1.32 s / 2.2 s | $0.050 | 140 s |
| s14 happy path (again) | completed, 10/10 | 1.67 s / 2.4 s | $0.058 | 134 s |
| s09 opt-out | opted_out, goodbye line, ended | 0.94 s / 1.8 s | $0.021 | 47 s |
| s07 callback "tomorrow at 5" | callback_requested, Fri 20 Nov 5 PM, ended | 1.7 s | $0.015 | 40 s |

Pipeline for comparison (Phase 6 real calls): reply p50 3.25 s, ~$0.07–0.10 per 3-minute call.

## Real calls

| # | Date | Result | First sound p50 / p95 | Cost | Notes |
|---|---|---|---|---|---|
| 1 `db2929ec` | 2026-11-19 | completed, 10/10 stored, finalized, summary | 1.40 s / 2.37 s | $0.067 (187 s) | "Gurugram" heard right; fixed lines kept (2 fillers cut). Tester mixed answers on purpose-like ("Current CTC is officially one one, but I can buy out for 15 days", then "Fourteen LPA" at the notice question): stored 1.1 LPA, "14 LPA" not taken for the CTC. 2 of 15 candidate lines transcribed in Devanagari/Urdu script by gpt-4o-mini-transcribe, so the final pass rejected the Gurugram evidence (live value kept). No barge-in tried. |

Fixes after call 1: transcription → `gpt-4o-transcribe` with an English-letters prompt and Indian
terms/names; the model records a value for any field the candidate mentions and asks again when
a number is unclear.

**Not yet tested:** barge-in on a real line, two calls at once, other testers. The model's wording varies between runs: before the last fixes
several runs repeated questions; the four runs after them (above) were clean. The scripted
simulator can't adapt when the model goes off script; a real caller can.

## Open questions for the decision

- Word-for-word lines: kept by our code for the compliance-critical ones; the questions are
  paraphrased by the model.
- Indian city names and company names on real lines (the pipeline's weak spot).
- Cost on real calls with real silences and corrections.
- Voice: `marin` vs Iris.
