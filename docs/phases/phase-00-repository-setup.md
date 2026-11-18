# Phase 0: Repository and architecture setup

| | |
|---|---|
| Source | plan.md §10 Phase 0, §2, §8, §9, §15 "First task" |
| Depends on | Nothing |
| Unlocks | Every later phase |
| Size / risk | S / Low |

## 1. Goal

A runnable, empty skeleton: Next.js frontend, FastAPI backend, PostgreSQL, Redis and a background worker start with one command, validate their configuration and report health. No business features yet.

## 2. Entry criteria

- plan.md read; the [cross-phase decisions](README.md#cross-phase-technical-decisions) reviewed.
- Installed locally: Docker Desktop (Compose v2), Python 3.12, current Active LTS Node.js, git.

## 3. Scope

- **In:** tasks P0-T1 to P0-T13 below.
- **Out:** database models and migrations (P1), authentication (P1), any provider SDK (P2 onwards).

## 4. Deliverables

```text
.
├── .gitignore  .env.example  docker-compose.yml  docker-compose.override.yml  Makefile  README.md
├── backend/
│   ├── Dockerfile  requirements.txt  requirements-dev.txt  pyproject.toml
│   └── app/
│       ├── main.py                 # create_app(), lifespan, routers, error handlers
│       ├── config.py               # pydantic-settings, startup validation
│       ├── api/health.py           # /health, /health/ready
│       ├── api/v1/__init__.py      # v1 router (empty for now)
│       ├── database/connection.py
│       ├── utils/redis.py
│       ├── utils/log.py            # structlog setup, redaction, phone masking
│       ├── workers/settings.py     # ARQ WorkerSettings + heartbeat cron
│       └── tests/  conftest.py  test_health.py  test_config.py
├── frontend/                       # create-next-app output + Dockerfile, lib/api.ts, app/page.tsx
└── docs/  architecture.md  setup.md  telephony.md  api.md
```

The remaining folders from plan.md §8 are created as empty packages (`__init__.py` only). No placeholder classes; each module arrives with its phase.

## 5. Tasks

### P0-T1 Inspect the repository and environment

- The folder holds `plan.md` and `docs/phases/`. Don't move or rename `plan.md` without asking.
- Record in `docs/setup.md`: `python3 --version`, `node --version`, `npm --version`, `docker --version`, `docker compose version`, and CPU architecture (`uname -m`). Apple Silicon (arm64) vs linux/amd64 matters for ONNX wheels in P3.
- Initialize git (`git init -b main`) after the user confirms.
- The path contains a space (`project 2`). Quote paths in Makefile and shell scripts; use relative paths in Compose.

### P0-T2 Create the directory structure

- Lay out plan.md §8 at the repo root (no `ai-recruitment-agent/` wrapper).
- Python packages get `__init__.py`. Don't create empty provider or service classes yet.

### P0-T3 Initialize Next.js with TypeScript

- `npx create-next-app@latest frontend --typescript --tailwind --eslint --app --no-src-dir --import-alias "@/*"` (no `src/` folder, to match plan.md §8).
- Add Prettier with `prettier-plugin-tailwindcss`. Scripts: `dev`, `build`, `lint`, `typecheck` (`tsc --noEmit`), `format`.
- `next.config`: rewrites `/api/:path*` and `/health/:path*` to `${BACKEND_INTERNAL_URL}`. This is a server-side variable; never prefix it with `NEXT_PUBLIC_`.
- `app/page.tsx`: a system status page that calls `/health/ready` and shows each component's state. It shows live data only.
- `lib/api.ts`: a small fetch wrapper that unwraps `{data}` and throws typed errors from `{error}`.
- Frontend Dockerfile: multi-stage (deps → build → `next start`). Dev mode (`next dev`, bind mount) comes from the override file.

### P0-T4 Initialize FastAPI

- `create_app()` factory. `lifespan` opens and closes the DB engine and Redis pool, and logs a startup summary of configuration **names** (never values).
- Routers: `/health*` at the root; everything else under `/api/v1`.
- Envelope helpers and exception handlers:
  - `RequestValidationError` → 422 `{"error": {"code": "validation_error", "message": …, "details": [...]}}`
  - `HTTPException` → mapped code
  - Unhandled → 500 with the request id and no stack trace in the body
- Middleware: request id (`X-Request-ID` in and out) and access log with duration.
- CORS: allow only `FRONTEND_ORIGIN`. Browser traffic normally goes through the Next.js proxy.
- Dependencies, pinned exactly: fastapi, uvicorn[standard], pydantic v2, pydantic-settings, sqlalchemy[asyncio] 2.x, asyncpg, alembic, redis, arq, structlog, httpx. Dev: pytest, pytest-asyncio, ruff, mypy.
- `pyproject.toml`: ruff (lint + format), mypy (strict for `app/`), pytest (`asyncio_mode = "auto"`).
- Backend Dockerfile: `python:3.12-slim`, non-root user, `pip install --no-cache-dir -r requirements.txt`. TTS system packages are added in P3.

### P0-T5 Docker Compose

| Service | Image / build | Notes |
|---|---|---|
| postgres | `postgres:16-alpine` | volume `pgdata`; healthcheck `pg_isready`; host port 5433 → 5432 to avoid a clash with a local Postgres |
| redis | `redis:7-alpine` | `--appendonly yes` so queued jobs survive restarts; healthcheck `redis-cli ping`; host port 6380 |
| backend | `./backend` | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1`; waits for healthy postgres and redis |
| worker | `./backend` (same image) | `arq app.workers.settings.WorkerSettings` |
| frontend | `./frontend` | port 3000 |

- `docker-compose.override.yml` (dev only): bind mounts, `--reload`, `next dev`. Production Compose comes in P10.
- `env_file: .env` for backend and worker only. The frontend gets only `BACKEND_INTERNAL_URL`.

### P0-T6 Configure PostgreSQL

- `database/connection.py`: async engine from `DATABASE_URL` (asyncpg), `async_sessionmaker(expire_on_commit=False)`, a `get_session` dependency, and `check_database()` running `SELECT 1` with a 2 s timeout.
- Session timezone UTC (`connect_args={"server_settings": {"timezone": "UTC"}}`).
- Alembic is set up in P1 when the first model exists.

### P0-T7 Configure Redis and the worker

- `utils/redis.py`: shared `redis.asyncio` client from `REDIS_URL`, key prefix `rcai:`, `check_redis()` = PING with a timeout.
- `workers/settings.py`: ARQ `WorkerSettings` with Redis settings, an empty `functions` list and a `heartbeat` cron (every 30 s) that writes `rcai:worker:heartbeat` with a 90 s TTL.
- **[Verify]** ARQ's current maintenance status and compatibility with the current redis-py. If it's a problem, switch to Celery now (plan.md allows either). Later phases only assume "a Redis-backed job queue with cron jobs and job-id de-duplication".

### P0-T8 Environment validation

- `config.py`: `Settings(BaseSettings)` with nested sections: core, database, redis, openai, deepgram, exotel, kitten, google, calling.
- Required at startup: `APP_ENV`, `APP_SECRET_KEY` (≥ 32 chars), `DATABASE_URL`, `REDIS_URL`. If any is missing or invalid, the app refuses to start and prints the variable **names**.
- Provider sections are optional until their phase. Each exposes `is_configured`; features needing an unconfigured provider fail with a clear error, and the settings page (P8) shows "not configured".
- Keys and tokens are `SecretStr`, so they're masked in `repr()` and logs.
- `.env.example` = plan.md §9 list plus `LOG_LEVEL`, `FRONTEND_ORIGIN`, `FRONTEND_URL`, `BACKEND_INTERNAL_URL`, `APP_TIMEZONE=Asia/Kolkata`. Exotel variable names stay as in plan.md §9 and are re-checked in P5 **[Verify]**.
- When `APP_ENV=production`, also reject a weak or default `APP_SECRET_KEY`, debug mode, and a non-HTTPS `PUBLIC_BACKEND_URL`.

### P0-T9 Health endpoints

- `GET /health` (liveness, no dependency checks):
  `{"data": {"status": "ok", "version": "<git sha or 0.0.0>"}}`
- `GET /health/ready` (readiness) checks database, Redis and worker heartbeat concurrently, each with a 2 s timeout:
  - all ok → 200 `{"data": {"status": "ok", "components": {"database": "ok", "redis": "ok", "worker": "ok"}}}`
  - any failure → 503 with the same shape, failing components set to `"error"` plus a short message (no connection strings).
- Provider connectivity (OpenAI, Deepgram, Exotel, Sheets) is **not** part of readiness. It belongs to `/api/v1/settings/status` (P8), so a provider outage never restarts the backend.

### P0-T10 Architecture documentation

- `docs/architecture.md`: plan.md §3 diagram; process model (frontend; backend including live-audio WebSockets; worker; Postgres; Redis); which process owns what; Postgres as source of truth; module boundaries from plan.md §8; architecture principles from plan.md §3.
- `docs/setup.md`: prerequisites, `cp .env.example .env`, `make up`, URLs, common problems.
- `docs/api.md`: envelope format, error codes, versioning, pagination (`page`, `page_size`, `meta.total`).
- `docs/telephony.md`: the Exotel enablement tracker from P0-T13; completed in P5.

### P0-T11 Logging foundation (added)

- structlog: JSON in production, readable console output in dev. `request_id` bound per request; contextvars ready for `candidate_id`, `call_attempt_id`, `provider_call_id` (plan.md §12 observability).
- Redaction processor drops values whose keys match `key|token|secret|password|authorization`.
- `mask_phone("+919876543210")` → `"+91******3210"`. Logs carry IDs and masked phones only, never full candidate details.

### P0-T12 Developer tooling (added)

- Makefile targets: `up`, `down`, `logs`, `test`, `lint`, `fmt`, `typecheck`, `shell-db`.
- Secret scanning: a `gitleaks` pre-commit hook, or at least `make check-secrets` before each commit.
- `.gitignore`: `.env*` except `.env.example`, `secrets/`, `artifacts/`, `node_modules/`, `.next/`, `__pycache__/`, `.venv/`, model files and caches (`*.onnx`), audio recordings (`*.wav` outside test fixtures).

### P0-T13 Start the Exotel enablement track (non-code, added)

Raise these with Exotel now and record answers, dates and ticket numbers in `docs/telephony.md`:

1. Account activation and KYC; ExoPhone (virtual number) for outbound caller ID.
2. Does our account and plan support **bidirectional real-time audio streaming** on outbound calls (Exotel's Voicebot/stream applet)? **[Verify]**
3. Stream audio format: encoding, sample rate, channels, chunk-size rules.
4. Can we send audio back on the stream, and are playback-control messages (clear/mark) supported? P6 barge-in depends on this.
5. How to attach our own identifier (call attempt ID) to a call so it comes back in webhooks and the stream start message.
6. Status callback payload and the full list of call statuses.
7. Concurrent-call limit on the account; per-minute cost.
8. DND/NCPR scrubbing and calling-hour rules for recruitment calls.
9. Webhook authentication options or source IP ranges.
10. Call recording availability and how recording URLs are accessed.

If the answer to question 2 is "no" or "not on your plan", tell the user immediately. plan.md Module E says to stop and resolve this before the voice pipeline is built.

## 6. Tests

- `test_health.py`: liveness 200; readiness 200 with real Postgres and Redis (Compose); readiness 503 when the DB check fails (dependency override).
- `test_config.py`: a missing core variable → startup error naming it; secret values absent from `repr(settings)` and from the logged startup summary; production rules reject a weak secret.
- Frontend: `npm run lint && npm run typecheck && npm run build` pass.

## 7. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P0-AC1 | Frontend starts successfully | `make up`; http://localhost:3000 renders the status page |
| P0-AC2 | Backend starts successfully | http://localhost:8000/health returns 200; `/docs` loads |
| P0-AC3 | PostgreSQL connection works | `/health/ready` → database ok; `docker compose stop postgres` → 503 with database error; start again → ok |
| P0-AC4 | Redis connection works | Same test with redis |
| P0-AC5 | Health endpoints return valid responses | `pytest app/tests/test_health.py` passes; shapes match P0-T9 |
| P0-AC6 | No secrets are committed | `git check-ignore .env` succeeds; `.env.example` values empty; gitleaks scan clean |
| P0-AC7 (added) | Worker runs | `/health/ready` → worker ok; stop the worker → worker error within 90 s |
| P0-AC8 (added) | Quality gates run | `make lint typecheck test` pass |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Exotel enablement is slow | Started here and tracked; P1–P4 don't need it |
| Port clashes with a local Postgres/Redis | Host ports 5433 and 6380 |
| Apple Silicon vs linux/amd64 differences (ONNX in P3) | Build and run the backend image on the target architecture early; note it in setup.md |
| Space in the folder path breaks scripts | Quote paths; run every `make` target from the repo root once |

## 9. Manual setup and credentials

None needed to finish this phase. Start now: Exotel (P0-T13) and an OpenAI account with API billing (needed in P2).

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| ARQ or Celery | ARQ, after the P0-T7 check |
| Initialize git now | Yes |
| Dependency locking | `uv pip compile` (or `pip-compile`) producing `requirements.txt`, keeping plan.md's file name |

## 11. Exit

Write the [phase exit report](README.md#phase-exit-report). plan.md §15: don't start Phase 1 until the user has reviewed Phase 0.
