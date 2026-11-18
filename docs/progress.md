# Progress

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
