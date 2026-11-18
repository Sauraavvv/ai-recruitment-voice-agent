# Telephony (Exotel)

Status: **verified on real calls (Phase 5, 2026-11-19)**. Facts marked ✅ were seen on a real call; anything else is from Exotel's docs and is marked as such.

## 1. Enablement tracker (started in Phase 0)

| # | Question for Exotel | Answer | Date | Source |
|---|---|---|---|---|
| 1 | Account activation and KYC status; ExoPhone (virtual number) for outbound caller ID | **Free trial** (500 credits), **KYC not completed**. ✅ Any number that isn't verified in the dashboard is refused before dialing with HTTP 403 "Your account is not yet KYC compliant". KYC must be done before calling real candidates (Phase 10). The account SID `makanmantraa1` is only a name chosen at sign-up; no other project uses this account (user, 2026-11-19). ✅ ExoPhone (caller ID) **01143078442** (`IncomingPhoneNumbers` API). Our flow: app id **1390568** | 2026-11-19 | Dashboard, API, real calls |
| 2 | Bidirectional real-time audio streaming on outbound calls? | ✅ **Yes**, Voicebot applet on the trial plan, both directions, on real calls | 2026-11-19 | Real calls (§3) |
| 3 | Stream audio format | ✅ 16-bit linear PCM, mono, 8000 Hz, base64 in JSON. Inbound: **320-byte chunks (20 ms)**, 16 000 bytes/s. The start message announces `encoding: "base64"`, `sample_rate: "8000"`, `bit_rate: "128kbps"`. Outbound 3 200-byte chunks (200 ms) played cleanly | 2026-11-19 | Real calls |
| 4 | Send audio back; `mark` / `clear`? | ✅ Media back works. ✅ `mark` is echoed back about 0.47 s after the audio before it finished at our end. ✅ `clear` stops queued audio: the count stopped at "three" as planned, and the mark queued behind the cleared audio never came back | 2026-11-19 | Real calls |
| 5 | Attaching our attempt id | ✅ `CustomField=<value>` arrives in the stream as a **key** of `start.custom_parameters` with an empty value (`{"<value>": ""}`), not in webhooks (the default callback has no CustomField). We match by `CallSid` first | 2026-11-19 | Real calls |
| 6 | Status callback payload and statuses | ✅ The default callback is **form-encoded** with only `Status`, `CallSid`, `DateUpdated` (no duration, no RecordingUrl without recording). Seen: `completed`, `no-answer`. **A rejected call is `no-answer`, not `busy`.** Docs: Exotel retries up to 2 times without HTTP 200 | 2026-11-19 | Real calls, [docs][cb] |
| 7 | Concurrent-call limit; per-minute cost | Open, ask Exotel before Phase 10 | | |
| 8 | DND/NCPR and calling-hour rules for recruitment calls | Open, ask Exotel before Phase 10. `CallType=trans` is sent on every call; whether it applies to our use is for Exotel to confirm | | |
| 9 | Webhook authentication | No signature in the docs. We use a secret path token; wrong token → 403. Voicebot stream: secret path token (Exotel also offers IP whitelisting or Basic Auth) | 2026-11-19 | |
| 10 | Call recording | Not used in the PoC. Docs: `Record=true` on the call, `RecordingUrl` in the callback | | [docs][flow] |

## 2. Stream protocol (Voicebot applet)

Sources: [Developer docs: Stream & Voicebot applet][dev] · [Support FAQ: Voice bot][faq] · real captures in `backend/app/tests/fixtures/exotel/captured_*.json`.

### Connection
- ✅ Exotel is the WebSocket **client**; it connects to the fixed `wss://` URL set in the flow's Voicebot applet, through the tunnel, within about 10 s of the call being placed (when the person answers).
- ✅ When the Voicebot step ends (we close the socket), the flow continues to its **Hangup** applet; the phone disconnected within 2 s (tester).
- ✅ When the person hangs up, Exotel sends `stop` with `reason: "canceled or call ended"` and closes.
- Docs only: a dynamic URL (an `http(s)` endpoint returning `wss://…` per call) and Basic Auth/IP whitelisting for the connection. Not used.

### Messages from Exotel (✅ real shapes; all numbers inside are **strings**)
```json
{"event": "connected"}
{"event": "start", "sequence_number": "1", "stream_sid": "…",
 "start": {"stream_sid": "…", "call_sid": "…", "leg_sid": "…", "account_sid": "…",
           "from": "0XXXXXXXXXX", "to": "0XXXXXXXXXX",
           "custom_parameters": {"<CustomField value>": ""},
           "media_format": {"encoding": "base64", "sample_rate": "8000", "bit_rate": "128kbps"}}}
{"event": "media", "sequence_number": "2", "stream_sid": "…",
 "media": {"chunk": "1", "timestamp": "20", "payload": "<base64 of 320 bytes>"}}
{"event": "mark", "stream_sid": "…", "mark": {"name": "<label>"}}
{"event": "stop", "sequence_number": "893", "stream_sid": "…",
 "stop": {"call_sid": "…", "leg_sid": "…", "account_sid": "…", "reason": "canceled or call ended"}}
```
- `from`/`to` are 11-digit national numbers (`0…`), not E.164.
- The echoed `mark` has no `sequence_number`. A few `sequence_number` gaps occur (2 in a 55 s call).
- `dtmf` is documented but wasn't exercised.

