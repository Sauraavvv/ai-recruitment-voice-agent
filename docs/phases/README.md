# Phase plans: AI Recruitment Voice Calling Agent

Detailed execution plans for the 11 development phases in [plan.md](../../plan.md) §10.

plan.md remains the source of truth for **what** to build. These files cover **how** to build each phase: the order of work, the files it produces, design details plan.md leaves open, and how the phase is verified before the next one starts.

## Files

| Phase | Plan | Outcome | Size | Risk |
|---|---|---|---|---|
| 0 | [Repository & architecture setup](phase-00-repository-setup.md) | Frontend, backend, Postgres, Redis and worker run via Docker Compose with health checks | S | Low |
| 1 | [Database & candidate management](phase-01-database-candidates.md) | Schema + migrations, candidate/job CRUD, Excel/CSV import with preview, recruiter login | M | Low |
| 2 | [AI screening agent (text)](phase-02-ai-screening-agent.md) | Stateful agent passes scripted text screenings against the real OpenAI API | L | Medium |
| 3 | [Kitten TTS](phase-03-kitten-tts.md) | Warm TTS service with known output format, chunker, text normalizer, benchmarks | M | Medium |
| 4 | [Deepgram STT](phase-04-deepgram-stt.md) | Per-session streaming STT, utterance detection, transcripts flowing into the agent | M | Medium |
| 5 | [Exotel telephony PoC](phase-05-telephony-poc.md) | Real outbound call with two-way audio and webhook-driven status; **go/no-go gate** | L | **High** |
| 6 | [Complete voice conversation](phase-06-voice-conversation.md) | Real screening calls end to end: turn-taking, barge-in, transcripts | XL | **High** |
| 7 | [Structured data & Google Sheets](phase-07-data-and-sheets.md) | Final extraction, summary, Postgres persistence, idempotent Sheets sync | L | Medium |
| 8 | [Dashboard & call controls](phase-08-dashboard.md) | Recruiter UI on real data: stats, call controls, transcripts, settings | L | Low–Medium |
| 9 | [Automatic retry](phase-09-auto-retry.md) | Retry and callback scheduling with limits, calling window, opt-out enforcement | M | Medium |
| 10 | [Testing & deployment](phase-10-testing-deployment.md) | Test matrix with real calls, HTTPS deployment, docs, demo, Definition of Done | L | Medium |

Sizes are relative (S < M < L < XL), not calendar estimates.

## Order and dependencies

```text
P0 ─► P1 ─► P2 ─► P3 ─► P4 ─► P5 ─► P6 ─► P7 ─► P8 ─► P9 ─► P10
 │                             ▲
 └── Exotel account track ─────┘   (non-code, starts in P0)
```

- Phases run in plan order. P3 and P4 don't depend on each other; P4's last task needs the P2 agent.
- P5 needs P1 (`call_attempts`) and uses a P3 clip for its audio test.
- The Google Sheets client in P7 (tasks T5–T10) depends only on P1 and can be built early if work is blocked waiting on Exotel.

## Start these on day one

1. **Exotel account.** KYC, virtual number (ExoPhone) approval, outbound calling and bidirectional audio streaming enablement are outside your control and can take days. P5 can't start without them, and if streaming can't be enabled the telephony choice must be revisited (plan.md Module E). Tracked in P0-T13.
2. **Other credentials** (plan.md §16): OpenAI with API billing (P2), Deepgram (P4), Google service account (P7), public HTTPS host (P5).
3. **Test participants.** Three or more people who agree to receive test calls on their own phones (P5, P6, P10). Calls go only to people who have agreed.

## Conventions used in the phase files

