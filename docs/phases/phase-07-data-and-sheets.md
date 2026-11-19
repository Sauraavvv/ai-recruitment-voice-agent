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

## 13. As built (2026-11-19)

Sheets design and setup: [google-sheets.md](../google-sheets.md).

**Deliverables:** `agent/final_pass.py` (final extraction, evidence check, reconciliation, `FinalScreeningData`, screening-status rules), `services/finalization_service.py`, `sheet_mapping.py`, `sheets_service.py`, `sync_service.py`, `workers/sync_worker.py` (+ `finalize_call` and `reconcile_finalize` in `call_worker.py`), `api/v1/integrations.py`, migration **`0005_finalize_and_sync.py`** (0003/0004 were taken), `scripts/sheets_tool.py` (`make sheets-check|sync|backfill|compare`), `docs/google-sheets.md`. Dependencies added: `google-api-python-client` 2.202.0, `google-auth` 2.62.2 (and theirs); nothing upgraded.

**Deviations from §5–§6 and why:**
- The end of the call (`screening_store.store_outcome`) now stores only the conversation (transcript + live result). Candidate fields, status and meta move into the finalization transaction. **Exception:** an opt-out is written at once with its outbox row. It only ever goes false → true, and no other call may be placed while finalization is queued.
- Final pass lives in `agent/final_pass.py` (an agent concern, pure and unit-tested); the service does the database work. It reuses the P2 field schema (`FinalFields` extends `ExtractedFields`) plus evidence `{field, quote, seq}`. Quotes are checked with the P2 fuzzy matcher against **candidate** lines only (the cited line first, then any). An assistant's read-back is never evidence.
- Reconciliation additions: UNKNOWN is treated like MISSING (an evidence-backed value is accepted). An ANSWERED value whose final-pass evidence is *not* later than the live answer is kept and flagged `conflict`, same as CONFIRMED. The live position is found from the live raw words, falling back to the n-th candidate line.
- Screening status: no data and no decision (e.g. hung up after the greeting) leaves the status unchanged instead of `not_started`, so a retry can't erase a partial result. "Reached closing" = the conversation ended `completed`.
- Merge: a field without a value this call keeps the older value **and** its meta; the meta records the status (e.g. declined) only when there's no older value. Custom answers go to `screening_field_meta` (there are no columns for them).
- Summary: 3 tries on LLM errors or rejected text (was 2, errors weren't retried), then the facts-only text. It runs after the commit and saves with its own outbox row (the sheet has a Call Summary column). A crash between the two is handled: `finalized_at` set without a summary → the next run writes only the summary. A cron (`reconcile_finalize`, every 10 min) re-queues conversations not finalized or summarized after 10 min.
- Sheets operations are **batched**: one `values.batchGet` (header + column A), one `values.batchUpdate` for all existing rows, one `values.append` for all new rows, per round of ≤100 candidates. The service account gets 60 requests a minute (checked 2026-11-19), and a 500-row import would otherwise be 1 000+ requests. The Redis lock covers the whole drain (one drainer); queued sync jobs carry no job id and keep no result, so a change during a running sync is never lost.
- Numbers are written as numbers (RAW), not strings, so the sheet can sort by CTC; units are in the headers ("Total Experience (Years)", "Current CTC (LPA)"). Labels are human-readable ("No answer", "Partially completed").
- Retry: transient errors (also 408) back off 1 m/5 m/15 m/1 h/6 h with up to +20% jitter, then fail for good (manual sync retries). Permanent errors (400/403/404, refused key, header mismatch) fail at once with integration status `error`, but retry every 30 min, so "restore access → reconciler syncs" works without a manual step.
- Outbox rows are also written when a call is queued and when an attempt reaches a final status (Call Status, Attempt Count, Last Call Date columns), not only for candidate edits.
- Missing tab → created; empty tab → header written, frozen, with the one-way-sync note on A1.
- Added after running on the 7 real Phase 6 calls (2026-11-19):
  - **Out-of-order finalization**: an older call finalized after a newer one (a backlog after a worker outage) only fills fields that are still empty and never changes `screening_status` (`final.superseded`). Found when the new reconciler finalized the 7 stored calls in parallel and the dev candidate ended up with an older call's status; the dev candidate was then re-finalized in order.
  - **No false conflicts**: a final value that restates the live answer (same candidate line, same words once normalized, same notice days) is not a conflict. Before this, 6 of 6 "conflicts" on the real calls were "Thirty days" vs "30 days" or the same quote with/without its full stop. Lines are located by exact normalized words before the fuzzy match ("twelve lakhs" fuzzily matched "eighteen lakhs").
- `GOOGLE_SERVICE_ACCOUNT_JSON` is a **path** (decision §10, recommendation taken): `./secrets/google-sa.json` mounted read-only at `/app/secrets`.

**Not done:** the live parts. They need the Google Cloud project, the service account and two spreadsheets (§11): `make test-sheets`, the real-call cards (a complete and a partial call through finalization), P7-AC4 on the real sheet (`make sheets-compare`), and the revoke-access drill.
