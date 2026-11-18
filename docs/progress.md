# Progress

## Phase 4 exit report (2026-11-18)

**Implemented:** streaming speech-to-text through Deepgram behind `STTProvider`, one stream per call session, and a local loop that feeds finished utterances to the P2 agent.
- `providers/stt/deepgram_provider.py`, a plain `websockets` client (no SDK), with the protocol checked against the live API:
  - Connect: 3 s timeout, 3 attempts with backoff. 401/403/400 → `STTConfigError` at once.
  - Keepalive during silence. `close()` sends `CloseStream` and waits up to 2 s for the last results.
  - Mid-stream drop → reconnect and resume. 2 s of audio is buffered meanwhile (oldest dropped, logged), and timestamps stay continuous.
  - No working stream for over 5 s → `error` event, then `closed`.
  - `finalize()`, `sent_at()` for latency measurement, and per-call keyterms.
- `voice/utterance.py`, `UtteranceAssembler`:
  - Finals accumulate; partials only update the preview.
  - The utterance completes on `speech_final` or `UtteranceEnd`, whichever comes first; the second signal is ignored.
  - Confidence is the minimum across segments. Empty finals are ignored. Fillers are dropped unless a yes/no answer is expected ("mm-hmm" counts as an answer).
  - Speech timing for P6's silence timeouts.
- `voice/local_loop.py`, `VoiceLoop`: STT → assembler → `ConversationManager`, exactly one reply per utterance. Every log line carries `session_id`. Inputs: the microphone, or a scripted scenario spoken by macOS `say` turn by turn. Optional spoken replies (Deepgram Aura).
- Tools:
  - `make stt-file` (stream a WAV like a call; `--dump-events` records fixtures)
  - `make stt-mic`
  - `make voice-loop` (`SCRIPT=`, `SPEAK=1`)
  - `make stt-clips` (synthetic test set)
  - `make stt-record` (real speakers)
  - `make bench-stt`
  - `make test-stt`
