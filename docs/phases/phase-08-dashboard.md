# Phase 8: Dashboard and call controls

| | |
|---|---|
| Source | plan.md §10 Phase 8, §7 pages 1–5, §6 calling and dashboard endpoints |
| Depends on | P1 pages; P5–P7 backend |
| Unlocks | P9 UI pieces, P10 |
| Size / risk | L / Low–Medium |

## 1. Goal

The recruiter UI from plan.md §7, driven entirely by real database values: dashboard, candidates with call controls, candidate detail with transcript and summary, a calls list, and settings with provider status. Status changes appear without a manual refresh.

## 2. Entry criteria

P5–P7 accepted; a few real call attempts in the dev database to look at.

## 3. Scope

- **In:** plan.md tasks 1–10, settings endpoints, a global calling pause.
- **Out:** retry automation behaviour (P9). The retry settings form can be built here.

## 4. Deliverables

```text
backend/app/
  api/v1/     dashboard.py  calls.py (complete)  settings.py
  services/   dashboard_service.py  settings_service.py  provider_status_service.py
  database/migrations/versions/0004_app_settings.py
frontend/
  app/(app)/layout.tsx      # navigation shell
  app/dashboard/  app/candidates/  app/candidates/[id]/  app/calls/  app/settings/
  components/  StatTile  StatusBadge  CallHistory  TranscriptView  SummaryCard  ConfirmDialog  EmptyState  ErrorState
  hooks/       useCandidates  useCalls  usePolling
```

## 5. Backend

### 5.1 Dashboard metrics (`GET /api/v1/dashboard/stats`)

Each metric is one query; the definition is shown as a tooltip in the UI **[Decision: confirm definitions]**.

| Metric | Definition |
|---|---|
| Total candidates | Candidates not deleted |
| Calls completed | Attempts with `call_status = completed` |
| Calls pending | Attempts in `pending`, `queued`, `initiating` |
| Calls in progress | Attempts in `ringing`, `in_progress` |
| Unanswered calls | Candidates whose latest attempt is `no_answer` or `busy` |
| Failed calls | Candidates whose latest attempt is `failed` |
| Interested candidates | `candidates.interested = true` |
| Screening completed | `candidates.screening_status = completed` |
| Scheduled retries (added) | Attempts in `retry_scheduled`, `callback_requested` |

Optional `?range=today|7d|all` for call metrics. An empty database returns zeros, never placeholder numbers (plan.md rule).

### 5.2 Activity and attention

- `GET /api/v1/dashboard/activity`: the last 20 call status changes, with candidate name and time.
- `GET /api/v1/dashboard/attention`: candidates with a reason code: callback due within 24 h, partially completed, data conflict (P7), technical failure, Sheets sync failed, a candidate question the agent couldn't answer, wrong person, attempts exhausted (P9), vague callback request.

### 5.3 Calls endpoints

| Endpoint | Notes |
|---|---|
| `POST /api/v1/calls/start` | Exists from P5; returns eligibility results per candidate |
| `GET /api/v1/calls`, `GET /api/v1/calls/{id}` | Filters: status, candidate, date range; includes `end_reason`, duration, provider status |
| `GET /api/v1/calls/{id}/transcript` | Transcript JSON from `conversations` |
| `POST /api/v1/calls/{id}/retry` | Manual retry with the P5 eligibility rules (opt-out, consent, window, no live attempt); creates `attempt_type=manual` |
| `POST /api/v1/calls/{id}/cancel` | Allowed for `pending`, `queued`, `retry_scheduled`, `callback_requested` |
| `POST /api/v1/calls/{id}/hangup` [Proposed] | Ends an in-progress call through the provider (safety control) |
| `GET /api/v1/calls/{id}/recording` [Proposed] | Streams the recording through the backend after auth, only if recording is enabled; the provider URL never reaches the browser **[Verify Exotel recording access]** |

Candidate list rows include `eligibility: {can_call, reason}` so the UI can disable buttons and say why.

### 5.4 Settings [Proposed]

- `app_settings` table (single row, JSONB sections): organization name, agent introduction template, calling window (days, start, end, timezone), max concurrent calls (capped by the `MAX_CONCURRENT_CALLS` env value), retry configuration (P9), and **calling enabled** (global pause switch).
- `GET /api/v1/settings` and `PATCH /api/v1/settings`: Pydantic-validated; changes logged with the user id.
- `GET /api/v1/settings/status`: per provider `configured`, `reachable`, `last_checked`, `message`. Cheap checks cached for 60 s **[Verify the cheapest authenticated call for each]**:
  - OpenAI: list models
  - Deepgram: key/project check
  - Exotel: account details
  - Kitten: model loaded + last latency
  - Google Sheets: P7 status
