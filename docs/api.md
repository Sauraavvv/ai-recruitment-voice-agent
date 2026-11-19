# API conventions

Interactive reference (development only): http://localhost:8000/docs

## Versioning

Feature endpoints live under `/api/v1`. Health endpoints are at the root (`/health`, `/health/ready`) for infrastructure probes.

## Response envelope

Success:

```json
{ "data": { ... }, "meta": { "page": 1, "page_size": 25, "total": 120 } }
```

`meta` appears only where it means something (e.g. paginated lists).

Error:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [ ... ],
    "request_id": "3f2c9a..."
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 401 | `not_authenticated` | No valid session cookie |
| 401 | `invalid_credentials` | Wrong email or password at login |
| 403 | `csrf_failed` | State-changing request whose `Origin` (or `Referer`) isn't `FRONTEND_ORIGIN` |
| 410 | `import_expired` | Import preview older than 24 hours |
| 429 | `too_many_attempts` | More than 5 login attempts per minute for one IP + email |
| 404 | `not_found` | Unknown route or resource |
| 409 | e.g. `duplicate_phone` | Conflicts with existing data |
| 422 | `validation_error` | Request body or parameters invalid; `details` lists fields |
| 500 | `internal_error` | Unexpected error; details are in the server log under `request_id` |
| 503 | — | `/health/ready` when a dependency is down (body still uses `data`) |

## Request ids

Every HTTP response has an `X-Request-ID` header. Send your own (letters, digits, `.`, `_`, `-`, max 64 chars) to correlate logs; otherwise one is generated.

## Pagination

Query parameters `page` (1-based) and `page_size` (max 100). Totals in `meta.total`.

## Authentication

Every `/api/v1` route needs a logged-in recruiter except `POST /api/v1/auth/login`. Login sets an `HttpOnly; SameSite=Lax` cookie `rcai_session` (`Secure` in production) backed by a Redis session with a 12-hour sliding expiry. There is no public sign-up; accounts are created with `make create-user`.

`POST`, `PUT`, `PATCH` and `DELETE` requests must carry an `Origin` header (or, failing that, a `Referer`) equal to `FRONTEND_ORIGIN`. Browsers do this automatically through the Next.js proxy; scripts using curl must add `-H "Origin: http://localhost:3000"`.

## Endpoints

The full schema is at `/docs` and `/openapi.json`; the frontend's types are generated from it with `make types`.

### Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/auth/login` | `{email, password}` → user; sets the session cookie |
| POST | `/api/v1/auth/logout` | Ends the session |
| GET | `/api/v1/auth/me` | Current user |

### Candidates

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/candidates` | Requires `consent_attested: true`. Phone normalized to E.164. `job_id` defaults to the active job. 409 `duplicate_phone` with `details.existing_candidate_id` |
| GET | `/api/v1/candidates` | `q` (name/phone/email), `screening_status`, `job_id`, `interested`, `sort` (`created_at`, `name`, `updated_at`, prefix `-` for descending; default `-created_at`), `page`, `page_size` |
| GET | `/api/v1/candidates/{id}` | Profile and screening fields |
| PATCH | `/api/v1/candidates/{id}` | Partial update; `null` clears an optional field. Changing the phone re-checks duplicates. `opted_out` can't go back to `false` (409 `opt_out_irreversible`) |
| DELETE | `/api/v1/candidates/{id}` | Soft delete. The phone stays reserved, so re-adding it returns 409 with `details.deleted: true` |

### Candidate import

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/candidates/import` | Multipart `file` (.csv/.xlsx, ≤ 5 MB, ≤ 1,000 rows) and optional `job_id`. Returns the preview: headers, auto-mapping, per-row status and the report. Nothing is saved yet |
| GET | `/api/v1/candidates/import/{id}` | Preview (re-validated) or, once confirmed, the final report |
| PUT | `/api/v1/candidates/import/{id}/mapping` | `{column_mapping: {field: column_index or null}}`; re-validates |
| POST | `/api/v1/candidates/import/{id}/confirm` | `{consent_attested: true}`; inserts the valid rows |

