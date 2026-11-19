# Local setup

## Prerequisites

| Tool | Version used | Install |
|---|---|---|
| Docker Desktop (with Compose v2) | latest | `brew install --cask docker`, then open Docker once |
| Python | 3.12 (for running backend tests outside Docker) | `brew install python@3.12` |
| uv | 0.13+ | `brew install uv` |
| Node.js | 26 (local); Docker image `node:26-alpine` | `brew install node` |
| git | 2.54 | Xcode command line tools |

Recorded on the development machine (Phase 0, 2026-11-18): macOS 26.6.2, Apple Silicon (`arm64`), Python 3.12.16, Node 26.7.0, npm 11.19.0, git 2.54.0, uv 0.13.9.

Apple Silicon note: Docker builds `linux/arm64` images locally. A production server is likely `linux/amd64`: check that the backend image builds for it with `docker buildx build --platform linux/amd64 backend` (done in Phase 3; see [benchmarks/tts.md](benchmarks/tts.md)).

The project folder name contains a space (`project 2`). Quote paths in shell commands and scripts.

## First run

```bash
make env          # creates .env with a random APP_SECRET_KEY (doesn't overwrite an existing .env)
make up           # builds and starts postgres, redis, backend, worker, frontend
make ps           # all services should be "running" / "healthy"
make create-user email=you@example.com name="Your Name"   # prompts for a password (10+ chars)
```

The backend applies database migrations (`alembic upgrade head`) every time its container starts. Then log in at http://localhost:3000/login, create the job under **Job settings**, and upload candidates.

| URL | What |
|---|---|
| http://localhost:3000 (3010 on this machine) | Frontend: opens the login page; after login `/dashboard` (calls and analytics); candidates at `/candidates`; system status at `/status` |
| http://localhost:8000/health | Backend liveness |
| http://localhost:8000/health/ready | Database, Redis and worker readiness |
| http://localhost:8000/docs | API reference (development only) |

Host ports for Postgres and Redis are **5433** and **6380** so they don't clash with local installs. Backend and frontend host ports come from `BACKEND_PORT` and `FRONTEND_PORT` in `.env` (default 8000 / 3000); change them if another app already uses those ports, and keep `FRONTEND_ORIGIN`/`FRONTEND_URL` in step with `FRONTEND_PORT`. On the original dev machine they are **8010** and **3010**.

## Backend tests and checks without Docker

```bash
make venv         # creates backend/.venv with Python 3.12 and installs dependencies
make test         # pytest (the real-services test is skipped unless postgres/redis are running)
make lint         # ruff + eslint
make typecheck    # mypy + tsc
```

## Database migrations

```bash
make migrate                      # apply pending migrations (also runs on backend start)
make migration m="add something"  # autogenerate a new revision from model changes; review it by hand
```

Migrations live in `backend/app/database/migrations/versions/`. Autogenerate misses some things (partial indexes, CHECK constraints, triggers), so always read the generated file.

Integration tests use a separate database, `recruitment_ai_test`, created and migrated automatically, with every test rolled back.

## Frontend API types

`frontend/types/api.ts` is generated from the backend's OpenAPI schema. After changing an API schema, run `make types` (needs the stack running) and commit the result.

## Dependencies

