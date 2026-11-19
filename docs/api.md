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
| GET | `/api/v1/auth/me` | Current user, with `role`: `admin` or `recruiter` (Phase 8; only an admin may change the Google Sheet) |

### Candidates

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/candidates` | Requires `consent_attested: true`. Phone normalized to E.164. `job_id` defaults to the active job. 409 `duplicate_phone` with `details.existing_candidate_id` |
| GET | `/api/v1/candidates` | `q` (name/phone/email), `screening_status`, `call_status` (the latest call's status, or `not_called`), `job_id`, `interested`, `sort` (`created_at`, `name`, `updated_at`, prefix `-` for descending; default `-created_at`), `page`, `page_size`. Rows add `eligibility {can_call, reason, message}`, `last_call {id, attempt_number, call_status, end_reason, at, terminal}` (the latest call that isn't only scheduled), `last_call_has_transcript`, `open_conflicts`, `retry_status` (Phase 9: `{kind: retry\|callback\|exhausted, call_attempt_id, at, attempt, attempts_made, max_attempts, callbacks_made, max_callbacks}` or null). A scheduled retry or callback doesn't block `can_call`: a call started now replaces it |
| GET | `/api/v1/candidates/{id}/overview` | `{eligibility, summary, sheet_sync, sheets_configured, conflicts, retry_status}`. `summary`: the latest finalized call that collected data, else the latest (`newer_call_without_data` says when a later call had nothing) |
| POST | `/api/v1/candidates/{id}/conflicts/{field}/resolve` | `{choice: "keep" \| "use"}`: keep the stored value or take the other one. Marks the conflict resolved (who, when, choice) on the field's meta and in the call's `final.conflicts`; Sheets outbox row. `409 no_conflict` |
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

### Calls (Phase 5, completed in Phase 8)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/calls/start` | `{"candidate_ids": [...], "dry_run": false, "override_limit": false}` (1–100) → `202` with one result per candidate: `{candidate_id, ok, call_attempt_id, error: {code, message}}`. Each accepted candidate gets a `queued` attempt and an `initiate_call` job; a scheduled retry or callback is cancelled and replaced (`replaced_by_manual_call`). `dry_run: true` only checks (the confirmation dialog). Phase 9: `max_attempts_reached` when the candidate's calls are used up; send again with `override_limit: true` after the recruiter confirms |
| GET | `/api/v1/calls` | Attempts, newest first, with `candidate_name`, `applied_role`, `has_transcript`. Filters `candidate_id`, `call_status` (repeatable), `q` (candidate name/phone), `created_from`, `created_to`; paginated |
| GET | `/api/v1/calls/{id}` | One attempt: `call_status`, `provider_status`, `end_reason`, times, `duration_seconds`, `failure_reason`, `next_retry_at` (when a scheduled retry or callback is due), `retry_count`, `retry_decision` (`retry_scheduled`, `callback_scheduled`, `exhausted`, `no_retry:<reason>`; [retries.md](retries.md)), `retry_note`, `has_recording` (the provider's recording URL is never sent) |
| GET | `/api/v1/calls/{id}/transcript` | `{entries: [{seq, speaker, text, timestamp, interrupted, heard_text}], summary, finalized, …}`; empty entries for an unanswered call |
| POST | `/api/v1/calls/{id}/retry` | A new `manual` attempt for the candidate under the start rules; optional body `{"override_limit": true}`; same result shape as one `start` item |
| POST | `/api/v1/calls/{id}/cancel` | Only `pending`, `queued`, `retry_scheduled`, `callback_requested` → `cancelled` (`failure_reason: cancelled_by_recruiter:<user>`); else `409 call_not_cancellable` |
| POST | `/api/v1/calls/{id}/hangup` | Ends a call `in_progress` on this server: the agent says its closing line and hangs up (`failure_reason: ended_by_recruiter`). `409 call_not_in_progress`, `404 call_session_not_found` |

Eligibility error codes: `candidate_not_found`, `candidate_deleted`, `opted_out`, `consent_missing`, `phone_invalid`, `job_inactive`, `call_already_active`, `calling_paused` (Settings page), `outside_calling_window` (Settings page; Mon–Sat 10:00–19:00 IST by default), `telephony_not_configured`, `voice_unavailable`; `enqueue_failed` if the job queue is down.

`call_status`: `queued → initiating → (ringing) → in_progress → completed`, or `failed | no_answer | busy | cancelled` from any live state. `end_reason`: `agent_completed`, `candidate_hangup`, `no_answer`, `busy`, `provider_failed`, `technical_failure`, `cancelled`, `invalid_number`, and the conversation's own reasons (`declined`, `opted_out`, `callback_scheduled`, `wrong_person`, `silence_timeout`, `max_duration`, `escalated`).

### Dashboard (Phase 8)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/dashboard/stats?range=today\|7d\|all` | The nine tiles (phase-08 §5.1) plus `definitions` (tooltip text). `range` limits completed / unanswered / failed by when the call was placed. An empty database gives zeros |
| GET | `/api/v1/dashboard/activity` | The 20 most recently changed attempts with candidate name and status |
| GET | `/api/v1/dashboard/attention` | `[{candidate_id, candidate_name, reason, at, call_attempt_id, detail, conflict}]`; reasons `callback_due`, `data_conflict`, `unanswered_question`, `vague_callback`, `technical_failure`, `partially_completed`, `wrong_person`, `attempts_exhausted`, `callback_not_scheduled` (Phase 9: callback limit reached or more than 14 days ahead), `sheets_sync_failed` (most urgent first) |
| GET | `/api/v1/dashboard/quick-start` | Eligible candidates never called (first 20), total, whether calling is open now, why not (`blocked_reason`), lines in use |
| GET | `/api/v1/dashboard/summary` | Phase 1 charts, live calls, latest transcript |

### Settings (Phase 8)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/settings` | `{general: {organization_name, agent_introduction, calling: {days, start_hour, end_hour}, max_concurrent_calls, retry: {max_attempts, interval_days, enabled, max_callbacks, alternate_slots}, calling_enabled}, limits: {max_concurrent_calls, timezone, calling_enabled_env}, introduction: {text, …}, calling_now}` |
| PATCH | `/api/v1/settings` | Any subset of `general`. The introduction may use `{first_name}`, `{company}`, `{job_title}`, `{organization}`, must contain "AI" and end with "?"; `null` = built-in line. Concurrency is capped by `MAX_CONCURRENT_CALLS`. `retry` may be partial (fields left out are unchanged); `interval_days` 2–4, `max_callbacks` 0–5. Logged with the user id |
| GET | `/api/v1/settings/status?refresh=` | `{providers: [{name, label, configured, reachable, message, detail, last_checked}], google_sheets}`; checks cached 60 s; never contains a key |

### Google Sheets (Phase 7)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/integrations/google-sheets/status` | `{configured, tab, state, message, reachable, header, service_account_email, last_success_at, last_error_at, pending_candidates, failed_candidates, checked_at}`. `state`: `ok`, `degraded` (temporary failures, retrying), `error` (needs fixing), `unknown`, `not_configured`. `reachable`/`header` come from a live check cached 60 s; `?refresh=true` forces it |
| POST | `/api/v1/integrations/google-sheets/sync/{candidate_id}` | `202 {candidate_id, sync_log_id, sync_status: "pending", queued}`. Also retries a row that failed for good. `404 candidate_not_found`, `409 sheets_not_configured` |
| POST | `/api/v1/integrations/google-sheets/backfill` | "Sync all": every active candidate queued |
| POST | `/api/v1/integrations/google-sheets/check` | **Admin.** `{link, tab?}` → `{sheet_id, sheet_url, tab, reachable, header, message, service_account_email, can_save}` for that sheet (nothing saved) |
| PUT | `/api/v1/integrations/google-sheets/sheet` | **Admin.** Same body; checked again, saved in `app_settings` (`.env` stays the default), every active candidate queued for the new sheet. The old sheet keeps its rows. `403 admin_required`, `409 sheet_not_usable` |

Status (Phase 8) also has `sheet_id`, `sheet_url`, `sheet_source` (`settings` or `env`), `sheet_changed_at`, `can_edit`, `key_configured`.

Every candidate change (create, edit, import, call queued or ended, finalization, summary) adds a Sheets outbox row in the same transaction. Details: [google-sheets.md](google-sheets.md).

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