### Messages we send (✅ all accepted)
```json
{"event": "media", "stream_sid": "…", "media": {"payload": "<base64 of 3200 bytes>"}}
{"event": "mark",  "stream_sid": "…", "mark": {"name": "intro"}}
{"event": "clear", "stream_sid": "…"}
```

### Settings (P5-T9)
`TELEPHONY_ENCODING=slin`, `TELEPHONY_SAMPLE_RATE=8000`, `TELEPHONY_FRAME_BYTES=3200`. The backend compares them with the start message's `media_format` and refuses the stream on a mismatch (`encoding: "base64"` counts as slin).

Not measured yet (Phase 6): smaller outgoing chunks (the docs' minimum is 3.2 KB) and 16 kHz.

[dev]: https://developer.exotel.com/docs/agentstream/stream-voicebot-applet
[faq]: https://support.exotel.com/support/solutions/articles/3000112112-voice-bot

## 2a. Call control (REST v1)

Sources: [Connect number to call flow][flow] · [Status callback][cb] · [Call details][details] · [Webhook setup][wh].

| What | How we use it |
|---|---|
| Place a call | ✅ `POST https://api.exotel.com/v1/Accounts/{sid}/Calls/connect.json`, HTTP Basic (API key : token). Form: `From`=candidate (E.164 accepted; rung first), `CallerId`=ExoPhone, `Url=http://my.exotel.com/{sid}/exoml/start_voice/{app_id}`, `CallType=trans`, `TimeLimit`, `TimeOut`, `CustomField`=attempt id without hyphens, `StatusCallback` |
| ❌ Not accepted | ✅ `StatusCallbackEvents[…]` (any value) → HTTP 400 "Invalid 'StatusCallbackEvents' specified" on connect-to-flow. So there is no `answered` callback: "answered" comes from the stream's `start` |
| Response | ✅ `{"Call": {"Sid": "…", "Status": "in-progress", …}}` immediately, even while ringing. `Sid` → `provider_call_id` |
| Ring timeout | ✅ `TimeOut=30` → `no-answer` after about 31 s |
| Status callback | ✅ Form-encoded `Status`, `CallSid`, `DateUpdated`, about 3 s after the call ends. Duration is taken from our own start/end times |
| Timestamps | ✅ `YYYY-MM-DD HH:mm:ss` in **IST** |
| Call details | `GET …/Calls/{CallSid}.json?details=true` (reconciler); `GET …/Calls.json?From=…&DateCreated=gte:…` after an initiate timeout. ✅ The list endpoint works |
| Ending a call from our side | ✅ Close the Voicebot WebSocket → Hangup applet → phone disconnects within 2 s. No REST hangup needed |
| Errors | ✅ 401 bad credentials; ✅ 403 unverified number on a KYC-less trial (refused, no call placed); ✅ 400 invalid parameters |

### Our flow in Exotel (App Bazaar)

1. A flow with exactly two applets: **Voicebot** → **Hangup**. Ours is app id 1390568.
2. Voicebot URL: the value printed by `make exotel-urls` (`wss://<tunnel>/api/v1/webhooks/exotel/stream/<token>`). **It changes whenever the quick-tunnel URL changes**; update the applet then.
3. The status callback URL (`https://<tunnel>/cb/<token>`) is sent with each call; nothing to configure.

[flow]: https://developer.exotel.com/docs/voice-v1/api-reference/connect-to-flow
[cb]: https://developer.exotel.com/docs/voice-v1/api-reference/status-callback
[details]: https://developer.exotel.com/docs/voice-v1/api-reference/call-details
[wh]: https://developer.exotel.com/docs/advanced-config/webhooks-setup

## 3. Test-call log (Phase 5)

All calls went to the tester's own verified phone (the only tester). Attempt ids are the first 8 characters.

| Date (IST) | Attempt | Case | Expected | Actual | Notes |
|---|---|---|---|---|---|
| 2026-11-19 00:20–00:31 | #1–9 | First tries | Call placed | ❌ HTTP 400 "Invalid 'StatusCallbackEvents' specified", no call placed | Cause: `StatusCallbackEvents` isn't accepted on connect-to-flow. The dev worker didn't reload code (`arq --watch` keeps modules), so later fixes weren't running; fixed by restarting the whole process (`watchfiles`). Meanwhile 7 untracked diagnostic calls reached the tester (direct API requests while narrowing down the error) |
| 2026-11-19 00:24 | (untracked) | First stream | Voicebot connects | ✅ Exotel connected to our WSS through the tunnel; start message logged | `encoding: "base64"` → our format check rejected it; fixed |
| 2026-11-19 00:32 | f84b72af (#10) | **Full**: clip, echo, mark, clear, backend hangup | Clip heard; echo after 1 s; count stops at about "three"; phone drops within 2 s of goodbye | ✅ Tester: clip clear **4/5**, echo heard, count stopped at "three", call dropped within 2 s. Backend: `in_progress` at 12 s from stream start; 2 744 inbound chunks × 320 B, 15 997 B/s; 192 outbound frames, no protocol errors; marks back after 0.47 s; mark after `clear` not returned; `completed` / `agent_completed`; tasks 3 → 3; slot released | Duration 57 s (from our timestamps) |
| 2026-11-19 00:36 | b43681f7 (#11) | Tester hangs up | `completed`, candidate_hangup, cleanup | ✅ `stop` reason "canceled or call ended" → `completed` / `candidate_hangup`, 20 s, tasks 3 → 3, slot released | |
| 2026-11-19 00:37 | (#12) | Tester rejects | busy (or provider equivalent) | ✅ Exotel reports **`no-answer`** → `no_answer` / `no_answer`; stream never opened | Exotel doesn't distinguish reject from no answer |
| 2026-11-19 00:38 | (#13) | Ring out | no_answer | ✅ `no-answer` after about 31 s (`TimeOut=30`) → `no_answer` | |
| 2026-11-19 00:40 | (new) | Unverified / invalid number | failed, invalid_number | ✅ Refused before dialing: HTTP 403 "not yet KYC compliant" → `failed` / `provider_failed` | On the trial every unverified number gets this, so a true invalid-number response can only be seen after KYC (Phase 10). Tested with the ExoPhone's own number: nobody rung |
| — | — | Phone switched off / unreachable | failed or no_answer | Not tested (needs a second phone) | Phase 10 |
| 2026-11-19 00:41 | f84b72af | Same webhook twice; late out-of-order webhook | One state change | ✅ Real terminal callback replayed through the tunnel → `duplicate`; an older `in-progress` → `ignored`; attempt stays `completed` | |
| 2026-11-19 | #10–13 | Sequential calls | Each event on its own attempt | ✅ Four calls, each callback and stream on its own attempt; nothing left in `initiating`/`in_progress`; no slot keys left | |

| 2026-11-19 00:52 | 0a735253 (#14) | **Live screening** (`mode=screen`, preview of Phase 6): AI asks the job's questions, answers stored | All 10 fields asked, answers stored, agent hangs up | ✅ 168 s call, 22 agent turns, all 10 fields stored on the candidate, `screening_status=completed`, `conversations` row with transcript and summary, `agent_completed`. ❌ From mid-call on, the tester's answers were processed one question late, and some twice: what the tester said during the agent's ~2 s thinking pause was queued and taken as the answer to the next question | Fixed for the preview: utterances that finish while the agent is busy are dropped (`VoiceLoop(drop_stale=True)`). The summary said "He"; summaries now never use gendered pronouns. Phase 6 needs acknowledgement masking and barge-in |
| 2026-11-19 00:59 | dad54a4a (#15) | **Live screening, re-test** with the fix | Each answer on its own question | ✅ 179 s, 13 candidate turns, every answer matched its question, nothing dropped or repeated, all 10 fields stored, read-back confirmed, agent hung up. End of speech → agent's voice ≈ 4 s (STT p50 0.96 s + agent p50 2.0 s + TTS first audio p50 1.0 s) | Notice "30 days, buy-out to 15" stored as "30 days" (the buy-out is only in the raw words); CTC fixed/variable split only in the raw words; the summary said "is an AI Engineer" (it's the role applied for). 0.3 s of inbound audio dropped once (queue overflow) |

Captures: `backend/artifacts/calls/<attempt>_in.wav` and `_stream.json` (gitignored, delete after review); sanitized fixtures in `backend/app/tests/fixtures/exotel/`.

## 4. Go / no-go (Phase 5)

**Recommendation: Go.** Exotel's Voicebot carries live audio both ways on this trial account; calls are placed, tracked, ended from either side, and every outcome lands on the right attempt. P5-AC1 to AC8 pass (phase-05 §13).

Open items, none blocking Phase 6:
- KYC before calling anyone who isn't verified (Phase 10).
- Ask Exotel: concurrency limit, per-minute cost, DND rules and whether `CallType=trans` is right for recruitment calls.
- The quick tunnel's URL changes on restart; a stable host is needed before wider testing (Phase 10, or a named tunnel).
- No `answered` callback (stream `start` is the answered signal); no duration in the callback (taken from our timestamps, or Call Details after about 2 minutes).
