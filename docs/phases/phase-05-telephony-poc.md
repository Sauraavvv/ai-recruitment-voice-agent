# Phase 5: Telephony proof of concept (Exotel)

| | |
|---|---|
| Source | plan.md §10 Phase 5, Module E, Module F, §6 integration endpoints |
| Depends on | P0, P1 (`call_attempts`), P3 (test clip); Exotel account with streaming enabled |
| Unlocks | P6, through the **go/no-go gate** in §9 |
| Size / risk | L / **High** |

## 1. Goal

Prove with real calls that the backend can place an outbound call through Exotel, link it to an internal call attempt, receive live caller audio, send generated audio back so the person hears it, and track the call's lifecycle through webhooks. Write down the real protocol so P6 builds on measured facts.

plan.md: "Do not fake any part of this integration." Nothing in this phase is marked done without a real call.

## 2. Entry criteria

- Exotel enablement track (P0-T13) complete: account active, ExoPhone approved, streaming confirmed in writing for **this** account.
- A public HTTPS + WSS URL for the backend (P5-T3).
- One or two people who agreed to receive test calls on their own phones, with their numbers **verified in the Exotel dashboard** (the trial account without KYC can only call verified numbers). During the PoC, only they are called.
- P1 authentication in place, because the backend becomes publicly reachable.

## 3. Scope

- **In:** plan.md tasks 1–10; the minimum of Module F (eligibility, queueing, concurrency limit, state machine, webhooks, idempotency); audio conversion utilities; a stuck-call reconciler.
- **Out:** the conversation (P6), retries (P9), UI controls (P8; this phase uses the API and a CLI script).

## 4. Deliverables

```text
backend/app/
  providers/telephony/  base.py  exotel_provider.py  exotel_models.py (payloads, status mapping)
  services/             call_service.py (eligibility, create attempt, enqueue)  call_state.py (transitions)
  workers/              call_worker.py (initiate_call job, concurrency slots, reconciler cron)
  api/v1/               calls.py (start, list, get)  webhooks.py
  voice/                websocket_handler.py (PoC: test clip + echo)  audio_converter.py
  database/migrations/  versions/0002_telephony.py
  scripts/              test_call.py
  tests/                unit/telephony/…  fixtures/exotel/ (captured real payloads, sanitized)
docs/telephony.md       (verified protocol, test-call log, go/no-go)
```

## 5. Schema additions [Proposed]

| Item | Purpose |
|---|---|
| `call_attempts.provider_status` VARCHAR | Raw provider status, kept separate from the internal status |
| `call_attempts.attempt_type` VARCHAR | `initial`, `manual`, `retry`, `callback` (P9) |
| `call_attempts.end_reason` VARCHAR | Normalized reason: no_answer, busy, invalid_number, candidate_hangup, agent_completed, technical_failure, … |
| `call_attempts.stream_id` VARCHAR NULL | Provider media stream identifier |
| Partial unique index on `call_attempts(candidate_id)` where status in (pending, queued, initiating, ringing, in_progress, retry_scheduled, callback_requested) | At most one live or scheduled attempt per candidate; prevents duplicate simultaneous calls |
| Unique `(candidate_id, attempt_number)` | Attempt numbering can't collide |
| `webhook_events` (id, provider, provider_call_id, event_type, dedupe_key UNIQUE, payload JSONB, received_at, processed_at, error) | Idempotent processing and audit trail |

## 6. Tasks

### P5-T1 Verify Exotel account and product availability

Confirm and record in docs/telephony.md, with dates and ticket references: account active; outbound calling enabled; ExoPhone/caller ID; streaming product enabled on this account; concurrency limit; DND handling; recording option. If streaming isn't available, stop (§9).

### P5-T2 Read the current official integration documentation

Write these sections of docs/telephony.md, each fact with a link and the date read:

1. **Outbound call API:** endpoint, authentication, parameters, how the call connects to the flow/app containing the streaming step, how to pass our `call_attempt_id`, response fields (provider call id).
2. **Flow configuration:** how the streaming step is configured (static or per-call WebSocket URL) and what happens after the stream ends.
3. **Status callbacks:** URL setup, HTTP method and encoding, payload fields, every status value, retry behaviour, signature or token options.
4. **Stream protocol:** handshake, message types (start, media, stop, mark, clear, dtmf…), JSON shapes, how custom parameters arrive, encoding, sample rate, channels, outgoing chunk-size rules, maximum message rate.
5. **Ending a call from our side:** REST hangup vs closing the stream.
6. **Recording:** availability, URL format, access control.