- Backend: edit `backend/requirements.in` or `requirements-dev.in`, then `make lock` (pins exact versions with hashes in `requirements.txt`).
- `backend/requirements-nodeps.txt` holds packages installed with `--no-deps` (currently `kittenml`, whose declared dependencies include PyTorch, which we don't use). Update its version and hash by hand.
- Frontend: `npm install <pkg>` inside `frontend/`.

## Configuration

All settings come from `.env` (see `.env.example`). The backend refuses to start if a required variable is missing or invalid and prints the variable names. Provider keys (OpenAI, Deepgram, Exotel, Google) can stay empty until their phase.

### OpenAI (Phase 2 onwards)

Set `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-5.4-mini` and `OPENAI_REASONING_EFFORT=none`, then run `make up` so the containers reload `.env`. Set a monthly spend limit in the OpenAI dashboard. Then:

- `make agent-cli`: chat with the agent as a candidate, using the active job.
- `make agent-eval`: the live scenario suite (about $0.40 for 3 runs).
- `make llm-bench models=a,b args='--effort none'`: compare model latency.

These call the real API; `make test` never does. See [agent.md](agent.md).

### Voice: Kitten (Iris) with Deepgram Aura fallback (since 2026-11-19)

The agent speaks with **Kitten TTS, voice Iris**, on the backend's own CPU. After live calls the user found Iris clearer on the phone than Deepgram's Harmonia (2026-11-19), so Kitten is the primary and **Deepgram Aura-2 Harmonia** is the fallback when `DEEPGRAM_API_KEY` is set: it takes over when Kitten errors or takes longer than `TTS_TIMEOUT_S` (3 s). Once a call falls back, it stays on Deepgram until it ends. After 3 failures in a row, Kitten is skipped for 60 s. Without a key, Kitten speaks alone. `TTS_PROVIDER=deepgram` puts Deepgram first again (the Phase 3 setup). Settings and rules: `.env.example` (`TTS_PROVIDER`, `DEEPGRAM_TTS_*`) and `backend/app/providers/tts/fallback.py`. Cost: $0.030 per 1,000 characters, about $0.06 per call. New accounts get $200 of free credit.

- `make tts-say TEXT="…" PROVIDER=kitten` hears the fallback voice. `VOICE=aura-2-asteria-en` tries another Deepgram voice.
- `make test-deepgram-tts`: live Deepgram tests (a few cents). `make bench-tts args='--provider deepgram --runs 10'`: its latency.

### Kitten TTS (Phase 3 onwards)

Nothing to configure. The Docker image contains the model (Kitten TTS 2 nano, English, at a pinned revision), and the backend loads it in the background at startup (log line `tts_ready`). Defaults: voice `Iris`, 2 ONNX threads per synthesis, 3 s timeout. Override them with `KITTEN_VOICE`, `TTS_THREADS` and `TTS_TIMEOUT_S`. Leave `KITTEN_MODEL_PATH` empty to use the bundled model.

- `make tts-say TEXT="Hello, am I speaking with Priya Iyer?" PHONE=1`: speak a line, save it to `backend/artifacts/tts/` and play it, plus the 8 kHz phone version with `PHONE=1`. It also prints the text exactly as the model reads it.
- Mispronounced name or company: add a respelling to `backend/app/voice/pronunciations.yaml`, then try `make tts-say` again. `tts-say` always reads the current file; the backend reads it once at startup (`docker compose restart backend`).
- `make test-tts`: tests against the real model (about 2 minutes). `make test` skips them.
- `make bench-tts args='--threads 1,2,4'`: the latency benchmark in [benchmarks/tts.md](benchmarks/tts.md).
- Without Docker: `make tts-model` downloads the model to `backend/models/` (gitignored) for the local venv.

### Speech-to-text: Deepgram streaming (Phase 4 onwards)

Uses the same `DEEPGRAM_API_KEY`. One WebSocket stream per call (`backend/app/providers/stt/`); finished utterances come from `voice/utterance.py`. Defaults (`DEEPGRAM_STT_*` in `.env.example`) come from [benchmarks/stt.md](benchmarks/stt.md). Cost: Nova-3 English streaming is $0.0048 per minute of audio sent (Deepgram's pay-as-you-go price on 2026-11-18), about $0.03 for a 5-minute call. The stream is billed while it's open, so it's closed as soon as a call ends.

The microphone, `say` and recording tools run **on the Mac host** (Docker can't reach the microphone), using `backend/.venv` (`make venv` installs `sounddevice`). They read the root `.env` themselves.

- `make stt-clips`: generate the synthetic test set (macOS voices Rishi, Tara and Aman, with pauses and fan/TV/traffic noise) into `backend/artifacts/stt-audio/synthetic/`. Not committed.
- `make stt-file FILE=artifacts/stt-audio/synthetic/rishi/c07_multi_answer.wav RATE=8000`: stream one file like a live call and watch partials, finals and latency (in Docker). `args='--dump-events out.json'` saves Deepgram's raw messages, sanitized, as a test fixture.
- `make stt-mic [RATE=8000]`: talk and watch the live transcript.
- `make voice-loop`: talk to the screening agent through STT (headphones; `SPEAK=1` speaks its replies). `make voice-loop SCRIPT=s14_happy_path RATE=8000` plays a scenario's lines with `say`, turn by turn, with no microphone needed.
- `make stt-record SPEAKER=name`: record real test clips line by line (only with the speaker's consent; they stay in `backend/artifacts/stt-audio/real/`). Then `make bench-stt args='--sets real'`.
- `make test-stt`: live STT tests (about 1.5 minutes, a few cents; needs `make stt-clips` first). `make bench-stt`: the full benchmark (about 10 minutes, about $0.50).

### Telephony: Exotel (Phase 5 onwards)

Protocol, verified facts and the test-call log: [telephony.md](telephony.md).

1. `.env`: `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_ACCOUNT_SID`, `EXOTEL_SUBDOMAIN` (`api.exotel.com` for a Singapore-region account, `api.in.exotel.com` for Mumbai), `EXOTEL_CALLER_ID` (the ExoPhone), `EXOTEL_APP_ID` (the flow's id).
2. Public URL: `make tunnel` (Cloudflare quick tunnel; `brew install cloudflared`). Put its `https://…trycloudflare.com` URL in `PUBLIC_BACKEND_URL`, then `docker compose up -d backend worker` (containers read `.env` only when created). The URL changes every time the tunnel restarts.
3. `make exotel-urls` prints the Voicebot URL. In Exotel's App Bazaar the flow is exactly **Voicebot** (that URL) → **Hangup**.
4. Test call to a consenting tester whose number is verified in the Exotel dashboard (trial accounts without KYC can't call anyone else): `make test-call phone=+9198XXXXXXXX` runs a real screening conversation (Phase 6) and prints the transcript, the stored answers, the summary and the per-turn latency table. `mode=full` (clip, echo, stop test, backend hangs up) and `mode=listen` (clip, then you hang up) are the Phase 5 line checks. Test calls skip the calling window. With `TELEPHONY_CAPTURE_DIR` set, each call writes `backend/artifacts/calls/<attempt>_in.wav` and `_stream.json` (gitignored; delete after review).
5. From the UI: open a candidate and press **Call now** (the API refuses outside the calling window, without consent, or while the voice is still loading).

Voice conversation settings (VAD, barge-in, silence, time limits): `.env.example` and [voice-pipeline.md](voice-pipeline.md). The post-call summary is written by the worker's `finalize_call` job a few seconds after the call.

The worker places calls (`initiate_call`, one Redis slot per `MAX_CONCURRENT_CALLS`) and checks stuck calls with Exotel every 2 minutes.

Never commit `.env`. Run `make check-secrets` (needs `brew install gitleaks`) before committing.

## Common problems

| Symptom | Fix |
|---|---|
| `Invalid configuration… APP_SECRET_KEY: is required` | Run `make env`, or set a 32+ character value in `.env` |
| `/health/ready` shows `worker: error` | Worker not running or just started; check `docker compose logs worker` (heartbeat every 30 s) |
| Agent or eval: `LLMConfigError: OPENAI_API_KEY and OPENAI_MODEL must be set` | Fill them in `.env`, then `make up` (containers read `.env` only when created) |
| OpenAI `400 Unsupported value: 'minimal'` | 5.x/6.x models accept `OPENAI_REASONING_EFFORT=none`, not `minimal`; non-reasoning models (e.g. gpt-4.1-mini) need it empty |
| Log shows `tts_component_unavailable component=primary` | Deepgram was unreachable or rejected the key at startup; Kitten speaks, and Deepgram is retried every 60 s. Check `DEEPGRAM_API_KEY` |
| Log shows `tts_fallback_used` | A sentence went to Kitten (Deepgram error or > 1.5 s to first audio); see the `error=` field |
| Log shows `tts_load_failed … no Kitten model` | The backend runs outside the image without the model: `make tts-model`, or set `KITTEN_MODEL_PATH` |
| `tts_load_failed … unknown KITTEN_VOICE` | Use an English voice name from the error message (default `Iris`) |
| `STTConfigError: Deepgram rejected the API key` | `DEEPGRAM_API_KEY` is wrong or revoked; STT fails at session start, never mid-call |
| Log shows `stt_disconnected` then `stt_connected` | The stream dropped and reconnected; up to 2 s of audio was buffered meanwhile (`stt_audio_dropped` if more) |
| `make stt-mic` / `voice-loop`: `PortAudioError` or no audio | Allow the terminal app microphone access (System Settings → Privacy & Security → Microphone), then restart the terminal |
| `make test-stt` skips everything | Generate the clips first: `make stt-clips` (on the host) |
| Test call: HTTP 400 "Invalid 'StatusCallbackEvents' specified" | Don't send `StatusCallbackEvents` (connect-to-flow rejects it). If you changed worker code, check the worker really restarted (`docker compose logs worker`) |
| Test call: HTTP 403 "not yet KYC compliant" | The number isn't verified in the Exotel dashboard (trial without KYC) |
| Phone rings but is silent, log shows `stream_unknown_call` or nothing | The Voicebot URL in the flow is stale (tunnel restarted): `make exotel-urls`, update the applet |
| Log shows `stream_media_format_mismatch` | `TELEPHONY_*` settings differ from what Exotel announced in the start message |
| Worker ignores code changes | Fixed in Phase 5 (`watchfiles` restarts the process); recreate it with `docker compose up -d worker` |
| Port already in use | Stop the other service or change the host port in `docker-compose.yml` |
| Frontend shows "Backend unreachable" | Backend container not up; `docker compose logs backend` |
| Every change in the UI fails with "Request origin not allowed" | `FRONTEND_ORIGIN` in `.env` doesn't match the URL in the browser (e.g. port 3010 vs 3000); fix it and restart the backend |
| Can't log in / no account | `make create-user email=… name=…` (running it again resets the password) |
