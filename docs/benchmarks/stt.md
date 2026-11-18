# STT benchmark: Deepgram streaming (Phase 4)

Measured 2026-11-18 from the developer Mac in India (Deepgram's servers are in the US, about 280 ms round trip). Tool: `make bench-stt` (`backend/app/scripts/bench_stt.py`). Raw results: `backend/artifacts/stt-bench/*.json` (not committed).

## Chosen settings

| Setting | Value | Why |
|---|---|---|
| Model / language | `nova-3`, `en-IN` | Accuracy equal to `en`, ahead of `nova-2`. `nova-2` also looped a word dozens of times on 2 clips ("Infosys Infosys Infosys…"). Same price as `en`. |
| Sample rate | 8 kHz linear16 (telephony) | 16 kHz gave no gain on this set; calls are narrowband anyway |
| `endpointing` | 300 ms | Fastest of 300/500/800, with no accuracy cost. All three split the long-pause clips equally |
| `utterance_end_ms` | 1000 | Backstop when no `speech_final` comes |
| `smart_format` | **off** | With it on, Deepgram holds back answers that end in a number (e.g. "…fifteen point five") for up to 4.5 s, waiting to see if the number continues. Off: +2.6 points accuracy, −170 ms p50. Numbers arrive as words ("twelve lakhs"); the agent handles them |
| Keyterms | `CTC, LPA, lakhs, notice period` + per-call terms (company names) | `keyterm` on Nova-3 |

Settings: `DEEPGRAM_STT_*` in `.env.example`.

## Test set

- 20 lines in `backend/app/tests/fixtures/stt_clips.yaml`: screening answers with numbers, companies and cities, several answers in one sentence, two answers with a long pause mid-answer (1.3 s and 1.6 s), a filler ("Hmm.") and silence. Each line lists its key entities.
- **Synthetic speech, not people.** Spoken by the three macOS Indian-English voices (Rishi, Tara, Aman) at 16 kHz, plus 6 background-noise variants per voice: fan (pink noise, 12 dB SNR), traffic (10 dB) and TV (another voice talking, 8 dB). 78 clips in total. Sent at 8 kHz through a μ-law round trip, like a phone call.
- macOS `say` is flaky: the same line sometimes renders truncated or as seconds of garbage. The generator renders until two renders match. The first two benchmark runs used some broken renders and were discarded.
- After each answer: 2.5 s of a −60 dBFS noise floor, as on a real phone line. With digital silence instead (all zeros), Deepgram's endpointing fires sooner (p50 about 1.0 s instead of 1.8 s), which overstates its speed.
- **Real recordings still to do** (plan P4-T8: 3+ consenting speakers): `make stt-record SPEAKER=name`, then `make bench-stt args='--sets real'`. Synthetic voices are cleaner and more regular than people, so treat these accuracy numbers as optimistic and the false-endpoint numbers as untested for hesitant speech.

## Results (78 clips per configuration, realistic tail)

Latency = from the end of the last word to the utterance being complete (what the agent waits for).

| Config | Key entities | Clips fully right | Latency p50 / p95 | Pause splits (of 6) | Other splits | Missed |
|---|---|---|---|---|---|---|
| nova-3 en-IN 8k, endpointing 300 | 88.2% | 58/72 | 1794 / 3107 ms | 6 | 0 | 0 |
| nova-3 en-IN 8k, endpointing 500 | 88.2% | 57/72 | 2022 / 3153 ms | 6 | 0 | 1 |
| nova-3 en-IN 8k, endpointing 800 | 88.2% | 58/72 | 2255 / 3146 ms | 6 | 0 | 0 |
| nova-3 en 8k, 500 | 87.6% | 57/72 | 2062 / 3082 ms | 6 | 0 | 0 |
| nova-2 en-IN 8k, 500 | 87.6% | 58/72 | 1979 / 2913 ms | 6 | 0 | 2 |
| nova-3 en-IN **16k**, 500 | 87.6% | 57/72 | 1982 / 3110 ms | 6 | 0 | 1 |
| **nova-3 en-IN 8k, 300, smart_format off (chosen)** | **90.8%** | **59/72** | **1620 / 2577 ms** | 6 | 0 | 0 |
| nova-3 en-IN 8k, 300 + `Finalize` 400 ms after speech | 88.9% | 58/72 | **851 / 1346 ms** | 6 | 0 | 0 |
| Flux (`flux-general-en`, `/v2/listen`) | 84.6%* | – | 1144 / 2091 ms* | 6 | 0 | 7* |

\* Flux: over the 65 sessions that connected. In the final run Deepgram refused 46 of 78 Flux connections with HTTP 503 ("Service Unavailable, please try again later"), and still about 1 in 5 when connecting one at a time. No Nova connection failed in the same runs.

By voice (chosen config): Rishi 94%, Tara 90%, Aman 88%. Clean clips (no added noise): 95%. Silence and filler clips: no utterances in any configuration.

### Errors that remain (chosen config)

- **"four PM" → "four AM"**: 4 of 6 callback clips, every run (Tara and Aman). A callback time must be confirmed back to the candidate ("tomorrow at 4 PM, is that right?").
- **Cities:** Noida → "Moida", Gurgaon → "Google" / "Gugao" / dropped. Add the job's city and common NCR names as per-call keyterms; the read-back confirmation catches the rest.
- **TV babble at 8 dB SNR**: the background voice gets transcribed into the answer ("In tonight's last five…"). Expect clarification requests on noisy calls.
- Earlier runs with broken renders also produced "fifteen point" (with "five" missing); that was the audio, not Deepgram.

## Latency: Deepgram's endpointing vs a local end-of-speech detector

Deepgram's own end-of-speech decision is the slow part. Its p50 is about 1.6–2.3 s from the last word on a realistic line, and it varies with the line noise and with how the answer ends. Sending `Finalize` 400 ms after speech stops (what a local VAD would do) brings the final in at **p50 851 ms, p95 1346 ms**, consistently, whatever the answer ends with. The bench uses the clean clip to know where speech ends, so this is the best case for a VAD; a real VAD on noisy lines will be somewhat worse.

**Recommendation for Phase 6** (added to its plan, §5.3): drive end of turn with the local VAD it needs for barge-in anyway (Silero or webrtcvad), call `finalize()` after about 400 ms of silence, and keep Deepgram's endpointing as the backstop. With the agent's ~2.3 s, that puts the wait from end of speech to reply at about 3.1 s, which the acknowledgement clip masks.

Measured separately: connecting a stream takes about 0.8–1.5 s from India, so Phase 6 should open the STT stream while the call is ringing, not when it's answered.

## Long pauses and false endpoints

Every Nova configuration (even 800 ms) split both mid-answer pauses (1.3 s and 1.6 s): "My current CTC is…" | "I think it is nine point two lakhs." Endpointing can't hold a pause that long without making every turn slow, so Phase 6 must merge an utterance that follows within about 1 s before the agent replies. No configuration split an answer without a pause. In one live loop run, 300 ms split "Yes, | sure, I have a few minutes" at the comma. Real recordings will show how often hesitant speech splits.

## Live end-to-end (P4-AC2)

`make voice-loop SCRIPT=s14_happy_path RATE=8000` (scenario lines spoken by `say`, real Deepgram and OpenAI). Rishi, endpointing 500, smart_format on: 12 utterances → 12 replies, completed, all 10 fields right, STT latency median 1083 ms. Tara, chosen settings: completed, all fields right, median 857 ms. The first line came out garbled at confidence 0.53 (a broken `say` render) and the agent asked again, as designed.

## Cost

Nova-3 English streaming: $0.0048 per minute of audio sent (Deepgram pay-as-you-go, 2026-11-18), about $0.03 for a 5-minute call. The stream is billed while it's open, so it's closed as soon as the call ends. Flux: $0.0065/min. Each full benchmark run costs about $0.50.
