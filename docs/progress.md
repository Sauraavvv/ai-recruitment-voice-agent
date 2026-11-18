# Progress

## Phase 1 decisions (agreed 2026-11-18)

- Phone numbers are unique across all jobs: one record per person; re-imports are flagged as duplicates.
- Deleting a candidate is a soft delete: hidden and never called, history kept.
- Consent: the recruiter ticks an attestation checkbox per import; calls are blocked without it.
- Import formats: `.csv` and `.xlsx` only.

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
