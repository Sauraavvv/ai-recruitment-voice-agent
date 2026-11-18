# TTS benchmarks and voice choice (Phase 3)

**Chosen:** Kitten TTS 2 **nano**, English, voice **Iris** ("hushed museum guide", female).
The user chose it in the listening test on 2026-11-18.

| | |
|---|---|
| Package | `kittenml` 0.9.8 (PyPI, Apache-2.0), installed `--no-deps` (`backend/requirements-nodeps.txt`) |
| Model | [`KittenML/kitten-tts-2-nano`](https://huggingface.co/KittenML/kitten-tts-2-nano) @ `54526b8d8e45`, English files only (25 MB), Apache-2.0 |
| Output | **24 000 Hz**, mono, float32 from the model → int16 PCM. Asserted at startup (`EXPECTED_SAMPLE_RATE`). |
| Inference | ONNX Runtime 1.32 (CPU), int8 weights, 2 intra-op threads per synthesis (`TTS_THREADS`) |
| Text front end | Our normalizer (`app/voice/text_normalizer.py`), then Kitten's: misaki lexicon → CMUdict → a small BART for unknown words. The BART runs as ONNX (see below). No espeak. |
| Post-processing | Silence trimmed (−45 dBFS threshold, 50 ms padding), peak normalized to −3 dBFS |

## What was evaluated

The plan assumed the PyPI package `kittentts`. It turned out to be stale (0.1.3, August 2025).
The current package is `kittenml`, and it ships two model families:

| Candidate | Size | Result |
|---|---|---|
| Kitten 0.8 nano (int8) / micro / mini | 15–80 M params | 8 voices, light (espeak via `espeakng-loader`). Fast enough except mini (medium sentence 610 ms on an M2). |
| **Kitten 2 nano** | 17 M params | 10 English voices, fast. Its English G2P needs a BART model, which upstream runs in PyTorch. |
| Kitten 2 mini | 82 M params | Too slow: real-time factor 0.36, short sentence 594 ms. Rejected. |
| Kitten 2 (flagship) | 1.7 B params | Needs about 6 GB of RAM (this Mac has 8 GB, Docker 4 GB), and the weights use the separate Stellon Labs community licence. Not tested. |

Round 1 of the listening test covered all 18 voices of 0.8-micro and 2-nano, on 3 call sentences,
in wideband and 8 kHz μ-law. The user picked **Iris** (2-nano).

### Removing PyTorch

Kitten 2's English front end guesses the pronunciation of words missing from its dictionaries
with a 0.75 M-parameter character BART. That covers most Indian surnames, e.g. Chaturvedi,
Khandelwal, Shekhawat. Upstream loads it with PyTorch and transformers, which would add about
700 MB to the image and need PyTorch's CPU-only package index. Instead:

- `app/scripts/export_g2p_onnx.py` exported the BART once to ONNX
  (`backend/app/voice/g2p/g2p_bart_en_us.onnx`, 3 MB, committed).
- `app/providers/tts/g2p_onnx.py` runs it with greedy decoding and replaces upstream's
  `Fallback` class.
- **Verified:** 4229/4229 words gave identical phonemes with ONNX and PyTorch (4000 CMUdict words,
  plus 229 Indian names, cities and companies in three capitalisations). Full sentences gave
  identical phoneme strings end to end, including the four words that went through the BART.

Re-export the graph if the model revision ever changes `g2p/`.

## Latency (P3-T7)

Command: `python -m app.scripts.bench_tts --runs 50 --threads 1,2,4` (`make bench-tts` in Docker).
Each synthesis includes normalization, G2P, the model, trimming and int16 conversion. Every run
skips the phrase cache.

**Host:** Apple M2, 8 cores, macOS arm64, 50 runs per sentence

| Threads | Cold load | Short p50 / p95 | Medium p50 / p95 | Long p50 / p95 | RTF (m) | 2 concurrent (× single) | Loop lag p99 / max |
|---|---|---|---|---|---|---|---|
| 1 | 2.2 s | 189 / 203 ms | 544 / 609 ms | 1083 / 1113 ms | 0.121 | 593 ms (1.09×) | 0.7 / 1.3 ms |
| **2** | 1.13 s | 131 / 135 ms | 341 / 355 ms | 664 / 686 ms | 0.076 | 451 ms (1.32×) | 0.7 / 7.4 ms |
| 4 | 0.98 s | 112 / 120 ms | 262 / 275 ms | 501 / 528 ms | 0.058 | 425 ms (1.62×) | 0.8 / 3.6 ms |

**Docker:** `linux/arm64` image on Docker Desktop (Apple M2, 8 vCPU, 4 GB), 50 runs per sentence

| Threads | Cold load | Short p50 / p95 | Medium p50 / p95 | Long p50 / p95 | RTF (m) | 2 concurrent (× single) | Loop lag p99 / max |
|---|---|---|---|---|---|---|---|
| 1 | 3.88 s | 240 / 356 ms | 604 / 693 ms | 1210 / 1563 ms | 0.133 | 664 ms (1.1×) | 1.4 / 40.1 ms |
| **2** | 1.29 s | 182 / 215 ms | 398 / 421 ms | 753 / 804 ms | 0.087 | 550 ms (1.38×) | 1.3 / 2.2 ms |
| 4 | 1.21 s | 170 / 195 ms | 325 / 363 ms | 591 / 729 ms | 0.071 | 536 ms (1.65×) | 1.4 / 2.4 ms |

Sentences: short "Got it, thank you." (≈1.0 s of audio), medium (≈4.5 s), long (≈9.8 s).
"Cold load" is measured after the Python imports in the same process. The backend's first full
load, including imports, spaCy and 17 pre-synthesized phrases, takes about 7 s in Docker. It
runs in the background at startup.

Against the targets (Docker, 2 threads):

| Metric | Target | Result |
|---|---|---|
| Short sentence, warm | ≤ 300 ms p95 | ✅ 215 ms |
| Medium sentence, warm | ≤ 600 ms p95 | ✅ 421 ms |
| Long sentence, warm | record | 804 ms p95 |
| Real-time factor | ≤ 0.3 | ✅ 0.087 |
| Two concurrent syntheses | ≤ 1.5× single | ✅ 1.38× |
| Event-loop lag during synthesis | ≤ 20 ms | ✅ 2.2 ms max |

**Default: 2 threads.** 4 threads is about 20% faster on one call but scales worse with two
concurrent calls (1.65×). The single-thread run had one 40 ms loop-lag spike, out of a p99 of
1.4 ms. Re-run on the target VM in Phase 10 (`make bench-tts args='--threads 1,2,4'`) and set
`TTS_THREADS` from that.

## Listening test (P3-T6, P3-AC6)

Round 1 (voice choice): 18 voices × 3 sentences, phone band first. The user chose Iris.

Round 2 (final pipeline): the 15 sentences in `backend/app/tests/fixtures/tts_sentences.txt`
through the production path (normalizer → ONNX G2P → model → trim → normalize), downsampled to
8 kHz and round-tripped through μ-law.

| Voice | Clarity (8 kHz) | Naturalness | Names | Notes |
|---|---|---|---|---|
| Iris (2-nano) | **4/5** | not scored separately | all 15 lines fine | Scored by the user, 2026-11-18. No pronunciation fixes needed. |

## Reproducing

```bash
make tts-say TEXT="Hello, am I speaking with Priya Iyer?" PHONE=1   # listen
make test-tts                                                      # real-model tests
make bench-tts args='--runs 50 --threads 1,2,4'                    # this table
```