Row status: `valid`, `invalid`, `duplicate_in_file` (the first row with a phone wins) or `duplicate_existing` (with `existing_candidate_id`; the existing record is never changed). Report:

```json
{
  "total_rows": 10, "valid_candidates": 8, "duplicate_candidates": 1,
  "duplicates_in_file": 1, "duplicates_existing": 0,
  "invalid_candidates": 1, "imported_candidates": 8,
  "errors": [{"row": 11, "field": "phone", "message": "Phone number is too short"}]
}
```

`row` is the spreadsheet row number (the header is row 1). Previews expire after 24 hours; the worker then deletes their stored rows.

### Jobs

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/jobs` | All jobs, active first |
| GET | `/api/v1/jobs/active` | The active job, or `null` |
| GET | `/api/v1/jobs/default-screening-questions` | The ten standard questions, with the recruiters' wording |
| PUT | `/api/v1/jobs/default-screening-questions` | Change wording / required of standard questions (`{questions:[{key,prompt,required}]}`); keys, types and order are fixed. Jobs that ask exactly the old defaults (any order) are updated too; returns `jobs_updated` |
| DELETE | `/api/v1/jobs/default-screening-questions` | Restore the original wording (same propagation) |
| POST | `/api/v1/jobs` | Questions default to the standard ten. The first job becomes active |
| GET / PATCH | `/api/v1/jobs/{id}` | `job_description` and `agent_instructions` are limited to 4,000 characters |
| POST | `/api/v1/jobs/{id}/activate` | Makes this the only active job |

`screening_questions` is an ordered list of `{key, prompt, required, type: string|number|boolean, unit}`. The ten standard keys (`current_location` … `interview_availability`) keep their fixed types; other keys are custom questions.

### Calls (Phase 5)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/calls/start` | `{"candidate_ids": [...]}` (1–100) → `202` with one result per candidate: `{candidate_id, ok, call_attempt_id, error: {code, message}}`. Each accepted candidate gets a `queued` attempt and an `initiate_call` job |
| GET | `/api/v1/calls` | Attempts, newest first; filters `candidate_id`, `call_status`; paginated |
| GET | `/api/v1/calls/{id}` | One attempt: `call_status`, `provider_status`, `end_reason`, times, `duration_seconds`, `failure_reason` |

Eligibility error codes: `candidate_not_found`, `candidate_deleted`, `opted_out`, `consent_missing`, `phone_invalid`, `job_inactive`, `call_already_active`, `outside_calling_window` (Mon–Sat 10:00–19:00 IST by default), `telephony_not_configured`; `enqueue_failed` if the job queue is down.

`call_status`: `queued → initiating → (ringing) → in_progress → completed`, or `failed | no_answer | busy | cancelled` from any live state. `end_reason`: `agent_completed`, `candidate_hangup`, `no_answer`, `busy`, `provider_failed`, `technical_failure`, `cancelled`, `invalid_number`.

### Provider endpoints (no session; secret token in the URL)

| Method | Path | Notes |
|---|---|---|
| POST | `/cb/{token}` (alias `/api/v1/webhooks/exotel/status/{token}`) | Exotel status callback, form or JSON. Wrong token → 403. Always `200 {"ok": true, "outcome": applied\|ignored\|duplicate\|unknown_call\|unmapped_status\|error}` so Exotel doesn't retry into a failure |
| WebSocket | `/api/v1/webhooks/exotel/stream/{token}` | Exotel Voicebot media stream ([telephony.md](telephony.md)). Wrong token → closed (1008); unknown call → 1008; media format mismatch → 1003 |

`make exotel-urls` prints both URLs with their tokens.

## Health

| Endpoint | Purpose | Response |
|---|---|---|
| `GET /health` | Liveness: process is up | `200 {"data": {"status": "ok", "version": "0.0.0"}}` |
| `GET /health/ready` | Readiness: database, Redis and worker heartbeat | `200` when all ok; `503` with `components` showing which failed and a short `errors` reason |

External providers (OpenAI, Deepgram, Exotel, Google Sheets) are not part of readiness; their status will be at `GET /api/v1/settings/status` (Phase 8).