**Hypotheses to confirm before coding against them [Verify]:** Exotel's public documentation for its Voicebot/stream applet has described bidirectional JSON messages over WebSocket carrying base64 audio as 16-bit linear PCM, 8 kHz, mono, with outgoing chunks sized in multiples of 320 bytes, and `mark`/`clear` messages for playback control. Treat each of these as unverified until P5-T7 and P5-T9 measure them on a real call.

### P5-T3 Configure a public HTTPS callback endpoint

- Dev: a tunnel with a stable hostname that supports WebSockets (e.g. Cloudflare Tunnel or an ngrok reserved domain). Set `PUBLIC_BACKEND_URL` to it.
- Webhook authentication: an unguessable secret in the callback URL (query parameter or path segment), compared in constant time; plus a provider signature or IP allowlist if Exotel offers one **[Verify]**. Failures → 403, logged.
- Stream authentication: a per-attempt token in the stream URL or custom parameters, checked on connect; unknown or expired → close immediately.
- Everything else on the public URL already requires login (P1).

### P5-T4 Implement outbound call initiation

**Provider adapter** (plan.md's `TelephonyProvider`, implemented for Exotel):
- `initiate_call(candidate, call_session)` → `ProviderCall(provider_call_id, raw_status)`.
- httpx with timeouts (connect 5 s, read 10 s).
- **No automatic retry on timeout**: the call may already have been placed. Mark the attempt `initiating` with `failure_reason=initiate_timeout` and let the reconciler check the provider's status before anything else happens.
- Phone numbers are E.164 inside the system and formatted for the provider at the adapter boundary.

**Orchestration** (`call_service`, `call_worker`):
1. `POST /api/v1/calls/start {"candidate_ids": [...]}`, or `scripts/test_call.py --candidate-id …`.
2. Eligibility per candidate; every check must pass, and failures are returned per candidate:
   - not deleted, not opted out, consent recorded, phone valid, job active
   - no live or scheduled attempt (the DB index enforces this too)
   - inside the calling window (default Mon–Sat 10:00–19:00 IST **[Decision]**; configurable in P9)
   - telephony configured; voice providers healthy (enforced from P6)
3. Create the attempt (`queued`, `attempt_number = previous + 1`, `attempt_type = initial | manual`) and enqueue ARQ job `initiate_call(attempt_id)` with job id `call:{attempt_id}` for de-duplication.
4. Worker: acquire a concurrency slot (Redis semaphore of size `MAX_CONCURRENT_CALLS`; each slot has a TTL of max call duration + 5 min as a safety net). No slot → defer 15 s. Re-check eligibility (things change while queued). Set `initiating`, call the provider, store `provider_call_id`.
5. The slot is released on a terminal status (webhook), when the stream closes, or by TTL.

**State machine** (`call_state.py`): only allowed transitions; terminal states are final; out-of-order events (e.g. `ringing` after `completed`) are stored in `webhook_events` but don't change state. Telephony status stays separate from screening status (plan.md Module F).

```text
pending → queued → initiating → ringing → in_progress → completed
any non-terminal → failed | no_answer | busy | cancelled
```

**Stuck-attempt reconciler** (ARQ cron every 2 minutes, and once at worker startup): attempts in `initiating`, `ringing` or `in_progress` longer than expected → `get_call_status` from the provider → apply. If the provider has no record → `failed` with `technical_failure`.

### P5-T5 Receive provider webhooks

- `POST /api/v1/webhooks/exotel`: verify the token → parse (form or JSON per the docs) → insert into `webhook_events` with `dedupe_key = hash(provider_call_id, status, provider timestamp)`. Duplicate key → 200, no-op.
- Find the attempt by `provider_call_id` (or our id passed through the provider). Unknown → store, log, return 200 (avoids retry storms).
- Map provider status → internal status through one table in `exotel_models.py`. Store `provider_status`, timestamps, `duration_seconds`, `recording_url`, `end_reason`.
- Respond within 1 s; heavier work (finalization in P7) goes to the queue.

### P5-T6 Establish the real-time media connection

- WebSocket route at whatever path and handshake the protocol requires. plan.md's `/api/v1/webhooks/exotel/stream` is a placeholder; plan.md §6 says to follow the official protocol.
- On connect: read the handshake/start message → extract stream id, provider call id and custom parameters → resolve and verify the attempt → create an isolated `CallSession` registered under `call_attempt_id`.
- Bounded inbound queue (about 2 s of audio); overflow drops the oldest audio and logs it.
- On stop or disconnect: cancel session tasks, close resources, unregister, and release the slot if the call has ended.

### P5-T7 Inspect inbound audio

- Log the shape of the first message of each type (field names and payload lengths only, never content).
- Decode media; measure bytes per message and per second; derive encoding and sample rate and compare with the docs.
- PoC only, testers' phones only: write inbound audio to `artifacts/calls/{attempt_id}_in.wav` (gitignored; delete after review) and listen to it.

### P5-T8 Play test audio back to the phone

`voice/audio_converter.py` (pure functions, unit-tested):
- Resample from the TTS rate to the telephony rate with an anti-aliasing resampler (`soxr` or `scipy.signal.resample_poly`), never by dropping samples.
- Encode to the required codec (linear PCM or μ-law). Python 3.12's `audioop` is deprecated and removed in 3.13; use a NumPy implementation or `audioop-lts` so an upgrade doesn't break it.
- Frame into the exact required chunk size; carry the remainder into the next chunk; pad only the final frame with silence.
- Pace sending close to real time, keeping at most about 200 ms buffered ahead, so stopping playback later (barge-in) is fast.

Real-call checks:
1. Play a Kitten clip: "Hello, this is a test call from the recruitment assistant…"
2. Echo test: send the caller's own audio back after a 1 s delay. This proves full duplex and measures round-trip latency.
3. Send `mark` and `clear` messages (if supported) and record exactly what happens. P6 barge-in depends on this.

### P5-T9 Verify audio encoding and sample rate

- Record the final values in docs/telephony.md and in settings (`TELEPHONY_ENCODING`, `TELEPHONY_SAMPLE_RATE`, `TELEPHONY_FRAME_BYTES`).
- If the start message announces a media format, compare it with the configuration at runtime and refuse the session on mismatch.
- No 8 kHz or 24 kHz values hardcoded anywhere else (plan.md Module D).

### P5-T10 Verify call termination and status updates

Each case uses the testers' phones and must end with the right status on the right attempt and the slot released:

| Case | Expected |
|---|---|
| Answer, then hang up from the phone | completed; stream closed; session cleaned up |
| Backend ends the call (hangup API or stream close) | completed; phone disconnects within 2 s |
| Reject the call | busy (or the provider's equivalent) |
| Let it ring out | no_answer |
| Unassigned or invalid number | failed, `end_reason=invalid_number` |
| Phone switched off / unreachable | failed or no_answer per provider mapping (document which) |
| Same webhook delivered twice | one state change |

## 7. Tests

- **Unit:** status mapping table; transition rules including out-of-order events; webhook de-duplication; eligibility rules; audio converter (a 1 kHz sine at the TTS rate keeps its frequency and duration after resampling; μ-law round-trip error within bounds; framing with remainders; no frame exceeds the size limit).
- **Integration:** webhook endpoint fed with **captured real payloads** (sanitized); stream handler fed with captured message sequences. This is a test harness only and is never presented as a working call.
- **Manual:** the P5-T10 checklist, results logged in docs/telephony.md.

## 8. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P5-AC1 | One real test call can be initiated | `scripts/test_call.py` → tester's phone rings; attempt has `provider_call_id` |
| P5-AC2 | Candidate answers the phone | Attempt moves to `in_progress` from a provider event |
| P5-AC3 | Backend receives actual candidate audio | Inbound WAV is intelligible; measured bytes/second match the documented format |
| P5-AC4 | Backend can send generated audio back | Kitten test clip sent without protocol errors |
| P5-AC5 | Candidate can hear the AI | Tester confirms the clip is audible and clear; echo test passes |
| P5-AC6 | Call disconnects correctly | Both hang-up directions; no leftover tasks (task count before/after); slot released |
| P5-AC7 | Provider events update the correct call attempt | Two sequential calls, each event on its own attempt; duplicates ignored |
| P5-AC8 (added) | Protocol documented | docs/telephony.md filled with verified facts; go/no-go recorded |

## 9. Go / no-go gate

**Go** when P5-AC1 to P5-AC8 pass.

If bidirectional streaming isn't available on the account or doesn't work reliably: **stop**, write up the evidence, and bring options to the user (plan.md Module E). Options to evaluate, not decided here:

1. Ask Exotel to enable the streaming product on the account.
2. Another provider with Indian outbound calling and bidirectional WebSocket media streaming (check Indian caller-ID and regulatory rules for each).
3. A SIP trunk from an Indian carrier plus a self-hosted media server (more infrastructure).

The `TelephonyProvider` interface and `audio_converter` keep P6 portable whichever option is chosen.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Account lacks streaming | Enablement track from P0; the gate |
| Docs differ from real behaviour | Measure on real calls; keep raw captures |
| Tunnel drops during calls | Stable hostname; move to the real host (P10) before wider testing |
| A timed-out initiate places a call anyway | No blind retries; reconciler |
| DND and calling-hour rules | Exotel guidance recorded; calling window enforced |
| Cost | Keep test calls short; track spend |

## 11. Manual setup and credentials

Exotel API key, token, account SID and subdomain; ExoPhone; a flow/app with the streaming step pointing at our WSS URL; status callback URL with its token; tunnel hostname; testers' agreement to be called.

## 12. Exit

[Phase exit report](README.md#phase-exit-report) plus the go/no-go decision, recorded with the user.

## 13. As built (2026-11-19)

Deviations from the plan above, each found on a real call or a deliberate simplification:

| Plan | As built | Why |
|---|---|---|
| Status callbacks for `answered` and `terminal` (`StatusCallbackEvents`) | Default callback only; "answered" comes from the stream's `start` | Exotel's connect-to-flow rejects `StatusCallbackEvents` (HTTP 400) |
| Callback content type JSON | Form-encoded (default); JSON still parsed | Default callback; fewer parameters |
| Callback URL `/api/v1/webhooks/exotel/status/{token}` | `/cb/{token}` (the old path still works) with a hex token | Shorter URL while narrowing down the 400; kept |
| Per-attempt stream token in custom parameters | One secret path token in the flow's static Voicebot URL; the attempt is matched by `start.call_sid`, then by CustomField (which arrives as a `custom_parameters` key) | The Voicebot URL is fixed in the flow; a per-call dynamic URL is undocumented for Voicebot |
| `end_reason=invalid_number` for unassigned numbers | On the trial, unverified numbers → HTTP 403 KYC → `provider_failed` | Can only be observed after KYC (Phase 10) |
| Reject → `busy` | Exotel reports a reject as `no-answer` | Provider behaviour |
| Duration from the callback | Our own start/end times when the callback has none | The default callback has no duration |
| Dev worker reload with `arq --watch` | `watchfiles` restarts the whole process | `arq --watch` re-creates the worker in the same process, so edited modules weren't re-imported |
| Echo test measures round-trip latency | Tester confirmed the echo; Exotel's mark round trip measured (0.47 s) | The phone side has no timestamp we can read |
| Voice-provider health in eligibility | Not enforced yet | Phase 6, as planned |

Extra, not in the plan: the stream capture (`TELEPHONY_CAPTURE_DIR`: inbound WAV + sanitized message log), `make tunnel`, `make exotel-urls`, `scripts/exotel_urls.py`, and a `now` argument on the reconciler for tests.

### Acceptance criteria

| ID | Result | Evidence |
|---|---|---|
| P5-AC1 | ✅ | `make test-call` → phone rang; attempt f84b72af has `provider_call_id` |
| P5-AC2 | ✅ | `in_progress` 12 s after queueing, from the stream's start (the provider event for "answered") |
| P5-AC3 | ✅ | 15 997 inbound bytes/s = 8 kHz × 16-bit, as documented; inbound WAV shows speech at the times the tester spoke, and the echo of those same bytes was heard |
| P5-AC4 | ✅ | 192 outbound frames, clip and counting, no protocol errors |
| P5-AC5 | ✅ | Tester: clip clear 4/5, echo heard, the count stopped at "three" after `clear` |
| P5-AC6 | ✅ | Backend hangup → phone dropped within 2 s (tester), `agent_completed`; tester hangup → `candidate_hangup`; tasks 3 → 3 both times; no slot keys left |
| P5-AC7 | ✅ | Four sequential calls, each callback on its own attempt; real callback replayed → `duplicate`, late out-of-order → `ignored` |
| P5-AC8 | ✅ | docs/telephony.md: verified protocol, test-call log, go/no-go recommendation |