- Never returns keys or partial keys (plan.md §7).
- Global pause: when off, `start`, `retry` and the P9 dispatcher refuse to dial, and the worker skips queued attempts with a clear reason.

## 6. Frontend tasks

- Data fetching with TanStack Query and the generated OpenAPI types from P1.
- Component library: Tailwind only, or shadcn/ui for table, dialog and toast **[Decision]**.

### P8-T1 Dashboard statistics (page 1)

Stat tiles from 5.1, calling progress (in progress / queued / scheduled), recent activity, attention list with links, and a quick-start action: choose eligible candidates not yet called → confirmation dialog (count, calling-window status, concurrency) → start.

### P8-T2 Call status table (page 2: Candidates)

- Columns from plan.md: name, phone, job role, experience, call status, screening status, interest, last call date, actions (view, call, retry, view transcript).
- Server-side search (debounced) and filters (call status, screening status, interest); pagination.
- Bulk select → start calls (max 20 per action).
- Disabled actions show the reason from `eligibility`.

### P8-T3 Call initiation UI

Confirmation dialog for every start, single or bulk. Shows who will be called and who is skipped, with reasons from the API.

### P8-T4 Candidate detail page (page 4)

Editable profile; screening answers with field status chips (answered, confirmed, declined, unknown, missing, conflict) and the candidate's quoted words on hover; opt-out badge; Google Sheets sync status with "Sync now".

### P8-T5 Transcript view

Chat-style view per attempt with timestamps, interrupted markers and an attempt selector.

### P8-T6 Summary view

Latest summary, missing information and any callback request.

### P8-T7 Call history

Timeline of attempts: number, type, status, start, duration, end reason, next retry date. Recording player if enabled and authorized.

### P8-T8 Manual retry

Retry button enabled only when eligible, with a confirmation dialog.

### P8-T9 Live status refresh

Polling every 3 s while any visible call is active and every 30 s otherwise; paused when the tab is hidden. Status changes appear within 5 s of the webhook.

### P8-T10 Error and loading states

Skeleton loaders; empty states that point to the next step ("Upload candidates"); inline errors with retry; toasts for actions; 401 → login; a banner when the backend is unreachable. Accessibility: labels, keyboard navigation, status shown as text as well as colour.

### P8-T11 Calls page and Settings page (added; page 5)

- Calls page: all attempts with filters (the `calls/` folder in plan.md §8).
- Settings page: provider status cards with re-check; organization name; agent introduction with a preview of the opening line; calling preferences; retry configuration form; global pause switch; link to job settings. No secret values shown.

## 7. Tests

- **Backend:** stats against a fixture dataset with known counts (every metric); attention reasons; retry and cancel eligibility; settings validation; the status endpoint never contains secrets (assert none of the configured key values appear in any response body); global pause blocks dialing.
- **Frontend:** Vitest + Testing Library for StatusBadge mapping, filters and disabled-action reasons. Playwright E2E: login → upload → candidates → detail → settings, against a real backend with data created through the API.
- **Manual:** start a real call from the UI and watch status, transcript and summary appear.
- **Review check:** no hardcoded numbers in dashboard components; an empty database shows zeros.

## 8. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P8-AC1 | Dashboard metrics reflect actual database values | Script compares `/dashboard/stats` with direct SQL; UI matches API |
| P8-AC2 | Recruiter can initiate and monitor calls | Real call started from the UI; status changes shown within 5 s of each webhook |
| P8-AC3 | Recruiter can view screening information | Detail page shows answers, transcript and summary for a real call |
| P8-AC4 | Recruiter can retry eligible candidates | Retry enabled only when eligible and creates a new attempt; ineligible rows show the reason |
| P8-AC5 | Dashboard never relies on fake static statistics | Empty database → zeros; review check passes |
| P8-AC6 (added) | Settings show provider status without secrets | Status test plus visual check |
| P8-AC7 (added) | Global pause works | Pause → start and retry refused with a reason; worker doesn't dial queued attempts |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Metric definitions disputed | Definitions table and tooltips, agreed with the user |
| Polling load | Conditional intervals; lightweight endpoints |
| Recording links leaking | Backend proxy behind auth |

## 10. Open decisions

| Decision | Recommendation |
|---|---|
| Metric definitions | As in 5.1 |
| Component library | shadcn/ui for table, dialog and toast |
| Recording playback in the MVP | Only if recording is enabled and the agent's introduction discloses it |

## 11. Manual setup

None.

## 12. Exit

[Phase exit report](README.md#phase-exit-report) with screenshots of each page.
