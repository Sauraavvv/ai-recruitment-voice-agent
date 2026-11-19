# Phase 6 real-call test programme

Plan: [phase-06 §7.2](../phases/phase-06-voice-conversation.md#72-real-calls). Pipeline: [voice-pipeline.md](../voice-pipeline.md).

## How to run a test call

1. The tester agrees to be called, and their number is **verified in the Exotel dashboard** (the trial account can't call anyone else).
2. `make tunnel`. If its URL changed: update `PUBLIC_BACKEND_URL` in `.env`, run `docker compose up -d backend worker`, and paste the new `make exotel-urls` Voicebot URL into the flow (app 1390568).
3. `make test-call phone=+91XXXXXXXXXX name="Tester Name"`. You can also press **Call now** on the candidate's page.
4. The tester follows one card below. Afterwards the script prints the transcript, the stored fields, `end_reason`, the per-turn latency table and the summary. Copy the numbers into the log at the end of this file.
5. Captured audio (`backend/artifacts/calls/<attempt>_in.wav`) is the tester's voice: delete it after review.

The active job is **AI Engineer at MakanMantraa (Remote)**, with the 10 default questions: location, company, total and relevant experience, current and expected CTC, notice period, reason for change, interest, interview availability.

## Scenario cards

Each card gives the persona's answers. Answer naturally; the wording doesn't have to match. **Expected** is what should be stored or happen.

| # | Card | Behaviour to perform | Expected |
|---|---|---|---|
| 1 | Happy path, clear speech | Answer every question plainly: Pune; Infosys; 6 years; 4 relevant; 12 lakhs; 18 lakhs; 60 days; career growth; yes, interested; weekdays after 5 PM. Confirm the read-back. | All 10 fields; `screening_status=completed`; `end_reason=agent_completed` |
| 2 | Two answers in one sentence | "I'm in Bangalore, working at Wipro." Later: "Six years total, about four in AI." | Location **and** company from one answer; company not asked again; both experiences from one answer |
| 3 | Refuses salary | "I'd rather not share my current CTC." Answer everything else. | `current_ctc` declined (not asked again); the rest stored |
| 4 | Busy, callback | At "is this a good time?": "I'm busy, call me tomorrow at 5 PM." | Read-back of the callback time (PM, not AM); `end_reason=callback_scheduled`; `screening_status=callback_requested` |
| 5 | Not interested | After the introduction: "No, I'm not interested in a new job." | Polite close; `end_reason=declined` |
| 6 | Don't call again | Anywhere: "Please don't call me again." | Apology, close; `end_reason=opted_out`; candidate `opted_out=true` |
| 7 | Interrupts | While the agent is asking a long question (e.g. the introduction), start talking ("Sorry, who is calling?") and keep going for about 2 seconds. | The agent stops within about 0.5 s; the next reply makes sense; the transcript marks the agent's line `interrupted` |
| 8 | Long pauses | Before 3 answers, pause 3-5 s ("hmm…"). Once, say half an answer, pause about 1.5 s, and finish it ("I have… six years"). | No re-prompt before 7 s; the split answer is merged into one turn (`merged` in the latency table) |
| 9 | Noisy background | Call from a street, with a fan on, or with the TV on. Happy-path answers. | Fields still correct; no false interruptions while the agent speaks |
| 10 | Fast speech, short answers | Answer as briefly as possible: "Pune." "TCS." "Five." "Ten." "Fifteen." "Thirty days." | Values right (units inferred: years, lakhs, days) |
| 11 | Corrects an earlier answer | Say "eight lakhs" for current CTC, then two questions later: "Sorry, my current CTC is actually nine lakhs." | `current_ctc=9`, with a correction in its history |
| 12 | Hangs up halfway | Answer the first 4 or 5 questions, then hang up mid-question. | `end_reason=candidate_hangup`; transcript and answers up to the hang-up are stored; `screening_status=partially_completed` |

Silence check (any tester, once): after the greeting, say nothing. Expected: the question again after 7 s, then "Are you still there?", then the close; `end_reason=silence_timeout`.

## Acceptance evidence

| AC | Evidence |
|---|---|
| P6-AC1 | ≥ 3 complete calls by different testers (card 1 or 9) |
| P6-AC2 | Every required field asked once or answered unprompted (transcripts) |
| P6-AC3 | Captured vs card values: ≥ 90% field accuracy over the programme |
| P6-AC4 | Cards 2, 3, 8, 10, 11 pass |
| P6-AC5 | Card 7: `stop_latency_ms` in the `barge_in` log ≤ 500 ms (plus Exotel's own delay, heard by the tester) |
| P6-AC6 | Isolation tests pass (automated); two simultaneous real calls only if the account allows 2 lines |
| P6-AC7 | Card 12: transcript and answers in the database |
| P6-AC8 | Latency table below: t0 → first sound and t0 → reply p50/p95 |

## Call log

| Date | Attempt | Card | Tester | Network | Fields expected/captured | First sound p50 | Reply p50 / p95 | Interruptions | Result | Issues |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-19 | bee063ea | free answers (≈1, ends as 5) | Saurav | mobile | 9 asked, 9 stored as said; "interested: No" → declined (correct) | 842 ms | 3 570 / 6 102 ms | **2 false barge-ins**: "Hello?" said into a 2-3 s thinking pause cut the next reply at its first word; then 17 s of dead air (no silence timer after a barge-in) | declined, agent hung up, tasks 3→3 | Fixed: barge-in needs speech that starts after the reply is audible; silence timer after barge-in; "One moment." after 2.5 s; held bare "Hello?" never an answer; intro/role line pre-synthesized (turn 1 was 6.1 s); role line "an AI Engineer …, fully remote" |
| 2026-11-19 | a3e4077b | free answers, pauses | Saurav | mobile | 10/10 stored as said (CTC "one crore" → 100 LPA; notice "one year, buy out for one day" kept verbatim) | 750 ms | 3 982 / 4 276 ms | none: no false cuts, no dead air | callback_scheduled, agent hung up, tasks 3→3 | "One moment." played on 10/12 turns (threshold 2.5 s < usual LLM time) → raised to 3.5 s. "Can you please schedule a call for me?" (= interview) was taken as a callback and skipped the read-back → prompt rule + eval s17 |
| 2026-11-19 | ba86a9d2 | 7 (not reached) | Saurav | mobile | — | — | — | — | technical_failure / stream_never_connected (by the reconciler 3 min later) | The Cloudflare quick tunnel had died ("Tunnel not found", Mac idle ~2.5 h), so Exotel couldn't open the stream and dropped the call. Not a pipeline fault; new tunnel + flow URL. Production needs a stable URL (P10) |
| 2026-11-19 | 16770dfd | 7 attempted + free answers | Saurav | mobile | 10/10 stored as said; read-back confirmed | 979 ms | **3 036** / 4 384 ms | none registered: the captured inbound audio is silent (−70 dBFS) all through the role line; the candidate spoke right after it ended (36.1 s vs its mark at 35.6 s). Inbound audio does flow during playback (one "okay" over a reply was heard and ignored) | **completed**, agent hung up | Read-back spoke the raw notice sentence ("a notice period of Officially, it's…..") → now uses the extracted days. "Delhi" heard as "Deli". Turn 1 LLM 6.1 s and 183 ms loop lag: the call started a minute after a backend restart while Kitten was still loading |
| 2026-11-19 | c45bfda0 | 7 again + free answers (incl. a range) | Saurav | mobile | 10/10 stored as said; range "8 to 9" clarified → 9; read-back "a notice period of 15 days" | 663 ms | 3 114 / 4 722 ms | 1 barge-in, **stop 464 ms** (≤ 500 ✓), but it was the candidate's own continuation over an instant template reply. Interruptions over the introduction never reached us: inbound is a flat −67 dBFS for the whole 12 s of the intro and of the role line, the voice appears only after each playback ended → the handset was muting its microphone while it played (speakerphone/echo suppression) | **completed**, agent hung up | 6 merges in 18 turns (mid-sentence pauses ≥ 400 ms), working as designed. "Total work." (conf < 0.6) got an instant "Sorry, I didn't catch that" over "…four years" → replies now wait for 0.7 s of quiet (max 2.5 s) |
| 2026-11-19 | a231add0 | 7 (script, phone to ear) — **started from the UI (Call now)** | Saurav | mobile, handset | 10/10 stored; 3 STT misses re-asked by the agent ("TCS"→"PCS", stored PCS; "three years"→"Say yes"; "twelve lakhs"→"Garlic") | 627 ms | 3 458 / 6 080 ms | **Intro interrupted: stop 480 ms** (≤ 500 ✓), 37 % heard, agent answered "who is calling" and re-asked permission. Second interruption (softer) never reached us. | **completed**, agent hung up | Inbound sits on a flat −67 dBFS floor and every utterance starts *after* the agent's line ended, except loud talk-over: the handset/network gates the microphone while it plays, and opens late (onsets jump −67→−24 dB in 40 ms, clipping first consonants → the STT misses). Line limit, not the pipeline |
| 2026-11-19 | b952a19a | 2, 3, 11, 12 — **Kitten (Iris) as the main voice**, first live use | Saurav | mobile, handset | card 3 ✓ declined CTC, not re-asked; card 11 ✓ "six years, not four" caught mid-answer and confirmed; card 12 ✓ hang-up → partially_completed, transcript saved to the last question; card 2 ✗ STT lost "Infosys" and **"Working at" was stored as the company** | 717 ms | 3 275 / 3 926 ms (TTS p50 2 ms, p95 445 ms) | none attempted | candidate_hangup | Fixed: a company/location with no name in it is invalid → asked again; a "notice period" with no duration in it is rejected (found in the eval right after). Candidate record keeps older calls' answers where this call had none (current CTC 7 from a previous call, though declined now) → Phase 7 conflict rules |

## Latency (all calls)

Six screening calls on 2026-11-19 (88 agent turns), from `turn_metrics`, in ms. "After fixes" = calls 3-6, once the fixes from calls 1-2 were in (63 turns).

| Segment | Target p50 | p50 all | p95 all | p50 after fixes | p95 after fixes |
|---|---|---|---|---|---|
| t0 → t1 STT (`stt_ms`) | ≤ 600 | 688 | 1 106 | 681 | 1 106 |
| t1 → t2 LLM (`llm_ms`) | ≤ 2 500 | 2 458 | 3 914 | 2 233 | 3 464 |
| t2 → t3 first TTS audio (`tts_ms`) | ≤ 300 | 2 | 1 016 | 1 | 1 008 |
| t0 → acknowledgement (`ack_ms`) | ≤ 1 000 | 714 | 1 130 | 695 | 1 132 |
| t0 → first sound (`first_sound_ms`) | ≤ 1 000 | 732 | 4 019 | **721** | 4 019 |
| t0 → reply (`total_ms`) | ≤ 3 500 | 3 458 | 6 080 | **3 253** | 5 842 |

- STT is ~80 ms over its budget at p50 (VAD 400 ms silence + Deepgram's finalize round trip from India to the US). The acknowledgement still lands under 1 s.
- TTS is ~1 ms whenever the reply matches a warmed phrase (most turns); the p95 is a reply Deepgram had to render fresh (calls 1-5) or Kitten rendered (call 6, p95 445 ms).
- The p95 of first sound and reply are the turns with no acknowledgement (identity turn, merged turns) and slow LLM turns (up to 6 s; "One moment." covers those after 3.5 s).

## Acceptance (2026-11-19)

| AC | Result | Evidence |
|---|---|---|
| P6-AC1 | **Partly**: 4 complete screenings (calls 2-5), all by one tester | The user has no other testers; the trial account can only call numbers verified in Exotel. Calls by other people move to Phase 10 (after KYC) |
| P6-AC2 | ✅ | Every transcript asks each field once, or again only after an unclear answer / for a confirmation |
| P6-AC3 | ✅ 94.5% | 52 of 55 answers stored as the tester said them; the 3 misses are STT losses on the line ("Deli", "PCS", lost "Infosys") |
| P6-AC4 | ✅ with one live miss | Card 3 ✓, 8 ✓ (8 merges over calls 4-6), 10 ✓, 11 ✓ (call 6); card 2 failed live once (STT dropped "Infosys"; now asked again instead of stored), passes in the eval (s02) and the simulated call |
| P6-AC5 | ✅ where the line delivers the audio | Stop 464 ms (call 4) and **480 ms** (call 5, interrupting the introduction). Talking over the agent softly never reaches us on the tester's phone: the handset/network gates the microphone while it plays (flat −67 dBFS inbound). Documented as the line's limit |
| P6-AC6 | ✅ automated; live part not run | Isolation and leak tests pass; two simultaneous real calls need `MAX_CONCURRENT_CALLS=2` and Exotel's OK |
| P6-AC7 | ✅ | Call 6 (card 12): hung up mid-call → `candidate_hangup`, `partially_completed`, transcript and answers up to the hang-up stored |
| P6-AC8 | ✅ | Table above |

Not tested live, by decision (2026-11-19): card 6 ("don't call me again", would block the tester's number; covered by eval s09) and card 9 (noisy background).
