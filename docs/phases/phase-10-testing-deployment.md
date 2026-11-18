# Phase 10: Final testing and deployment

| | |
|---|---|
| Source | plan.md §10 Phase 10, §11 testing strategy, §12 non-functional requirements, §14 Definition of Done, §16 credentials |
| Depends on | P0–P9 |
| Unlocks | MVP sign-off |
| Size / risk | L / Medium |

## 1. Goal

Prove the MVP works end to end with real calls, harden the failure paths, deploy it on a stable HTTPS host with Docker Compose, document setup and operations, run the demo, and check off every Definition of Done item with evidence.

## 2. Entry criteria

P0–P9 accepted. A host for production. **Exotel KYC completed** (until then the account can only call verified numbers) and production caller ID approved. Testers available on different mobile networks.

## 3. Scope

- **In:** plan.md tasks 1–12, a security pass, a data-protection review.
- **Out:** everything in plan.md §13 (scope exclusions), which becomes the backlog.

## 4. Deliverables

```text
docker-compose.prod.yml  Caddyfile
scripts/  deploy.sh  backup.sh  restore.sh
backend/app/tests/integration/  (expanded)
frontend/tests/e2e/             (Playwright)
docs/  setup.md (complete)  deployment.md  runbook.md  test-report.md  demo-script.md  known-limitations.md
.github/workflows/ci.yml        (if the repo is hosted on GitHub)
```

## 5. Tasks

### P10-T1 Add integration tests

- Compose `test` profile: Postgres, Redis, backend, worker.
- Suites: API + database; worker jobs (finalize, sync, retry dispatch); provider contract tests: OpenAI (small live run), Deepgram (fixture audio), Sheets (test spreadsheet), Exotel parsers (captured real payloads).
- CI on every push or PR: lint, type-check, unit and integration tests. Live-provider suites run manually or nightly with secrets from the CI secret store.

### P10-T2 to P10-T9: test matrix

| ID | Plan test | Setup and steps | Expected |
|---|---|---|---|
| P10-T2 | Test actual calls | At least 3 full screenings with different testers, carriers (e.g. Jio, Airtel, Vi), devices, quiet and noisy places | All fields captured; transcript, summary and sheet row correct |
| P10-T3 | Test invalid numbers | Malformed number in an import; a valid-format but unassigned number dialled | First rejected at import; second → `failed` / `invalid_number`, no retry |
| P10-T4 | Test busy / no-answer | Reject the call; let it ring out | `busy` / `no_answer`; retry scheduled |
| P10-T5 | Test call disconnection | Candidate hangs up mid-question; phone loses network mid-call; backend container restarted mid-call | Partial data saved; attempt finalized by the reconciler; slot released; retry rules applied |
| P10-T6 | Test partial screening | Answer 4 questions, hang up | `partially_completed`; summary lists missing fields; attention item |
| P10-T7 | Test Google Sheets failure | Revoke service-account access during calls, then restore | Database complete; `sync_logs` failed then success; no duplicate rows |
| P10-T8 | Test retry scheduling | Staging minutes override; three misses; opt-out while a retry is scheduled | Retries on time; `exhausted`; scheduled retry cancelled |
| P10-T9 | Test concurrent call isolation | `MAX_CONCURRENT_CALLS=2`, two testers called at once | Each hears only their own name and questions; transcripts separate. Decide whether to enable 2 in production (plan.md §12) |
| added | Opt-out end to end | Say "don't call me again" | `opted_out`; no further calls; sheet shows it |
| added | Queue drain | 20 consented test candidates queued with concurrency 1 | Dialled one at a time, inside the window, no duplicates |
| added | Security | Unauthenticated API calls; webhook without token; search logs and the built frontend bundle for key patterns; `pip-audit`, `npm audit` | 401 / 403; no secrets found; no unaddressed high-severity vulnerabilities |
| added | Latency | Per-turn t0 → t4 across all P10 calls | Reported against P6 targets |

Record every result in docs/test-report.md with the call attempt IDs.

### P10-T10 Add deployment configuration

- **Host:** one Linux VM in an Indian region, close to Exotel and candidates. Size it from the P3/P6 benchmarks; 4 vCPU / 8 GB RAM is a starting point.
- **`docker-compose.prod.yml`:** no bind mounts or reload; `restart: unless-stopped`; healthchecks; CPU and memory limits; Postgres and Redis not exposed to the internet; volumes for data, model files and secrets (read-only).
- **Caddy** reverse proxy with automatic HTTPS: `app.<domain>` → frontend; `api.<domain>` → backend, including the WebSocket upgrade for the media stream. Only ports 80 and 443 open in the firewall.
- **Backend:** one Uvicorn worker (live call sessions run in-process).
- **Safe deploys:** `scripts/deploy.sh` turns on the global pause (P8), waits until no call is in progress (up to the max call duration), runs `alembic upgrade head`, restarts services, and turns calling back on. Docker `stop_grace_period` ≥ max call duration.
- **Backups:** nightly `pg_dump` to off-host storage with 14-day retention; one restore test before sign-off.
- **Logs:** JSON to stdout with Docker log rotation; latency and sync metrics searchable by IDs.
- **Secrets:** `.env` on the server with `chmod 600`; Google key file mounted read-only.
- **Telephony cut-over:** point the Exotel flow and status callback from the tunnel to the production domain, then re-run the P5-T10 checks on production.