- Task IDs look like `P3-T4`; acceptance-criteria IDs like `P3-AC2`. Use them in commits, PRs and phase reports.
- **[Proposed]**: goes beyond plan.md (a table, column, endpoint or rule that plan.md implies but doesn't spell out). Accept or reject before the phase starts.
- **[Verify]**: a fact about a third-party service. Confirm it against the provider's current official documentation before code depends on it. Values given next to it are hypotheses, not facts to hardcode.
- **[Decision]**: needs the user's call. Every phase lists these under "Open decisions" with a recommended default.
- "(added)" on a task or acceptance criterion means it isn't in plan.md but is needed to meet plan.md's goals.

## Cross-phase technical decisions

Recommended defaults; each is confirmed in the phase named.

| Topic | Recommendation | Reason | Phase |
|---|---|---|---|
| Background worker | ARQ | Async-native like FastAPI, Redis-backed, built-in cron covers the retry scheduler so APScheduler isn't needed. Check its maintenance status first; Celery is plan.md's alternative. | P0 |
| Python version | 3.12 | `audioop` (used for μ-law/PCM helpers) is removed in 3.13; ONNX Runtime and TTS wheels are most reliable on 3.12. | P0 |
| Repo root | This folder holds `frontend/`, `backend/`, `docs/` directly (no extra `ai-recruitment-agent/` level) | Simpler paths. The space in `project 2` must be quoted in scripts. | P0 |
| Where live audio runs | In the FastAPI backend process, one Uvicorn worker for the MVP | The telephony WebSocket lands on the API; one process keeps call sessions and the warm TTS model together. The worker only dials and runs background jobs. | P0, P6 |
| CPU-heavy inference | Dedicated executor (thread or process) for Kitten TTS | plan.md §12: don't block the event loop; 20 ms audio pacing needs a responsive loop. | P3 |
| Agent control | Python state machine owns field status, question order and completion; the LLM extracts and phrases | Makes "don't repeat questions" and "don't invent answers" enforceable and testable. | P2 |
| Compensation unit | Lakhs per annum (LPA) as a float, candidate's raw words kept alongside **[Decision]** | Matches how Indian candidates state CTC. | P2 |
| Time | Store UTC; display and calling window in Asia/Kolkata | plan.md §5 requires UTC storage. | P1 |
| API envelope | `{"data": …, "meta": …}` on success; `{"error": {"code", "message", "details"}}` on failure | plan.md §6 "consistent JSON response formats". | P0 |
| Frontend → backend | Next.js rewrites proxy `/api/*` to the backend | Same-origin cookies, no browser CORS, backend URL never in client code. | P0 |
| Authentication | Recruiter email + password, server-side sessions in Redis, HttpOnly cookie | plan.md §12 requires it, and it must exist before P5 puts the backend on a public URL. | P1 |
| Live dashboard updates | Polling with TanStack Query | Enough for 1–2 concurrent calls; SSE can come later. | P8 |
| Sheets reliability | Transactional outbox: a `sync_logs` row is written in the same DB transaction as the data change | A Sheets or Redis outage can't lose a sync (plan.md §3). | P7 |

## Proposed additions to plan.md's schema and API

| Addition | Why | Phase |
|---|---|---|
| `/health`, `/health/ready` | Phase 0 health checks | P0 |
| `users` table; `/api/v1/auth/login`, `/logout`, `/me` | Dashboard authentication (plan.md §12) | P1 |
| `import_batches` table | `GET /candidates/import/{id}` needs a stored preview and report | P1 |
| `PUT /candidates/import/{id}/mapping`, `POST /candidates/import/{id}/confirm` | Preview → confirm flow (plan.md Module A) | P1 |
| `/api/v1/jobs` CRUD + activate | Job configuration (Module B) has no endpoints in §6 | P1 |
| `candidates`: `applied_role`, `recruiter_notes`, `consent_source`, `consent_at`, `deleted_at`, `screening_field_meta` | Import columns with no home in §5; consent gate (plan.md §15); safe delete; per-field status | P1 |
| `call_attempts`: `provider_status`, `attempt_type`, `end_reason`, `stream_id`; one-live-attempt-per-candidate index | Separate raw/internal status; retries vs callbacks; duplicate-call prevention | P5 |
| `webhook_events` table | Idempotent webhook processing and audit (plan.md §3, §12) | P5 |
| `conversations.finalized_at`; `sync_logs.attempts`, `next_attempt_at` | Idempotent finalization; sync retry with backoff | P7 |
| `app_settings` table; `GET/PATCH /api/v1/settings`; `GET /api/v1/settings/status` | Settings page (plan.md §7 page 5): retry config, org name, agent intro, provider status, global pause | P8 |
| `POST /calls/{id}/hangup`, `GET /calls/{id}/recording` | Safety control for live calls; authenticated recording access | P8 |

## Rules that apply to every phase (from plan.md)

- Real calls only. Never fake a provider integration or mark it working before a real test succeeds.
- PostgreSQL is the source of truth; Google Sheets is a downstream copy.
- Secrets stay on the backend and never appear in logs, the database or the frontend.
- Test doubles live only under `tests/`; production code paths always use the real providers.
- Calls go only to candidates with recorded consent, inside the calling window, and never to anyone who opted out.
- Every phase follows plan.md §15's workflow: explain → list files → implement → format and type-check → test → update docs → report → list anything needing credentials or manual provider setup.
- Stop after each phase for user review before starting the next.

## Phase exit report

Copy this into the PR or `docs/progress.md` at the end of each phase.

```markdown
## Phase N exit report
- Implemented:
- Files created / changed:
- Tests run (command → result):
- Acceptance criteria:
  - PN-AC1 ✅ evidence: …
  - PN-AC2 ❌ reason / plan: …
- Deferred or not done:
- Needs credentials or manual provider configuration:
- Risks or surprises discovered:
- Decisions made (and by whom):
```
