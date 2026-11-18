# Telephony (Exotel)

Status: **enablement in progress**. Verified protocol details are filled in during [Phase 5](phases/phase-05-telephony-poc.md). Nothing below is to be coded against until marked verified.

## 1. Enablement tracker (started in Phase 0)

The whole voice pipeline depends on question 2. If the answer is "no" or "not on your plan", stop and decide the telephony approach before Phase 5 (plan.md Module E).

| # | Question for Exotel | Answer | Date | Ticket / contact |
|---|---|---|---|---|
| 1 | Account activation and KYC status; ExoPhone (virtual number) for outbound caller ID | Account active on a **free trial** (500 credits) with a trial number. **KYC not completed → outbound calls only to verified numbers.** Fine for Phases 5–6 (testers' numbers get verified); KYC must be done before calling real candidates (Phase 10). The existing custom app "makanmantraa1 Landing Flow" belongs to another project; leave it untouched | 2026-11-18 | Dashboard; Exotel expert (call) |
| 2 | Does our account/plan support **bidirectional real-time audio streaming** on outbound calls (Voicebot/stream applet)? | **Yes.** Voicebot and Stream applets are in the flow builder. Exotel's expert confirmed **Voicebot works on the trial plan** (part of their AI voice campaign offering). Still to be verified on a real call in Phase 5 | 2026-11-18 | Flow builder; Exotel expert (call) |
| 3 | Stream audio format: encoding, sample rate, channels, chunk-size rules | Docs: 16-bit linear PCM, mono, little-endian, base64. Sample rate 8000 (default), 16000 or 24000 via `?sample-rate=` on the URL. Chunks: multiple of 320 bytes, min 3.2 KB, max 100 KB (see §2) | 2026-11-18 | [Developer docs][dev] |
| 4 | Can we send audio back on the stream? Are playback-control messages (clear / mark) supported? | Docs: yes. Voicebot is bidirectional; the bot can send `media`, `mark` and `clear` | 2026-11-18 | [Developer docs][dev] |
| 5 | How do we attach our own id (call attempt id) so it comes back in webhooks and the stream start message? | Stream: custom URL query params arrive in `start.custom_parameters`. Docs say max 3 params / 256 chars; the flow editor says 25 params / 800 chars. We need 2 (attempt id + token). Webhook side still open | 2026-11-18 | [Developer docs][dev], flow editor |
| 6 | Status callback payload and the full list of call statuses | | | |
| 7 | Concurrent-call limit on the account; per-minute cost | | | |
| 8 | DND/NCPR scrubbing and calling-hour rules for recruitment calls | | | |
| 9 | Webhook authentication options or source IP ranges | Stream connection: IP whitelisting (via hello@exotel.com) or Basic Auth `Authorization: Basic base64(API_KEY:API_TOKEN)`. Status-callback webhooks still open | 2026-11-18 | [Developer docs][dev] |
| 10 | Call recording availability and how recording URLs are accessed | | | |

## 2. Documented protocol (read 2026-11-18, not yet verified on a call)

Sources: [Developer docs: Stream & Voicebot applet][dev] · [Support FAQ: Voice bot][faq] · [Sample code: exotel/voice-streaming](https://github.com/exotel/voice-streaming) (2021) · reference bots: `github.com/exotel/Agent-Stream`, `github.com/exotel/Agent-Stream-echobot`.

Phase 5 confirms each item on a real call and marks it ✅.

### Connection
- Exotel is the WebSocket **client**; our backend hosts the `wss://` endpoint.
- Voicebot URL is either a fixed `ws(s)://` URL, or an `http(s)://` URL that returns a `ws(s)://` URL per call (dynamic). The docs give no request or response format for Voicebot's dynamic URL; the Stream applet's returns `{"url": "wss://…"}`. **[Verify]**
- Custom parameters: query string on the WS URL → `start.custom_parameters`.
- Authentication of Exotel's connection to us: IP whitelisting or Basic Auth with our Exotel API key/token.
- When the Voicebot step ends, the stream auto-closes, Exotel sends `stop`, and the flow continues to the next applet.

### Audio
| Property | Value |
|---|---|
| Encoding | raw/slin: 16-bit linear PCM, little-endian, mono, base64 in JSON |
| Sample rate | 8000 (default), 16000, 24000; chosen with `?sample-rate=16000` on the URL |
| Outgoing chunk size | multiple of 320 bytes; min 3.2 KB; max 100 KB. Smaller → distortion, larger → timeouts, wrong size → gaps |

Note: 3.2 KB is 100 ms at 16 kHz but 200 ms at 8 kHz. Which minimum applies at each rate is **[Verify]**.

### Messages from Exotel
```json
{"event": "connected"}
{"event": "start", "sequence_number": 1, "stream_sid": "…",
 "start": {"stream_sid": "…", "call_sid": "…", "account_sid": "…", "from": "+91…", "to": "+91…",
           "custom_parameters": {"key1": "value1"},
           "media_format": {"encoding": "raw", "sample_rate": "8000", "bit_rate": "128"}}}
{"event": "media", "sequence_number": 3, "stream_sid": "…",
 "media": {"chunk": 2, "timestamp": "10", "payload": "<base64>"}}
{"event": "dtmf", "sequence_number": 1, "stream_sid": "…", "dtmf": {"duration": "200", "digit": "5"}}
{"event": "mark", "sequence_number": 15, "stream_sid": "…", "mark": {"name": "<label>"}}
{"event": "stop", "sequence_number": 10, "stream_sid": "…",
 "stop": {"call_sid": "…", "account_sid": "…", "reason": "stopped | callended"}}
```

### Messages we send
```json
{"event": "media", "stream_sid": "…", "media": {"payload": "<base64>"}}
{"event": "mark",  "stream_sid": "…", "mark": {"name": "reply-12"}}
{"event": "clear", "stream_sid": "…"}
```
- `mark`: Exotel echoes it back when the audio sent before it has finished playing → playback-finished signal for turn-taking.
- `clear`: drops queued audio that hasn't started playing → barge-in. Docs advise smaller chunks so `clear` is responsive.

### Implications for our design
- **24 kHz matches Kitten TTS's likely native rate** (P3 to confirm), so outgoing audio might need no resampling. Whether a phone call (PSTN, normally narrowband) gains anything above 8 kHz is to be measured in Phase 5 by listening and STT accuracy.
- Barge-in in Phase 6 can use `clear`, with outgoing chunks near the 100 ms minimum.
- `start.media_format.sample_rate` lets the backend check the actual rate at runtime (P5-T9).
- Attempt id + per-attempt token go in custom parameters; `call_sid` links to the Exotel call.

[dev]: https://developer.exotel.com/docs/agentstream/stream-voicebot-applet
[faq]: https://support.exotel.com/support/solutions/articles/3000112112-voice-bot

## 3. Test-call log (Phase 5)

| Date | Attempt id | Case | Expected | Actual | Notes |
|---|---|---|---|---|---|

## 4. Go / no-go (Phase 5)

_Pending._