- Details and numbers: [benchmarks/stt.md](benchmarks/stt.md); deviations from the plan: [phase-04 §13](phases/phase-04-deepgram-stt.md#13-as-built-2026-11-18).

**Chosen Deepgram settings** (from the benchmark; `DEEPGRAM_STT_*`):

| Setting | Value |
|---|---|
| Model | `nova-3` |
| Language | `en-IN` |
| Audio | 8 kHz linear16 |
| `endpointing` | 300 ms |
| `utterance_end_ms` | 1000 |
| `smart_format` | off |
| Keyterms | `CTC, LPA, lakhs, notice period`, plus per-call terms |

**Benchmark** (78 synthetic clips, 3 Indian-English voices, phone band, realistic line noise after each answer):

| Config | Key entities | Latency p50 / p95 | Pause splits |
|---|---|---|---|
| nova-3 en-IN, 300 ms, smart_format off (**chosen**) | 90.8% | 1620 / 2577 ms | 6/6 |
| same + local `Finalize` 400 ms after speech | 88.9% | **851 / 1346 ms** | 6/6 |
| nova-3 en-IN, 500 / 800 ms | 88.2% | 2022 / 2255 ms p50 | 6/6 |
| nova-2 en-IN | 87.6% | 1979 ms p50 | 6/6 |
| Flux | 84.6% | 1144 / 2091 ms | 6/6 |

Flux: Deepgram refused many connections with HTTP 503.

**Files created / changed:**
- Backend, new:
  - `providers/stt/base.py`, `deepgram_provider.py`, factory in `__init__.py`
  - `voice/utterance.py`, `voice/local_loop.py`
  - `scripts/stt_tools.py`, `stt_file.py`, `stt_mic.py`, `stt_record.py`, `make_stt_clips.py`, `bench_stt.py`
  - tests: `unit/voice/test_utterance.py`, `test_deepgram_stt.py` (against `fake_deepgram.py`, a local fake server), `test_local_loop.py`; `integration/test_deepgram.py` (marker `stt`)
  - fixtures: `fixtures/stt_clips.yaml` (20 lines with key entities), `fixtures/deepgram_events/*.json` (6 recorded, sanitized sequences)
- Backend, changed:
  - `config.py`: `DEEPGRAM_STT_MODEL`, `_LANGUAGE`, `_ENDPOINTING_MS`, `_UTTERANCE_END_MS`, `_SMART_FORMAT`, `_KEYTERMS`
  - `pyproject.toml`: `stt` marker excluded by default; ruff ignores for the tools; mypy ignore for `sounddevice`
  - `requirements-dev.in/.txt`: `sounddevice` 0.5.6 (host microphone tools). An addition only; nothing upgraded. `websockets` 17.4 was already pinned.
- Infra: Makefile adds the P4 targets; `.env.example` gets the STT settings. Audio stays in `backend/artifacts/stt-audio/` (gitignored, plan §10).
- Docs: `benchmarks/stt.md` (new); `setup.md` (STT section, troubleshooting); `phases/phase-04` (§13 As built); `phases/phase-06` (§5.3: VAD + `finalize()` for end of turn, measured numbers).

**Tests run:**
- `make test` → 385 passed, 1 skipped (the P3 Deepgram TTS test without a key on the host), 14 deselected.
- Docker suite → 385 passed. `make lint`, `make typecheck` → clean.
- `make test-stt` (live, Docker) → 7 passed: clips with key entities (94.7% on clean clips), silence with keepalive held over 30 s, socket killed → reconnect, invalid key, two concurrent sessions.
- Live voice loop, `s14_happy_path` at 8 kHz, twice (Rishi; Tara with the final settings).
- `make bench-stt`: 3 full runs plus a Flux re-run. The first 2 runs were discarded because of broken `say` renders and digital-silence tails.

**Acceptance criteria:**
- P4-AC1 ✅ with a caveat. Entity accuracy is recorded (90.8% on the synthetic set, 95% on clean clips) and live transcription works. It hasn't been measured on human speakers yet, and the live microphone demo needs you (`make stt-mic`).
- P4-AC2 ✅ Live loop: 12 utterances → 12 replies, call completed, all 10 fields correct. `test_local_loop.py` checks one reply per utterance, ordering while the agent is busy, and STT errors. The `voice_turn` log lines pair each utterance with its reply.
- P4-AC3 ✅ Silence, disconnect and bad-key tests pass live; flapping-connection, buffer-overflow and stream-loss cases pass against the fake server. Empty finals and fillers are ignored.
- P4-AC4 ✅ Concurrent two-session test passes, live and against the fake server; the assembler rejects events from another session.
- P4-AC5 ✅ End of speech → utterance complete at 8 kHz: p50 1620 ms, p95 2577 ms with the chosen settings; p50 851 ms with local `Finalize`.

**Deferred or not done:**
- **Real recordings (P4-T8):** 3+ consenting speakers with Indian-English accents. The tool is ready: `make stt-record SPEAKER=name`, then `make bench-stt args='--sets real'`. Re-check endpointing (300 ms) against hesitant real speech then.
- Live microphone demo: run `make stt-mic` and `make voice-loop` yourself (it needs a person and headphones).
- End of turn by local VAD + `finalize()`, and merging utterances after a long pause: Phase 6 (written into its plan).
- The backend image rebuild (needed for the new `pytest` marker and `sounddevice` inside Docker) was still downloading at the end of the session, because PyPI was very slow. Run `make up` once. Until then the old image's `make test-docker` also runs the live `stt` tests.

**Needs credentials or manual provider configuration:** none new (`DEEPGRAM_API_KEY` is already in `.env`). Recording real clips needs the speakers' consent.

**Risks or surprises discovered:**
- Deepgram's own endpointing is slow on a realistic line: about 1.6–2.3 s p50 with a faint noise floor, against about 1.0 s with digital silence. A local VAD + `Finalize` gives about 0.85 s. This matters for P6's latency budget (t0 → t1 ≤ 600 ms is not reachable with Deepgram's endpointing alone).
- `smart_format` holds back answers that end in a number for up to 4.5 s, hence it's off.
- "four PM" was heard as "four AM" on 2 of 3 voices, every time. A callback time must be read back to the candidate (P2 callback flow / P6).
- Cities: Noida → "Moida", Gurgaon → "Google". Add the job's city as a per-call keyterm; the read-back catches the rest.
- `nova-2` sometimes loops one word dozens of times ("Infosys Infosys…").
- Flux (`/v2/listen`) returned HTTP 503 on many connections on 2026-11-18. Not ready to depend on.
- Every pause over about 1.3 s mid-answer splits the utterance at any endpointing value. P6 must merge.
- Connecting takes about 0.8–1.5 s from India (US servers): open the stream while the call rings.
- macOS `say` renders the same line differently at random (truncated or garbage); fixed by rendering until two renders agree.
- Deepgram doesn't transcribe "hmm"/"uh" by default, so the filler rule rarely triggers.

**Decisions made:**
- Mine, from the benchmark, open to review: the settings above (especially `smart_format` off and 300 ms endpointing).
- Also mine:
  - A synthetic test set until real recordings exist.
  - Local VAD + `finalize()` recommended for P6.
  - Flux not adopted.
  - The plain `websockets` client.
  - Recorded fixtures kept in the repo (event JSON only, no audio).

## Phase 3 amendment: Deepgram Aura primary, Kitten fallback (2026-11-18)

**Asked by the user** after the Kitten build (d02281b): use Deepgram's TTS as the main voice and Kitten when Deepgram isn't available. Voice chosen by ear from 20 Aura-2 voices: **Harmonia** (Asteria runner-up).

**Implemented:**
- `providers/tts/deepgram_provider.py`: REST `/v1/speak`, linear16 24 kHz streamed. Retries only before the first audio byte, with a 1.5 s first-byte timeout. 401/403/400 → `TTSConfigError`. Fixed phrases fetched 4 at a time and cached on disk (`TTS_CACHE_DIR`). +6 dB soft-limited gain so Harmonia is as loud as Iris.
- `providers/tts/fallback.py`: `FallbackTTSProvider` with these rules:
  - A sentence Deepgram can't deliver goes to Kitten.
  - The call then stays on Kitten (sticky per `call_attempt_id`).
  - Circuit breaker after 3 consecutive failures, open for 60 s.
  - Deepgram is retried every 60 s if it was down at startup.
  - A stream that breaks mid-sentence is repeated on Kitten.
  - Ready if either provider is ready.
- `TTSProvider` gained `stream()` (Kitten yields its whole clip), `apology_clip(call_attempt_id=)` and `forget_call()`. `AudioClip`/`ProviderStatus` gained `components`. `pcm.gain_soft_limited`.
- Settings: `TTS_PROVIDER` (auto/deepgram/kitten; auto = Deepgram when a key is set), `TTS_FALLBACK`, `DEEPGRAM_TTS_VOICE`, `DEEPGRAM_TTS_GAIN_DB`, `DEEPGRAM_TTS_FIRST_BYTE_TIMEOUT_S`, `TTS_CACHE_DIR`. `DEEPGRAM_API_KEY` is in `.env` (not committed).
- Tools: `tts-say` streams like a call and reports which voice spoke (`PROVIDER=`, `VOICE=`). `bench-tts --provider deepgram`. `make test-deepgram-tts`.
- Dockerfile creates a writable `/app/artifacts`.

**Tests:**
- `make test` and `make test-docker` → 342 passed (adds mocked-HTTP Deepgram tests, fallback routing tests and the gain test). The test settings now pin `deepgram_api_key=None`, so the developer's key in Docker's environment can't leak into tests.
- `make test-deepgram-tts` → 3 passed (live). `make test-tts` → 6 passed (Kitten, Docker).
- Lint and mypy clean.
- Live fallback run: outage mid-call → Kitten in 1.76 s for that sentence, then sticky; startup with Deepgram down → ready on Kitten in 4.9 s.

**Numbers** ([benchmarks/tts.md](benchmarks/tts.md#deepgram-aura-primary)):
- First audio p50 337–353 ms, p95 ≤ 445 ms (Docker), whatever the sentence length.
- The whole clip takes about half its audio length, so P6 must play `stream()` output as it arrives.
- Cost about $0.06 per call ($0.030 per 1,000 characters); $200 of free credit on the account.

**Risks:**
- No Aura voice has an Indian accent.
- Deepgram's servers are in the US (about 280 ms round trip from here), so re-measure from the production VM in P10.
- One outage sentence costs about 1.5 s of silence before Kitten speaks; lower `DEEPGRAM_TTS_FIRST_BYTE_TIMEOUT_S` if that's too long. Its p95 is about 450 ms.
- Deepgram is also the planned STT (P4), so one outage affects both; Kitten covers only TTS.
- The API key was shared in chat. Rotate it in the Deepgram console if that's a concern.

## Phase 3 decisions (agreed 2026-11-18)

- Voice: **Iris**, Kitten TTS 2 **nano** (English, 24 kHz), chosen by the user from 18 voices (Kitten 0.8 micro and Kitten 2 nano), listening at phone quality first. Final-pipeline clarity at 8 kHz μ-law scored **4/5** by the user; all 15 test lines fine, no pronunciation fixes needed.

## Phase 3 exit report (2026-11-18)

**Implemented:** Kitten TTS behind `TTSProvider`, loaded once per backend process.
- The model loads in a background task in the FastAPI lifespan, warms up, and pre-synthesizes 17 fixed phrases: the acknowledgements for P6 masking, name-free closings, and the technical apology.
- Inference runs on a thread pool sized to `MAX_CONCURRENT_CALLS`, with 2 ONNX threads each. The text front end runs under a lock.
- A 3 s timeout with one retry, then `TTSTimeoutError` / `TTSSynthesisError`. P6 then plays `apology_clip()`.
- An LRU cache for repeated lines, and per-synthesis latency logging with `call_attempt_id`.
- Output: mono int16 at 24 kHz, silence-trimmed (50 ms padding), peak −3 dBFS.
- A text normalizer with Indian conventions (lakh/crore, LPA, ₹, CTC → "C T C", times, dates, phone numbers) plus `pronunciations.yaml`.
- A sentence chunker (batch and streaming).
- Tools: `make tts-say` (with an 8 kHz μ-law version), `make bench-tts`, `make test-tts`, `make tts-model`.
- Details: [benchmarks/tts.md](benchmarks/tts.md); deviations from the plan: [phase-03 §12](phases/phase-03-kitten-tts.md#12-as-built-2026-11-18).

**Files created / changed:**
- Backend, new: `providers/tts/` (`base.py`, `kitten_provider.py`, `g2p_onnx.py`, factory and fixed phrases in `__init__.py`); `voice/` (`chunker.py`, `text_normalizer.py`, `pronunciations.yaml`, `pcm.py`, `g2p/g2p_bart_en_us.onnx` + `.json`, 3 MB, committed); `scripts/` (`tts_say.py`, `bench_tts.py`, `download_tts_model.py`, `export_g2p_onnx.py`); tests `unit/voice/` (chunker, normalizer, pcm, provider with a fake engine), `integration/test_kitten_provider.py` (marker `tts`), `fixtures/tts_sentences.txt`, `fixtures/tts_corpus.py`.
- Backend, changed:
  - `config.py`: adds `TTS_THREADS`, `TTS_TIMEOUT_S`, `TTS_PRELOAD`; the Kitten settings default to the bundled model and Iris.
  - `main.py`: TTS in the lifespan; `app.state.tts`.
  - `conftest.py`: `tts_preload=False`.
  - `pyproject.toml`: `tts` marker excluded by default, mypy ignores for untyped packages, ruff Unicode ignores for the speech code.
- Infra:
  - Dockerfile: installs `requirements-nodeps.txt` (`kittenml` 0.9.8 `--no-deps`, hash-pinned); downloads the model at build time into `/opt/models/kitten-tts-2-nano` (pinned revision `54526b8d8e45`); sets `HF_HUB_OFFLINE=1`. No system packages.
  - New runtime dependencies (additions only, nothing upgraded): `numpy`, `soxr`, `num2words`, `onnxruntime`, `huggingface-hub`, `misaki`, `spacy`, `en-core-web-sm` 3.8.0, plus their dependencies. No torch, transformers or CUDA.
  - `.dockerignore` excludes `models`; `.gitignore` allows `backend/app/voice/g2p/*.onnx`; the dev compose mounts `backend/artifacts`; Makefile `venv` also installs the no-deps file; `.env.example` gets the TTS settings.
- Docs: `benchmarks/tts.md` (new), `setup.md` (Kitten section, dependencies, troubleshooting, amd64 note), `phases/phase-03` (§12 As built).

**Tests run:**
- `make test` and `make test-docker` → 310 passed, 7 deselected (live LLM eval and the real-model TTS tests).
- `make test-tts` → 6 passed, on the host (103 s) and in Docker (123 s).
- `make lint`, `make typecheck` → clean.
- `make bench-tts --runs 50 --threads 1,2,4` on the host and in Docker (tables in benchmarks/tts.md).
- The `linux/amd64` image (1.07 GB without dev tools) built, loaded the model and synthesized under emulation.
- ONNX vs PyTorch G2P: 4229/4229 words identical, and full sentences identical end to end.

**Acceptance criteria:**
- P3-AC1 ✅ All 210 unique agent replies synthesize: 46 from the P2 eval transcripts plus the P2 templates rendered over names, companies and values (`test_every_agent_reply_synthesizes`).
- P3-AC2 ✅ The load counter is unchanged over 100 syntheses (`test_model_loads_once_over_100_syntheses`), and the backend log shows `model_loads_total=1`.
- P3-AC3 ✅ `make tts-say TEXT=… PHONE=1` writes and plays the clips; checked in Docker.
- P3-AC4 ✅ 24 000 Hz, recorded in benchmarks/tts.md, asserted at load (`TTSConfigError` otherwise) and in tests.
- P3-AC5 ✅ Benchmark tables for the host and Docker. Docker at 2 threads: short sentence p95 215 ms (≤ 300), medium p95 421 ms (≤ 600), RTF 0.087 (≤ 0.3), 2 concurrent 1.38× (≤ 1.5×), loop lag max 2.2 ms (≤ 20).
- P3-AC6 ✅ Iris scored 4/5 for clarity at 8 kHz μ-law by the user; all lines fine.

**Deferred or not done:**
- Benchmark on the target VM (P10, `make bench-tts args='--threads 1,2,4'`); set `TTS_THREADS` from it.
- Telephony codec and framing (P5 `audio_converter.py`). `voice/pcm.py` has resampling (soxr) and a μ-law round trip for listening only.
- TTS status isn't exposed over HTTP yet (P8 settings page). Call eligibility should check `app.state.tts.status().ready` (P5).
- Playback cancellation and streaming into calls are P6. `StreamingChunker` is ready if LLM streaming is added.

**Needs credentials or manual provider configuration:** none. The model is public and downloaded at build time.

**Risks or surprises discovered:**
- The PyPI `kittentts` package is stale (0.1.3). The current package is `kittenml`, and its declared dependencies pull in PyTorch, transformers and diffusers, hence `--no-deps`.
- We rely on two `kittenml` internals, pinned by version: `frontend.english.Fallback` (replaced) and `KittenTTS2Tiny._chunk`. Re-run `make test-tts` and the G2P verification when upgrading.
- Kitten 2 tiny models try to `pip install` spaCy's `en_core_web_sm` at runtime if it's missing; it's pinned in requirements instead.
- espeak's macOS data path is broken in `espeakng-loader` (it only mattered for the 0.8 models, which we don't use).
- Kitten 2 mini is too slow on CPU (RTF 0.36), and the 1.7B flagship needs about 6 GB of RAM and uses a non-Apache weight licence.
- The model is fast, so the image size (1.07 GB) and spaCy's load time (about 7 s at startup) are the main costs. With `--reload` in dev, every code change reloads the voice.
- The developer Mac's Homebrew `ffmpeg` is broken (missing libx265). Not needed by the project; `brew reinstall ffmpeg` should fix it.

**Decisions made:**
- Agreed with the user: the voice (Iris, Kitten 2 nano), and the phone-band score.
- Mine, open to review:
  - G2P fallback on ONNX instead of PyTorch (verified identical); the graph is committed (3 MB).
  - The model is baked into the image rather than a volume.
  - Normalization happens inside `synthesize()`; Kitten's own normalizer stays on as a safety net.
  - 2 ONNX threads by default.
  - Background load at startup; the backend doesn't crash on TTS failure.
  - Fixed phrases come from `agent/prompts.py`, so they can't drift.
  - Real-model tests use the `tts` marker, outside `make test`.

## Phase 2 decisions (agreed 2026-11-18)

- Model: `gpt-5.4-mini` with `OPENAI_REASONING_EFFORT=none` (benchmarked against gpt-5.4-nano, gpt-5.6-luna, gpt-6-luna and gpt-4.1-mini).
- Latency: P2-AC7 is revised from p50 ≤ 1.2 s / p95 ≤ 2.5 s to **p50 ≤ 2.5 s / p95 ≤ 3.5 s**. Phase 6 masks the wait with an instant pre-synthesized acknowledgement ("Okay.", "Got it."). The OpenAI round trip alone is about 1 s, so 1.2 s wasn't reachable. Details: docs/agent.md, phase-06 plan §5.8.
- Phase plan defaults accepted: CTC stored as LPA float plus the candidate's raw words; interest asked first; ranges clarified once, then the lower bound is stored; custom job questions kept as free text; target call length about 5 minutes.

## Phase 2 exit report (2026-11-18)

**Implemented:** a text-only screening agent running against the real OpenAI API.
- A Python state machine owns field status, question order and completion. The LLM extracts values and phrases replies.
- Phases: identity, permission, screening, read-back confirmation and close, with exits for callback, decline, opt-out, wrong person and escalation.
- Values need an evidence quote from the candidate's own words, plus range and unit checks. Clarification (max 2 per field, then unknown), range handling, corrections with history, and consistency confirmations.
- A next-question guardrail (re-prompt once, then template).
- Silence, low STT confidence, interruption and LLM-failure handling.
- A neutral summary with a judgment guard, a text CLI, a live eval harness and a latency benchmark.
- Design and results: [agent.md](agent.md).

**Files created / changed:**
- Backend:
  - `providers/llm/` (`base.py`, `openai_provider.py`, factory in `__init__.py`)
  - `agent/` (`schemas.py`, `state.py`, `extraction.py`, `prompts.py`, `screening_agent.py`, `conversation_manager.py`, `cli.py`)
  - `services/summary_service.py`
  - `tests/unit/agent/` (scripted stub LLM; state, extraction, schema snapshot, manager, summary, adapter and scenario-file tests)
  - `tests/agent_eval/` (`job.yaml`, 16 `scenarios/*.yaml`, `runner.py`, `bench.py`, `test_agent_eval.py`, `results/`)
- Changed: `config.py` adds `OPENAI_REASONING_EFFORT` and `OPENAI_TIMEOUT_S`. The default question order in `schemas/job.py` now asks about interest first; this affects new jobs only, and the Phase 1 test was updated. `pyproject.toml` adds the `llm` marker, excluded by default, plus ruff ignores for the CLI and eval tools.
- Infra: new dependencies `openai` 3.55.0 and `pyyaml` (runtime; pyyaml was already present through uvicorn) and `types-PyYAML` (dev). These are additions only, nothing upgraded. Makefile adds `agent-cli`, `agent-eval` and `llm-bench`. `.env.example` has the OpenAI defaults.
- Docs: `agent.md` (new), `setup.md` (OpenAI section, troubleshooting), `phases/phase-02` (AC7 revised), `phases/phase-06` (latency budget and acknowledgement masking).

**Tests run:**
- `make test` and `make test-docker` → 228 passed, 1 deselected (the live eval).
- `make lint`, `make typecheck` → clean.
- `make agent-eval` (live, `gpt-5.4-mini`, 16 scenarios × 3) → **48/48 passed**. Safety 100%, other checks 100%, 195 LLM calls with 0 retries, $0.39.
- `make llm-bench` across 5 models; CLI replay of the happy path.

**Acceptance criteria:**
- P2-AC1 ✅ Scenario 14 passes 3/3; the CLI transcript is in agent.md.
- P2-AC2 ✅ Scenario 2 passes 3/3 (location and company from one answer; company never asked).
- P2-AC3 ✅ 0 repeated questions across all 48 runs. This is checked automatically from turn labels and phrase matching on every reply.
- P2-AC4 ✅ Scenarios 3 and 10 pass 3/3.
- P2-AC5 ✅ 100% of turns validated on the first try; retry rate 0%.
- P2-AC6 ✅ Scenarios 4, 5, 11 (and 13) pass 3/3. The evidence check drops unsupported values, and the unit tests cover it.
- P2-AC7 ✅ against the **revised** target: p50 2.26 s, p95 3.53 s in the eval (benchmark p50 2.63 s). ❌ against the original 1.2 s target. The user chose to revise it and mask the wait in P6.

**Deferred or not done:**
- §7.3 simulated-candidate run (optional): not built. Worth adding before or during P6 to track field accuracy across prompt changes.
- Persisting conversations, the post-call extraction pass and Sheets sync are P6/P7, as planned. `ScreeningResult` and `snapshot()` are ready for them.
- The output-schema trim (saves about 0.3 s per turn) was offered and not chosen. Revisit if P6 latency is tight.

**Needs credentials or manual provider configuration:** none new. `OPENAI_API_KEY` is set in `.env`; please make sure a monthly spend limit is set in the OpenAI dashboard.

**Risks or surprises discovered:**
- OpenAI latency is dominated by a fixed round trip (about 1 s, even for "Say ok."). The model, output size and the priority tier barely change it. Server location in P10 will matter.
- Reasoning models here reject `effort=minimal`; only `none` works.
- The SDK (openai 3.x) uses `httpx2`, not `httpx`.
- Prompt caching is inconsistent: 51% of input was cached in the eval, 0% in a sequential CLI run. The static prefix is barely over the 1,024-token minimum.
- The first live run caught 2 state bugs the stub tests missed (same-turn "confirmation" of a correction; a read-back "yes" confirming fields that weren't read back). Both are fixed and have unit tests. Live evals are worth re-running after every prompt or logic change.

**Decisions made:**
- Agreed with the user: the model, the revised latency target and P6 masking, and the plan defaults (see above).
- Mine, open to review:
  - The LLM sees unit-suffixed keys (`total_experience_years`, `current_ctc_lpa`); Python maps them to the DB column names. Field names in lists are free strings and normalized in Python, so a near-miss name isn't lost.
  - Message order is system → job → history → state → utterance (the plan had state before history), for better prefix caching.
  - The greeting, introduction, role line, read-back, closing and all exit lines are templates with no LLM wording. The permission answer leads straight into the role line plus the first question.
  - A correction during the read-back is stored as confirmed and the call closes (no second read-back).
  - "Not now" with no time asks once for a time. If the answer is vague, the call ends with `needs_recruiter=true` and no automatic callback.
  - `store=False` on every OpenAI request; `prompt_cache_key=screening-<job id>`.
  - Summaries use the structured answers only, not the raw transcript. P7's post-call pass can add transcript context.

## Phase 1 decisions (agreed 2026-11-18)

- Phone numbers are unique across all jobs: one record per person; re-imports are flagged as duplicates.
- Deleting a candidate is a soft delete: hidden and never called, history kept.
- Consent: the recruiter ticks an attestation checkbox per import; calls are blocked without it.
- Import formats: `.csv` and `.xlsx` only.

## Phase 1 exit report (2026-11-18)

**Implemented:** all seven plan.md §5 tables plus `users` and `import_batches`, in one reviewed Alembic migration. Candidate and job CRUD (route → service → repository). The CSV/Excel import pipeline: upload → auto-mapped preview → optional remap → consent → confirm. Recruiter login with Argon2 hashes, Redis sessions, a CSRF origin check and a login rate limit. Five plain frontend pages: login, candidate list, upload, candidate detail, job settings. Also a small "Add candidate" page (plan.md Module A: create candidates manually).

**Files created / changed:**
- Backend: `database/models/` (base, enums and one module per table), `database/migrations/` (async `env.py`, `0001_initial.py`), `alembic.ini`; `repositories/` (candidate, job, user, import); `services/` (candidate, job, import, `import_validation`, auth, errors); `schemas/` (common, candidate, job, imports, auth); `api/deps.py`, `api/v1/` (auth, candidates, imports, jobs); `utils/phone.py`, `utils/file_parsing.py`, `utils/candidate_fields.py`; `scripts/create_user.py`, `scripts/export_openapi.py`; worker cron `expire_import_previews`; tests in `tests/unit/`, `tests/integration/` and `tests/fixtures/imports/` (generated by `make_import_fixtures.py`).
- Frontend: `app/login/`, `app/(recruiter)/` (layout, `candidates/`, `candidates/new/`, `candidates/upload/`, `candidates/[id]/`, `settings/job/`), `components/` (nav, ui), `lib/use-load.ts`, `lib/labels.ts`, `lib/api.ts` (401 → `/login`, `send`, `errorMessage`), `services/*.ts`, `types/api.ts` (generated), `types/index.ts`, `public/candidate-template.csv`; `openapi-typescript` 7.13.0 dev dependency.
- Infra: new deps `python-multipart`, `openpyxl`, `phonenumbers`, `email-validator`, `argon2-cffi` (additions only, nothing upgraded). The backend container runs `alembic upgrade head` before starting. Makefile adds `migrate`, `migration`, `create-user` and `types`, and `test-docker` now uses the `recruitment_ai_test` database.
- Docs: `api.md` (auth, endpoints, error codes), `setup.md` (create user, migrations, types), README.

**Tests run:**
- `make test` → 128 passed (60 unit, 68 integration against real Postgres and Redis)
- `make test-docker` → 128 passed
- `make lint` → ruff and eslint clean; `make typecheck` → mypy strict and tsc clean; `npm run build` succeeds
- Manual end-to-end check through the Next.js proxy (port 3010): create user → login → create job → upload `mixed_10.xlsx` → confirm → list → `docker compose down && make up` → data still present. All pages return 200. The test data was deleted afterwards.

**Acceptance criteria:**
- P1-AC1 ✅ Through the API: `mixed_10.xlsx` → preview → confirm → 8 candidates listed (integration test, plus the manual run through the proxy). The UI screens build and render, but nobody has clicked through them in a browser yet.
- P1-AC2 ✅ The preview and report give the row number, field and reason (e.g. row 11, phone, "Phone number is too short")
- P1-AC3 ✅ Duplicates in the file and against existing records are flagged. Re-importing leaves existing records unchanged, including `updated_at` and screening data (`test_reimport_flags_existing_and_changes_nothing`)
- P1-AC4 ✅ After `docker compose down && make up`, the same 8 candidates were still there
- P1-AC5 ✅ Edit, search (name, email, phone digits), status and interest filters, sorting and pagination are covered by integration tests. The detail page form is built but hasn't been checked in a browser
- P1-AC6 ✅ A parametrized test over the OpenAPI route list: all 18 protected route/method pairs return 401 without a session
- P1-AC7 ✅ Upgrade → downgrade base → upgrade passes on a fresh database, and `alembic check` finds no drift

**Deferred or not done:**
- No browser-driven UI test yet (Playwright is planned for P10). Please click through the pages once.
- Candidate list columns for calls (call status, last call date, call/retry actions) come in P8, as planned.

**Needs credentials or manual provider configuration:** none. Create a login with `make create-user email=… name=…`.

**Risks or surprises discovered:**
- Next.js 16 with `cacheComponents` requires a `<Suspense>` boundary around any client component that reads the URL (`usePathname`, `useParams`, `useSearchParams`) on dynamic routes. The production build caught this; the nav and the detail page are wrapped.
- SQLAlchemy 2.1 changed the `Select[...]` generic typing; the repository annotations follow it.
- `FRONTEND_ORIGIN` must match the browser URL exactly (this machine uses `http://localhost:3010`), or every save fails with `csrf_failed`. This is noted in setup.md.

**Decisions made:**
- Agreed with the user earlier: unique phone across jobs, soft delete, consent attested per import (and per manual entry), `.csv`/`.xlsx` only.
- Mine, open to review:
  - Soft-deleted candidates keep their phone reserved. Re-adding the number returns 409 with `deleted: true` instead of silently creating a second record.
  - Setting `opted_out` also sets `screening_status = opted_out`.
  - The first job created becomes active automatically.
  - Redis stores sessions under a SHA-256 of the cookie token (`rcai:session:<hash>`), not the raw token.
  - The login rate limit keys on client IP + email. Behind the Next.js proxy every request has the same IP, so it is effectively per email.
  - An `updated_at` trigger in Postgres also covers writes that bypass the ORM.
  - Standard screening questions keep fixed keys and types; custom keys are allowed.

## Phase 0 exit report (2026-11-18)

**Implemented:** runnable skeleton. Next.js 16 frontend, FastAPI backend, PostgreSQL 16, Redis 7 and an ARQ worker start with `make up`. Configuration is validated at startup, liveness/readiness endpoints exist, logs are structured with secret redaction, and setup/architecture/API/telephony docs are written.

**Files created:** `docker-compose.yml`, `docker-compose.override.yml`, `.env.example`, `.gitignore`, `Makefile`, `README.md`; `backend/` (Dockerfile, requirements, `app/main.py`, `config.py`, `api/health.py`, `api/middleware.py`, `api/responses.py`, `database/connection.py`, `utils/redis.py`, `utils/log.py`, `workers/settings.py`, tests, plus empty packages from plan.md §8); `frontend/` (create-next-app, `next.config.ts` rewrites, `lib/api.ts`, status page, Dockerfile); `docs/architecture.md`, `setup.md`, `api.md`, `telephony.md`.

**Tests run:**
- `make test-docker` → 19 passed (real Postgres and Redis)
- `make test` (local venv) → 18 passed, 1 skipped (real-services test skips without Docker)
- `make lint` → ruff + eslint clean; `make typecheck` → mypy strict + tsc clean
- `npm run build` and production image builds (`backend`, `frontend --target runner`) succeed; production frontend container serves HTTP 200

**Acceptance criteria:**
- P0-AC1 ✅ Frontend starts: http://localhost:3010 → 200, status page shows live readiness
- P0-AC2 ✅ Backend starts: `/health` → 200, `/docs` → 200
- P0-AC3 ✅ PostgreSQL: ready → ok; Postgres stopped → 503 `database: error`; restarted → ok
- P0-AC4 ✅ Redis: same test; Redis stopped → 503 (redis and worker heartbeat error); restarted → ok
- P0-AC5 ✅ Health responses match the documented shapes; tests pass
- P0-AC6 ✅ `.env` gitignored; `.env.example` has empty secrets; the real `APP_SECRET_KEY` value appears in no committable file. gitleaks itself isn't installed yet (`brew install gitleaks`)
- P0-AC7 ✅ Worker: stopped → `worker: error` after ~95 s (heartbeat TTL is 90 s from the last write); restarted → ok
- P0-AC8 ✅ `make lint typecheck test` pass

**Decisions made:**
- ARQ for background jobs (0.28.0, released April 2026, so maintained).
- Repo root is this folder; git initialized on `main` (nothing committed yet).
- Host ports configurable: `BACKEND_PORT`/`FRONTEND_PORT`. This machine uses **8010/3010** because another local app uses 8000 and 3000.
- Next.js rewrites read `BACKEND_INTERNAL_URL` at build/start time, so Docker passes it as a build argument.

**Deferred / not done:** gitleaks pre-commit hook (tool not installed). Alembic setup is Phase 1 by plan.

**Needs credentials or manual setup:** Exotel enablement questions in [telephony.md](telephony.md) still need to be sent to Exotel. An OpenAI API key with billing is needed for Phase 2.

**Risks discovered:** Next.js 16.4 differs from older versions (its `AGENTS.md` says to check bundled docs before writing code); followed for config. Local Python is 3.13/3.14 by default; the backend venv and image pin 3.12.
