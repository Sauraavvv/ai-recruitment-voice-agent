# Phase 7: Structured data and Google Sheets

| | |
|---|---|
| Source | plan.md §10 Phase 7, Module G, Module H, §3 architecture principles |
| Depends on | P6 (real conversations). The Sheets client (P7-T5 to P7-T10) needs only P1 and can be built earlier. |
| Unlocks | P8, P9 |
| Size / risk | L / Medium |

## 1. Goal

After every call, produce validated final screening data and a neutral summary, commit them to PostgreSQL (the source of truth), then copy the candidate's row to Google Sheets: one row per candidate, retried on failure, and with no data lost when Sheets is down.

## 2. Entry criteria

P6 calls produce transcripts and state snapshots. Access to a Google Cloud project. A spreadsheet the team will use.

## 3. Scope

- **In:** plan.md tasks 1–10, the transactional outbox, a sync reconciler, integration status endpoints.
- **Out:** dashboard UI for these (P8); two-way sync (edits in the sheet never flow back).

## 4. Deliverables

```text
backend/app/
  services/  finalization_service.py  summary_service.py (from P2, now wired)
             sheets_service.py  sheet_mapping.py  sync_service.py
  workers/   sync_worker.py   (+ finalize_call job in call_worker.py)
  api/v1/    integrations.py
  database/migrations/versions/0003_finalize_and_sync.py
docs/google-sheets.md
```

## 5. Finalization pipeline

`finalize_call(attempt_id)` is an idempotent ARQ job:

```text
load conversation ──► already finalized? ──yes──► stop
        │ no
        ▼
final extraction (LLM over full transcript) ─► reconcile with live state ─► validate
        ▼
ONE DB TRANSACTION:
  conversations   extracted_data, screening_completed, finalized_at
  candidates      merged fields, screening_status, opted_out
  call_attempts   end data
  sync_logs       new row, status = pending          ◄── outbox
        ▼ commit
summary (LLM, up to 2 retries) ─► save ─► enqueue sync job
```

A summary failure never blocks persistence. The sync job always reads the latest database state.

### P7-T1 Implement final extraction

- One LLM pass over the full transcript, using the P2 field schema plus an evidence quote (and turn number) for every value.
- Reconcile with the live state:

| Live state | Final pass | Result |
|---|---|---|
| value | same value | Keep |
| CONFIRMED value | different | Keep live value; flag `conflict` for the recruiter |
| ANSWERED value | different, with evidence later in the transcript | Take the final value; old one kept in history |
| MISSING | value with evidence in a candidate turn | Accept, `source=final_pass` |
| any | value whose evidence isn't in the candidate's turns | Reject (prevents invented data) |
| DECLINED | — | Stays DECLINED |

### P7-T2 Validate final screening data

- `FinalScreeningData` Pydantic model with the P2 range rules. A bad field becomes null plus a note; the rest of the record still saves.
- Screening status:

| Condition | `screening_status` |
|---|---|
| Opted out | `opted_out` |
| Not interested | `declined` |
| Wrong person | `wrong_person` |
| Callback requested before finishing | `callback_requested` |
| All required fields answered, declined or unknown, and the call reached closing | `completed` |
| Some data collected | `partially_completed` |
| No conversation (no answer, failed) | unchanged |

### P7-T3 Save results to PostgreSQL

- One transaction, as in the diagram.
- Candidate merge: newer non-null values overwrite older ones; null never overwrites (plan.md state rules); `opted_out` only ever changes from false to true; `screening_field_meta` updated.
- `conversations.extracted_data` keeps the per-attempt result, so history survives later changes to the candidate record.
- Idempotent: check `finalized_at` under `SELECT … FOR UPDATE`.
- Opting out also cancels any scheduled attempts in the same transaction (P9 relies on this).

### P7-T4 Generate the summary

- P2's summary service: neutral, plan.md Module G sections, ≤ 1,000 characters, judgment-word guard.
- Stored in `conversations.summary`. The candidate's "latest summary" is the latest finalized conversation's.

## 6. Google Sheets

### P7-T5 Configure the Google service account

- Google Cloud project → enable the Sheets API → create a service account → JSON key.
- Share **only** the target spreadsheet with the service account's email, as Editor (minimum access, plan.md §9). Scope: `https://www.googleapis.com/auth/spreadsheets`.
- `GOOGLE_SERVICE_ACCOUNT_JSON` holds the **path** to a read-only mounted file (`secrets/google-sa.json`, gitignored) **[Decision: path or inline JSON]**. Never in the frontend; never logged.
- The spreadsheet contains candidate personal and salary data. Limit who it's shared with to the recruitment team.

### P7-T6 Implement the Sheets API client (`sheets_service.py`)

