# Architecture

Full blueprint: [plan.md](../plan.md). Phase-by-phase plans: [docs/phases/](phases/README.md).

## Processes

| Process | Runs | Owns |
|---|---|---|
| **frontend** | Next.js (`frontend/`) | Recruiter UI. Proxies `/api/*` and `/health/*` to the backend so the browser only talks to one origin. Holds no secrets. |
| **backend** | FastAPI, one Uvicorn worker (`backend/app/main.py`) | REST API, webhooks, and (from Phase 5) the live-audio WebSockets with their per-call sessions and the warm TTS model. |
| **worker** | ARQ (`backend/app/workers/settings.py`) | Background jobs: dialling calls, post-call finalization, Google Sheets sync, retry scheduling. Writes a heartbeat to Redis every 30 s. |
| **postgres** | PostgreSQL 16 | Source of truth for all data. |
| **redis** | Redis 7 (append-only) | Job queue, worker heartbeat, sessions, concurrency slots. |

Live call audio is handled in the backend process rather than the worker because the telephony provider's WebSocket connects to the API, and the call session and TTS model need to live in the same process.

## Data flow

```text
                    RECRUITER
                        │
                        ▼
              NEXT.JS DASHBOARD ── /api/* proxy ──► FASTAPI BACKEND
                                                     │   │      │
                                   ┌─────────────────┘   │      └──────────────┐
                                   ▼                     ▼                     ▼
                              POSTGRESQL            REDIS QUEUE          GOOGLE SHEETS
                           (source of truth)            │               (copy, written
                                   ▲                    ▼                by the worker)
                                   │               CALL WORKER ──► EXOTEL ──► CANDIDATE PHONE
                                   │                                              │
                                   │                                     audio WebSocket
                                   │                                              ▼
                                   │      BACKEND voice session: VAD → STT (Deepgram) → agent (OpenAI)
                                   └──────────────────────────── → Kitten TTS → audio back to Exotel
```

## Backend module boundaries

| Package | Responsibility | Must not |
|---|---|---|
| `api/` | HTTP routes, request/response models, auth | Contain SQL or business rules |
| `services/` | Business rules and transactions | Know about HTTP |
| `repositories/` | Database queries | Contain business rules |
| `database/` | Engine, sessions, models, migrations | |
| `agent/` | Screening conversation state and logic | Import audio or telephony code |
| `voice/` | Audio pipeline, turn-taking, interruption | Contain provider-specific code |
| `providers/` | Adapters for OpenAI, Deepgram, Kitten, Exotel behind interfaces | Leak provider types to other packages |
| `workers/` | Background job entry points | |

## Principles (from plan.md §3)

- The frontend never calls the telephony provider, OpenAI or Deepgram directly; credentials stay on the backend.
- The worker initiates outbound calls; webhooks update call status; WebSocket handlers process live audio.
- Every call attempt has its own id and links to a persistent candidate record.
- Database writes are idempotent.
- Google Sheets is synced after the database transaction commits; a Sheets failure never loses data.

## Conventions

- Timestamps stored in UTC; shown in Asia/Kolkata.
- API responses use the envelope in [api.md](api.md).
- Logs are structured (JSON in production) and carry `request_id`, and later `candidate_id`, `call_attempt_id`, `provider_call_id`. Secrets are redacted and phone numbers masked.
