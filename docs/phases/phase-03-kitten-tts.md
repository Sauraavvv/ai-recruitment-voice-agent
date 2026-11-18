# Phase 3: Kitten TTS integration

| | |
|---|---|
| Source | plan.md §10 Phase 3, Module D (TTS service, audio conversion), §12 performance |
| Depends on | P0 (P2 agent replies make a good test corpus) |
| Unlocks | P5 (test clip), P6 |
| Size / risk | M / Medium |

## 1. Goal

A TTS service that loads the Kitten model once, turns agent text into PCM audio of a known format fast enough for live calls, sounds acceptable over a phone line, and sits behind `TTSProvider` so it can be replaced.

## 2. Entry criteria

P0 accepted. Headphones for listening tests.

## 3. Scope

- **In:** plan.md tasks 1–9, text normalization for speech, a phone-band listening test, benchmarks.
- **Out:** conversion to the telephony codec and framing (P5's `audio_converter.py`, once the real format is known); streaming into calls (P6).

## 4. Deliverables

```text
backend/app/providers/tts/  base.py  kitten_provider.py
backend/app/voice/          chunker.py  text_normalizer.py  pronunciations.yaml
backend/app/scripts/        tts_say.py  bench_tts.py
backend/Dockerfile          (system packages for TTS)
backend/app/tests/          unit/voice/test_chunker.py  unit/voice/test_text_normalizer.py
                            integration/test_kitten_provider.py  (marked slow)
                            fixtures/tts_sentences.txt
docs/benchmarks/tts.md
```

## 5. Tasks

### P3-T1 Install the Kitten TTS package

- **[Verify]** current distribution. At the time of writing, KittenTTS is published by KittenML on GitHub (release wheels) with model weights on Hugging Face. Pin the exact version or wheel URL with a hash in `requirements.txt`.
- **[Verify]** phonemizer dependency: some versions rely on `espeak-ng` (system package) and some bundle it through a loader package. If the system package is needed, add it to the backend Dockerfile (`apt-get install espeak-ng`) and to docs/setup.md (`brew install espeak-ng`).
- Inference runs on ONNX Runtime (CPU). Confirm wheels exist for Apple Silicon (local) and the Docker/VM architecture.
- Check the licence of the package and the model weights **[Verify]**.

### P3-T2 Download and configure the English model

- List the available English model variants and voices **[Verify]**; shortlist the smallest variant plus one larger one if available.
- Download at image build time, or into a mounted volume at `KITTEN_MODEL_PATH`. Never download during a call. Use Hugging Face offline mode once cached.
- Validate `KITTEN_VOICE` at startup against the model's voice list.

### P3-T3 TTS provider interface

plan.md's interface plus what the pipeline needs:

```python
@dataclass(frozen=True)
class AudioClip:
    pcm: bytes          # signed 16-bit little-endian, mono
    sample_rate: int    # model's native rate
    duration_ms: int

class TTSProvider(ABC):
    sample_rate: int
    async def initialize(self) -> None          # load + warm up
    async def synthesize(self, text: str) -> AudioClip
    async def close(self) -> None
    def status(self) -> ProviderStatus          # loaded?, last error, last latency (P8 settings page)
```

TTS returns its native format. Conversion to the telephony format is a separate step (P5), so either side can change independently.

### P3-T4 Load the model once

- One provider instance per backend process, created in FastAPI `lifespan`. `initialize()` loads the model and synthesizes a warm-up sentence.
- Inference runs on a dedicated executor (`ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS)`), never on the event loop (plan.md §12).
- Limit ONNX Runtime intra-op threads so two concurrent calls don't compete for every core **[Verify how the package exposes session options]**.
- Measure event-loop lag during synthesis (P3-T7). If it exceeds 20 ms (which would disturb 20 ms audio pacing in P6), move inference to a `ProcessPoolExecutor` or a separate TTS process behind the same interface.
- A counter `tts_model_loads_total` proves the model isn't reloaded.

### P3-T5 Generate speech from text

- Convert model output (float32 in [-1, 1] **[Verify]**) to int16 with clipping.
- Trim leading/trailing silence above a threshold, keeping about 50 ms of padding; this saves latency on every sentence.
- Normalize to a consistent peak (about −3 dBFS) so audio isn't too quiet on a phone line; confirm by ear in P3-T6.
- Input guards: empty text → no audio; text over 400 characters goes through the chunker first.

### P3-T6 Verify audio output

- `make tts-say TEXT="…"` writes `artifacts/tts/*.wav` and plays it (`afplay` on macOS).
- Test sentences in `tests/fixtures/tts_sentences.txt`:
  - greetings with Indian names (Rahul Sharma, Priya Iyer, Venkatesh)
  - cities (Gurgaon, Bengaluru, Hyderabad, Noida) and companies (Infosys, TCS, Wipro, HCLTech)
  - numbers ("12.5 lakhs per annum", "60 days", "five and a half years")
  - times ("tomorrow at 5 PM"), a long question, a short acknowledgement
- **Phone-band test:** downsample every clip to 8 kHz (and round-trip through μ-law) and listen again. This is what candidates will hear. Pick the voice that stays clearest after downsampling.
- Score each voice 1–5 for clarity, naturalness and name pronunciation in docs/benchmarks/tts.md. The user takes part in choosing the voice.

### P3-T7 Benchmark latency

Run `python -m app.scripts.bench_tts` on the dev machine **and** inside the Docker image (and on the target VM in P10). 50 runs each; report p50/p95 with CPU model and thread settings.

| Metric | Proposed target |
|---|---|
| Model load time (cold) | Record only |
| First-sentence latency, short (~5 words), warm | ≤ 300 ms p95 |
| Medium sentence (~15 words), warm | ≤ 600 ms p95 |
| Long sentence (~30 words), warm | Record |
| Real-time factor (synthesis time ÷ audio duration) | ≤ 0.3 |
| Two concurrent syntheses | ≤ 1.5× single |
| Event-loop lag during synthesis | ≤ 20 ms |

### P3-T8 Sentence chunking (`voice/chunker.py`)

- Split on `.`, `?`, `!` boundaries without splitting decimals (5.5), abbreviations (Mr., Dr., Pvt., Ltd., e.g.) or initials.
- Max chunk about 20 words; split long sentences at commas or conjunctions.
- Merge fragments shorter than 3 words into the next chunk.
- Prefer a short **first** chunk ("Got it." / "Thanks, Rahul.") so the first audio starts sooner.
- Works on whole replies (P2 returns complete text) and stays usable if LLM streaming is added later.

### P3-T9 Error handling

- Model load failure at startup → `TTSProvider.status()` reports an error, and call eligibility (P5) refuses to dial. A call never starts without a working voice.
- Synthesis exception or timeout (3 s) → retry once; then the call session plays a pre-synthesized apology ("Sorry, I'm having a technical problem. We'll call you back.") and ends the call (P6). The apology is generated at startup **by the same Kitten model**.
- Phrase cache: LRU cache keyed by voice + normalized text for fixed phrases (greeting templates without names, acknowledgements, "Could you repeat that?", closings), pre-synthesized at startup.
- Per-synthesis latency logged with `call_attempt_id` when present (plan.md §12).

### P3-T10 Text normalization for speech (added, `voice/text_normalizer.py`)

Kitten reads text literally, so normalize before synthesis:

- Numbers → words with Indian conventions (`num2words`, `lang="en_IN"` **[Verify]**): 12.5 → "twelve point five"; 1,20,000 → "one lakh twenty thousand".
- Units and acronyms: LPA → "lakhs per annum", CTC → "C T C", AI → "A I", HR → "H R", ₹ → "rupees", % → "percent", "5 PM" → "five P M".
- Strip markdown, emoji and URLs.
- `pronunciations.yaml`: respellings for names or companies that come out wrong, editable without code changes.

## 6. Tests

- **Unit:** chunker (abbreviations, decimals, long sentences, merging), normalizer (numbers, units, currency, lexicon), float → int16 conversion (clipping, length), silence trimming.
- **Integration** (`slow`, real model): all test sentences produce non-empty audio at the expected sample rate with duration roughly proportional to text length; 100 consecutive syntheses → `tts_model_loads_total == 1`; a bad `KITTEN_MODEL_PATH` or unknown voice → clear startup error.

## 7. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P3-AC1 | TTS can synthesize arbitrary agent responses | All P2 eval agent replies (≥ 100) synthesize without error |
| P3-AC2 | Model is not reloaded for each response | Load counter = 1 after 100 syntheses (test) |
| P3-AC3 | Audio can be played in a local test | `make tts-say` plays clear audio |
| P3-AC4 | Model output sample rate is known | Value recorded in docs/benchmarks/tts.md and asserted at startup |
| P3-AC5 | Latency measurements are recorded | Benchmark table (local + Docker) in docs/benchmarks/tts.md |
| P3-AC6 (added) | Acceptable on a phone line | Chosen voice scores ≥ 4/5 clarity after 8 kHz downsampling, agreed with the user |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Voice quality poor in the 8 kHz phone band | Test early; try other voices/variants; provider stays replaceable (plan.md §2 rule 7) |
| CPU latency too high on the server | Benchmark on target hardware (P10 sizing); phrase cache; short first chunk |
| Event-loop stalls from inference | Measure lag; move to a separate process if needed |
| Missing system dependency in the image | Dockerfile + startup self-test |
| Indian names mispronounced | Pronunciation file; normalizer |

## 9. Open decisions

| Decision | Recommendation |
|---|---|
| Voice and model variant | Choose with the user from the listening test |
| Larger variant if latency allows | Only if it clearly wins the 8 kHz listening test and meets the latency targets |

## 10. Manual setup

None beyond installing the package and model. Listening sessions with the user.

## 11. Exit

[Phase exit report](README.md#phase-exit-report) with the benchmark table and the chosen voice.

## 12. As built (2026-11-18)

Details and numbers: [benchmarks/tts.md](../benchmarks/tts.md). Where the build departs from the plan:

- **Package and model:** `kittenml` 0.9.8 from PyPI (the `kittentts` package is stale), with **Kitten TTS 2 nano**, English, voice **Iris**, chosen by the user. Output is 24 kHz.
- **No espeak, no PyTorch:** Kitten 2's English front end doesn't use espeak, so the Dockerfile needs no system packages. Its BART pronunciation fallback was exported to ONNX (`app/scripts/export_g2p_onnx.py`, verified identical on 4229 words) and replaces upstream's PyTorch version (`app/providers/tts/g2p_onnx.py`). `kittenml` is installed `--no-deps` from `requirements-nodeps.txt`.
- **Model files:** downloaded at image build time at a pinned revision (`app/scripts/download_tts_model.py`) into `/opt/models/kitten-tts-2-nano`. `HF_HUB_OFFLINE=1`. `KITTEN_MODEL_PATH` stays empty unless overridden.
- **Extra files:** `voice/pcm.py` (int16, trim, normalize, 8 kHz μ-law listening aid), `voice/g2p/` (the ONNX graph), `providers/tts/g2p_onnx.py`, `scripts/download_tts_model.py`, `scripts/export_g2p_onnx.py`, `tests/fixtures/tts_corpus.py`, `tests/unit/voice/test_pcm.py`, `test_kitten_provider.py` (unit, fake engine).
- **Startup:** the model loads in a background task in the FastAPI lifespan. The API is usable meanwhile, and `app.state.tts.status()` reports `loading` / ready / the error. `TTS_PRELOAD=false` turns this off (tests).
- **Normalization lives in the provider:** `synthesize()` takes raw agent text and normalizes it. Kitten's own normalizer still runs afterwards, as a safety net.
- **Tests:** the real-model tests are marked `tts` (excluded from `make test`, run with `make test-tts`) instead of `slow`.