- Official `google-api-python-client` + `google-auth`. The client is blocking, so it runs in the worker through `asyncio.to_thread`.
- Four operations only: read the header, read column A, update a row range, append a row.
- Config: `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_TAB` (default `Candidates`).
- Header check: empty sheet → write the 23 headers in plan.md Module H order. Header mismatch → integration status `error` and no writes, which protects a sheet someone has edited.
- All writes use `valueInputOption=RAW`, so candidate text such as `=HYPERLINK(...)` is stored as text (no formula injection) and phone numbers keep their `+`.

### P7-T7 Look up rows by Candidate ID

- Read `Candidates!A2:A` on every sync and find the row. This stays correct even if someone sorts or inserts rows, and costs one read call.
- Writes are serialized with a Redis lock (`rcai:sheets:lock`), so two syncs can't both append a new row for the same candidate.

### P7-T8 Insert or update rows

- Pure function `to_sheet_row(candidate, latest_attempt, latest_conversation, attempt_count) -> list[str]` in `sheet_mapping.py`, producing the 23 columns:
  - dates in Asia/Kolkata as `YYYY-MM-DD HH:MM`; booleans `Yes` / `No` / blank; plain numbers (`12.5`), with the CTC unit (LPA) noted in the header
  - Call Status from the latest attempt; Screening Status; Attempt Count; Last Call Date; Next Retry Date (P9)
  - Transcript Reference = dashboard link `{FRONTEND_URL}/candidates/{id}`. The transcript itself stays in the app behind login
- Existing row → `values.update` on `A{row}:W{row}`. Not found → `values.append` with `INSERT_ROWS`.
- Add a note on the header: "Written by the recruitment system. Manual edits will be overwritten." (one-way sync).

### P7-T9 Add synchronization logs

- `sync_logs` rows go from `pending` to `success` (with `synced_at`) or `failed` (with `error_message`, `attempts`, `next_attempt_at`) [Proposed columns].
- The outbox row is written in the same transaction as every candidate change: finalization, import, recruiter edits (all through `candidate_service`).
- Several pending rows for one candidate are satisfied by a single sync of the latest state.

### P7-T10 Retry temporary sync failures

| Error | Handling |
|---|---|
| 429, 500, 502, 503, 504, timeouts, network errors | Retry with backoff and jitter: 1 min, 5 min, 15 min, 1 h, 6 h; then `failed`, visible in the dashboard |
| 400, 403, 404 (bad range, no permission, wrong sheet) | `failed` immediately; integration status `error`; message shown to recruiters |

- Reconciler cron every 10 minutes: re-enqueue `pending` rows older than 5 minutes and `failed` rows whose `next_attempt_at` has passed.
- Endpoints: `POST /api/v1/integrations/google-sheets/sync/{candidate_id}` (manual sync) and `GET /api/v1/integrations/google-sheets/status` (configured, reachable, header ok, last success, pending and failed counts).
- **[Verify]** current Sheets API per-minute quotas. MVP volume is far below them, and backoff handles 429s.

## 7. Tests

**Unit**
- Reconciliation table; validation and screening-status rules.
- Candidate merge: null never overwrites; `opted_out` is sticky.
- Row mapping: 23 columns in order; formula-like strings stay raw; IST dates; booleans; missing values.
- Outbox atomicity: force a failure mid-transaction → neither the candidate update nor the outbox row exists.
- Finalize idempotency: run twice → one result.

**Integration** with a dedicated **test spreadsheet** (real API, `@pytest.mark.sheets`)
- New candidate → appended; second sync → same row updated.
- Sheet sorted by hand → correct row still updated.
- Manual sync 5 times → one row.
- Revoke access → `failed`, database intact → restore → reconciler syncs.

**Real calls:** a complete call and a partial call through finalization.

## 8. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P7-AC1 | Completed calls update candidate records | Real call → candidate fields and `screening_status` set and matching the transcript |
| P7-AC2 | Partial calls preserve collected information | Hang up after 4 answers → those 4 saved; `partially_completed` |
| P7-AC3 | Summary is available | `conversations.summary` present, neutral, lists missing information |
| P7-AC4 | Google Sheet receives the correct data | Script compares each synced sheet row with the database |
| P7-AC5 | Repeated synchronization doesn't create duplicate rows | 5 manual syncs → one row |
| P7-AC6 | A temporary Sheets failure doesn't lose the database record | Outage simulation → database intact, failed log, automatic recovery |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Final pass invents values | Evidence check against the candidate's turns |
| People edit or rearrange the sheet | Header check; lookup by ID on every sync; one-way-sync note |
| Duplicate appends under concurrency | Global write lock |
| Personal data exposed through the sheet | Restricted sharing; transcripts stay in the app |
| Credential leak | Mounted file, gitignored, never logged |

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| Service-account JSON as a path or inline | Path to a mounted file |
| Show data conflicts to recruiters | Yes, in "needs attention" (P8) |
| Sheet tab name | `Candidates` |

## 11. Manual setup and credentials

Google Cloud project with the Sheets API enabled; service-account key; spreadsheet shared with the service account; a second spreadsheet for tests.

## 12. Exit

[Phase exit report](README.md#phase-exit-report) with a link to the test-sheet evidence.