### P10-T11 Add setup documentation

- `README.md`: what the system does, quick start, links.
- `docs/setup.md`: local setup end to end, and every credential from plan.md §16 with step-by-step provider setup (Exotel flow, Google service account and sharing, Deepgram, OpenAI spend limit, Kitten model download).
- `docs/deployment.md`: host provisioning, DNS, deploy and rollback, backup and restore.
- `docs/runbook.md`: webhooks not arriving; a stuck call; Sheets failing; high latency; pausing all calling; handling an opt-out or deletion request received by phone or email; rotating keys.
- `docs/known-limitations.md`: English only, 1–2 concurrent calls, one active job, one-way Sheets sync, and the plan.md §13 exclusions.

### P10-T12 Conduct an end-to-end demo

Script in docs/demo-script.md, run on production with consenting testers:

1. Log in; show Settings with every provider healthy.
2. Upload a 5-candidate CSV (testers' numbers) → preview → confirm.
3. Start calls from the dashboard and watch the statuses change.
4. Tester A completes the screening; tester B doesn't answer; tester C asks not to be called again.
5. Show A's transcript, answers and summary, and the updated Google Sheet row.
6. Show B's scheduled retry and C's opt-out.

Record the demo for stakeholders.

### P10-T13 Data-protection review (added)

Phone numbers, salaries and voice transcripts are personal data. Before real candidates are called, someone responsible for compliance confirms:
- the disclosure in the agent's introduction (AI, company, purpose, and recording if enabled)
- the consent basis for calling
- a retention period for transcripts and recordings (e.g. 180 days, then deleted)
- who can access the dashboard and the spreadsheet
- how deletion requests are handled

India's Digital Personal Data Protection Act, 2023 is the likely framework **[Verify with legal/compliance]**.

## 6. Definition of Done evidence (plan.md §14)

| Item | Evidence |
|---|---|
| Frontend and backend run successfully | Production URLs; health checks |
| Recruiter can upload an Excel/CSV file | P1-AC1; demo step 2 |
| Candidate data is saved in PostgreSQL | Query in the test report |
| Recruiter can select a candidate | Demo step 3 |
| Backend initiates an actual outbound call | Attempt IDs from P10-T2 |
| Candidate can hear the AI introduction | Tester confirmations |
| Candidate can respond using speech | Transcripts |
| STT transcribes candidate speech | Transcripts |
| OpenAI generates context-aware responses | Transcripts (multi-answer and clarification turns) |
| Kitten TTS generates the agent voice | Configuration + tester confirmations |
| Candidate hears the generated response | Tester confirmations |
| Agent collects the required recruitment fields | P10-T2 field accuracy |
| Agent handles unanswered questions and callbacks | P10-T6; P9-AC5 |
| Transcript is saved | Database |
| Screening summary is generated | Database / UI |
| Candidate record is updated | Database |
| Google Sheet is updated | Sheet rows |
| Dashboard displays the actual call status | P8-AC1, P8-AC2 |
| Manual retry works | P8-AC4 |
| Automatic retry works for eligible calls | P10-T8 |
| Opt-outs are enforced | Opt-out test |
| At least three complete test calls verified | Attempt IDs listed |

## 7. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P10-AC1 | A recruiter can upload candidates, initiate real calls, complete screening, view summaries and see the updated Google Sheet (plan.md) | Demo run on production, recorded |
| P10-AC2 (added) | Every Definition of Done item has evidence | Table in §6 complete |
| P10-AC3 (added) | Test matrix passed, or failures documented with an owner | docs/test-report.md |
| P10-AC4 (added) | Production runs on HTTPS with working backups | Restore test done |
| P10-AC5 (added) | Documentation is complete | A teammate sets up locally from docs/setup.md alone |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Production telephony differs from dev (caller ID, routing) | Repeat P5-T10 on production before the demo |
| Server too small for TTS plus 2 calls | Size from benchmarks; keep concurrency at 1 until P10-T9 passes |
| WebSocket problems behind the proxy | Caddy handles upgrades; test the stream path explicitly |
| Compliance gaps | P10-T13 before real candidates are called |

## 9. Open decisions

| Decision | Recommendation |
|---|---|
| Hosting provider and domain | Any VM provider with an Indian region |
| Two concurrent calls in production | Only after P10-T9 passes |
| Retention period for transcripts and recordings | Set in P10-T13 |

## 10. Manual setup and credentials

Production host and domain, production `.env`, Exotel URLs updated to production, backup storage, testers for the demo.

## 11. Exit

Final report: what works, the evidence, known limitations, and next steps (plan.md §13 exclusions as the backlog).
