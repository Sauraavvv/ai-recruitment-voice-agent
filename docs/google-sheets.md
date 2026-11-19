# Google Sheets sync

Status: **live since 2026-11-19 (Phase 7)**: `make test-sheets` 5/5 on the test spreadsheet, `make sheets-compare` 0 problems on the team sheet.

PostgreSQL is the source of truth. The sheet is a one-way copy for the recruitment team: one row per candidate, written by the system. Edits made in the sheet never come back, and the next sync overwrites them.

## 1. Setup (once)

1. **Google Cloud project**: [console.cloud.google.com](https://console.cloud.google.com) → create a project (or pick one) → *APIs & Services → Library* → enable **Google Sheets API**.
2. **Service account**: *IAM & Admin → Service accounts → Create*. It needs no project roles. Open it → *Keys → Add key → JSON*. A file downloads.
3. Save that file as `secrets/google-sa.json` in the repository root. It is gitignored and mounted read-only into the backend and worker containers at `/app/secrets`. Never paste its contents anywhere, the chat included. The containers run as uid 1000: check that the file is readable with `docker compose exec backend test -r /app/secrets/google-sa.json && echo readable` (if not, `chmod 644 secrets/google-sa.json`). If *Create key* is greyed out or refused, the account's organization blocks key creation (policy `iam.disableServiceAccountKeyCreation`): an organization admin must allow it for this project, or use a project under a personal Google account.
4. **Spreadsheet**: create one for the team (e.g. "HireCall candidates"). *Share* it with the service account's email (`…@….iam.gserviceaccount.com`, shown in the key file and by `make sheets-check`) as **Editor**. Share it with nobody else outside the recruitment team: it holds names, phone numbers and salaries.
5. `.env`:
   ```
   GOOGLE_SERVICE_ACCOUNT_JSON=/app/secrets/google-sa.json
   GOOGLE_SHEET_ID=<id from the URL: docs.google.com/spreadsheets/d/<id>/edit>
   GOOGLE_SHEET_TAB=Candidates
   ```
6. `docker compose up -d backend worker`, then `make sheets-check`. It should say `reachable: True`, `header: empty` (or `ok`).
7. `make sheets-backfill` writes every existing candidate. From then on everything is automatic.

For the live tests, make a **second** spreadsheet, share it the same way, and set `GOOGLE_TEST_SHEET_ID`. `make test-sheets` works in a temporary tab and deletes it afterwards.

Scope: `https://www.googleapis.com/auth/spreadsheets` only. The service account can open only spreadsheets shared with it.

## 2. The sheet

The tab (`Candidates` by default) is created if it doesn't exist. On an empty tab the first sync writes the header, freezes it, and adds a note on A1: *"Written by the recruitment system. Manual edits will be overwritten."*

| # | Column | Source |
|---|---|---|
| 1 | Candidate ID | `candidates.id`. The row is found by this on every sync |
| 2–5 | Candidate Name, Phone Number, Email, Job Role | candidate |
| 6–15 | Current Location … Interview Availability | candidate fields, merged after each call. Experience in years, CTC in LPA (units are in the headers). Interested: `Yes` / `No` / blank |
| 16 | Call Status | latest attempt (`No answer`, `Completed`, …) |
| 17 | Screening Status | candidate (`Completed`, `Partially completed`, …) |
| 18 | Attempt Count | attempts that were dialed (queued, cancelled and scheduled ones don't count) |
| 19 | Last Call Date | latest dialed attempt, `YYYY-MM-DD HH:MM` IST |
| 20 | Next Retry Date | the scheduled attempt's time (Phase 9) |
| 21 | Call Summary | latest finalized conversation |
| 22 | Transcript Reference | `{FRONTEND_URL}/candidates/{id}`. The transcript stays in the app, behind login |
| 23 | Last Updated | latest change to the candidate, its attempt or conversation, IST |

All writes use `valueInputOption=RAW`. Text such as `=HYPERLINK(...)` is stored as text, never run as a formula, and phone numbers keep their `+`. Numbers are written as numbers, so the team can sort and filter by CTC or experience.

**Sorting, filtering or inserting rows by hand is fine.** Changing the header row is not: if the header doesn't match exactly, the sync writes nothing, the integration status becomes `error`, and the message says so. Restore the header (or point `GOOGLE_SHEET_TAB` at an empty tab) and the rows sync on the next retry.

## 3. How it works

```text
candidate change (import, recruiter edit, call status, finalization, summary)
   └─ same DB transaction: sync_logs row, status=pending          ← outbox
        └─ after commit: queue `sync_sheets` (best effort)

sync_sheets (worker), under Redis lock rcai:sheets:lock:
   due rows (pending, or failed with next_attempt_at passed), ≤100 candidates per round
   → snapshot their row ids → read the LATEST database state
   → read header + column A (1 request) → update existing rows (1) → append new rows (1)
   → rows success | failed (+ backoff)          repeat until nothing is due

reconcile_sync (cron, every 10 min): pending > 5 min or failed & due → queue sync_sheets
```

- Several pending rows for one candidate are covered by one sync of the latest state.
- One drain runs at a time (the lock). Extra queued jobs wait up to 30 s, then find nothing to do.
- A Sheets outage only leaves rows `pending` or `failed`. The database is never rolled back or blocked.
- Not configured: rows stay `pending`. Configure Sheets later and they all sync (or run `make sheets-backfill`).

### Errors

| Error | Handling |
|---|---|
| 408, 429, 500, 502, 503, 504, timeouts, network errors | `failed`, retried after 1 min, 5 min, 15 min, 1 h, 6 h (each up to +20% jitter); after that `failed` for good. A manual sync retries it. Integration status `degraded` |
| 400, 403, 404, refused key, header changed | `failed` at once, integration status `error` with a message for recruiters (403 names the service account to share with). Retried every 30 min, so fixing access or the header recovers by itself |

### Quotas (checked 2026-11-19, [Google's limits page](https://developers.google.com/workspace/sheets/api/limits))

300 read and 300 write requests a minute per project, and **60 a minute per user**. The service account is one user. A batch request counts as one request. Going over gives HTTP 429; Google recommends exponential backoff with jitter. A sync round of up to 100 candidates costs 2–3 requests, so even a 500-row import is about 15 requests.

## 4. API

| Method | Path | |
|---|---|---|
| GET | `/api/v1/integrations/google-sheets/status[?refresh=true]` | configured, state (`ok` / `degraded` / `error` / `unknown` / `not_configured`), message, reachable and header (live check, cached 60 s), service account email, last success, last error, pending and failed candidate counts |
| POST | `/api/v1/integrations/google-sheets/sync/{candidate_id}` | 202: a pending outbox row is added and a sync queued. 409 `sheets_not_configured` |

## 5. Operations

| Command | |
|---|---|
| `make sheets-check` | service account, access, header |
| `make sheets-sync` | sync everything due, now |
| `make sheets-backfill` | queue every candidate and sync (first fill) |
| `make sheets-compare` | P7-AC4: every sheet row compared with the database; lists missing, different, extra and duplicate rows |
| `make test-sheets` | live tests on `GOOGLE_TEST_SHEET_ID` |

Logs: `sheets_synced` (updated / appended counts), `sheets_sync_failed` (transient, status, message), `sheets_sync_requeued`. Credentials are never logged.

## 6. Code

- `services/sheet_mapping.py`: `HEADERS`, `to_sheet_row()` (pure).
- `services/sheets_service.py`: `SheetsClient` (blocking, run in a thread), `upsert_blocking`, error classification, `SheetsService` (async).
- `services/sync_service.py`: `record_change` (outbox), `request_sync`, `drain`, status in Redis (`rcai:sheets:status`).
- `workers/sync_worker.py`: `sync_sheets`, `reconcile_sync`.
- `api/v1/integrations.py`.
- Tests: `unit/test_sheets.py`, `integration/test_sheets_sync.py` (fake sheet), `integration/test_sheets_live.py` (`-m sheets`).
