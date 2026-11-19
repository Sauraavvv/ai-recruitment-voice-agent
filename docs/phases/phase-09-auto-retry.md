# Phase 9: Automatic retry

| | |
|---|---|
| Source | plan.md §10 Phase 9, Module I, Module F call statuses |
| Depends on | P5 (orchestration), P7 (final statuses), P8 (settings UI) |
| Unlocks | P10 |
| Size / risk | M / Medium |

## 1. Goal

Unanswered calls are retried automatically after the configured interval, callbacks happen when the candidate asked, limits are enforced, declined or opted-out candidates are never called again, and no retry is ever scheduled twice.

## 2. Entry criteria

P5, P7 and P8 accepted.

## 3. Scope

- **In:** plan.md tasks 1–8, resuming known answers on retry, the calling window, a testable clock.
- **Out:** "best time to call" scheduling; SMS or WhatsApp follow-ups.

## 4. Deliverables

```text
backend/app/
  services/  retry_service.py (evaluate, schedule, dispatch)
  utils/     clock.py  calling_window.py
  workers/   retry_worker.py (dispatch cron)
frontend/    retry status in the candidates table, detail timeline, settings form wired up
docs/retries.md
```

## 5. Retry configuration (P9-T1)

Stored in `app_settings.retry` (editable on the Settings page). Defaults from plan.md Module I and env:

```json
{
  "enabled": true,
  "max_attempts": 3,
  "retry_interval_days": 2,
  "retry_on": ["no_answer", "busy", "temporary_failure"],
  "stop_on": ["completed", "candidate_declined", "invalid_number", "opted_out"],
  "max_callbacks": 2,
  "calling_window": {
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    "start": "10:00",
    "end": "19:00",
    "timezone": "Asia/Kolkata"
  }
}
```

- `retry_interval_days` must be 2, 3 or 4 (plan.md: default 2, configurable to 3 or 4).
- `max_callbacks` and `calling_window` are [Proposed]. The window needs the user's confirmation against applicable calling-hour rules **[Decision]**.

## 6. Outcome → retry decision (P9-T3)

| Attempt outcome | Retry? |
|---|---|
| `no_answer` | Yes, if attempts < max |
| `busy` | Yes |
| Temporary failure: provider 5xx or network error; our STT/LLM/TTS failed before screening started; call dropped in the first 15 s | Yes |
| Invalid number | No; candidate flagged |
| Completed, screening completed | No |
| Completed, screening partially completed (candidate hung up midway) | No automatic retry; appears in "needs attention" for a manual retry **[Decision]** |
| Declined | No |
| Opted out | No, and anything already scheduled is cancelled |
| Callback requested | Scheduled for the requested time, not the interval |
| Wrong person | No; flagged |
| Cancelled by recruiter | No |

Which provider failure reasons mean "invalid number" and which mean "temporary" comes from the P5 status mapping **[Verify Exotel's detailed status values]**.

## 7. Tasks

### P9-T2 Implement the retry scheduler

- `retry_service.evaluate(attempt)` runs when an attempt reaches a terminal status (webhook) and again after finalization (P7). It's idempotent.
- If eligible, it creates the next attempt immediately: `call_status=retry_scheduled`, `attempt_type=retry`, `attempt_number = n + 1`, `next_retry_at = next_window_slot(ended_at + interval)`.
- Dispatcher (ARQ cron, every 5 minutes):
  ```sql
  SELECT … FROM call_attempts
  WHERE call_status IN ('retry_scheduled', 'callback_requested') AND next_retry_at <= now()
  ORDER BY next_retry_at
  FOR UPDATE SKIP LOCKED
  LIMIT 20
  ```
  For each row: re-check eligibility (opt-out, consent, deletion, job active, calling enabled, window) → `queued` → enqueue `initiate_call` (job id de-duplication). Outside the window → move `next_retry_at` to the next window start.
- All time calculations go through an injectable `Clock`. Times are stored in UTC; the window is evaluated in Asia/Kolkata.

### P9-T4 Implement attempt limits

- Count `initial`, `retry` and `manual` attempts per candidate per job toward `max_attempts` **[Decision]**. Recruiters can override for a manual retry after a confirmation.
- When a retryable outcome happens on the last allowed attempt, that attempt's `call_status` becomes `exhausted`. The raw provider status stays in `provider_status` and the reason in `end_reason`. No new attempt is created, and the candidate appears in the attention list.

### P9-T5 Prevent duplicate retry jobs

Four layers:
1. Partial unique index: one live or scheduled attempt per candidate (P5).
2. Unique `(candidate_id, attempt_number)`.
3. `FOR UPDATE SKIP LOCKED` in the dispatcher.
4. ARQ job id = attempt id.

Concurrent `evaluate` calls for the same attempt produce one new attempt.

### P9-T6 Handle callback requests separately

- The agent supplies `callback_time_iso` (P2). Validate: in the future, within 14 days, inside the calling window. Otherwise move to the nearest window slot and note it in the summary.
- Vague requests ("call me later") get no automatic time; they become an attention item for the recruiter.
- Create `attempt_type=callback`, `call_status=callback_requested`, `next_retry_at=<requested time>`. Callbacks don't count toward `max_attempts`; they're capped by `max_callbacks`.
- An unanswered callback follows the normal retry rules from then on.
- **Resume:** the callback or retry session starts the agent with the fields already known (P6 §5.9) and a matching opener: "Hi Rahul, you asked us to call back about the {job title} role. Is now a good time?"

### P9-T7 Handle opt-outs

- An opt-out (from the agent or a recruiter) does, in one transaction: `candidates.opted_out = true` and every scheduled attempt → `cancelled` with reason `opted_out`.
- Checked at three points: scheduling, dispatch and worker initiation.
- Opted-out candidates can't be re-enabled from the UI in the MVP.

### P9-T8 Display retry status in the dashboard

- Candidates table: "Retry scheduled · 20 Nov 10:30 · attempt 2 of 3", "Callback · 19 Nov 17:00", "Exhausted".
- Detail page timeline shows scheduled attempts with a cancel button.
- Settings retry form is live.
- Attention list includes exhausted candidates and vague callback requests.

### P9-T9 Testable clock and fast-forward (added)

- Unit and integration tests use an injectable/frozen clock (`time-machine`) for 2-, 3- and 4-day intervals across window edges (Saturday evening → Monday when Sunday is excluded; just before the window closes; UTC/IST date boundary).
- Staging-only `RETRY_INTERVAL_UNIT=minutes` (refused when `APP_ENV=production`) lets a real no-answer → retry cycle run in minutes on a tester's phone.

## 8. Tests

- **Unit:** outcome table; interval and window maths with edge cases; attempt limit and `exhausted`; callback validation; opt-out cancellation; `evaluate` idempotency; concurrent `evaluate` → one attempt.
- **Integration:** a `no-answer` webhook → scheduled attempt; dispatcher only picks due attempts; worker restarted mid-dispatch → no duplicate dial.
- **Real calls (staging, minutes override):** don't answer → retry arrives after the configured minutes; third miss → exhausted; say "don't call me again" → scheduled retry cancelled.

## 9. Acceptance criteria

| ID | Criterion | How to verify |
|---|---|---|
| P9-AC1 | Eligible no-answer calls are scheduled | Real unanswered call → `retry_scheduled` attempt with the correct `next_retry_at` |
| P9-AC2 | Retry happens after the configured days | Frozen-clock tests for 2/3/4 days; staging minutes run with a real call |
| P9-AC3 | Maximum attempts are enforced | Three misses → `exhausted`; no fourth dial |
| P9-AC4 | Declined and opted-out candidates are never retried | Tests at all three checkpoints; a real opt-out cancels a scheduled attempt |
| P9-AC5 | Callbacks are handled at the requested time where feasible | "Tomorrow at 5 PM" → dial at 17:00 IST next day (scaled in staging); out-of-window request moved and noted |
| P9-AC6 (added) | No duplicate retries | Concurrency test and worker-restart test pass |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Timezone mistakes | UTC storage, timezone-aware maths, boundary tests |
| Duplicate dials after restarts | Four-layer protection |
| Calling at bad times or against rules | Window enforced at dispatch and at initiation; user confirms the window |
| Candidate annoyance | Attempt cap; opt-out honoured within the same call |

## 11. Open decisions

| Decision | Recommendation |
|---|---|
| Calling window | Mon–Sat 10:00–19:00 IST, confirmed with whoever handles compliance |
| Auto-retry partially completed calls | No; manual retry from the attention list |
| Manual attempts count toward the max | Yes, with a recruiter override |
| Max callbacks | 2 |
| Vary time of day between retries | Optional: alternate morning and afternoon slots |

## 12. Manual setup

None.

## 13. Exit

[Phase exit report](README.md#phase-exit-report).

## 14. As built (2026-11-19)

Design and operations: [retries.md](../retries.md). Exit report: [progress.md](../progress.md).

**Decisions (user, 2026-11-19):** all four §11 recommendations. A partially completed call is not
retried automatically (Needs attention → manual retry); manual calls count toward
`max_attempts`, with a confirmed override; at most 2 callbacks, which don't count; retries
alternate between morning and afternoon. The calling window stays as decided in Phase 5
(Mon–Sat 10:00–19:00 IST, editable on the Settings page).

**Deviations from the plan, and why:**
- `app_settings.retry` holds `enabled`, `max_attempts`, `interval_days`, `max_callbacks`,
  `alternate_slots`. `retry_on` / `stop_on` aren't settings: the outcome table (§6) is code, and
  is tested as one table. The window stays in `general.calling` (whole hours, as in Phase 8).
- No `time-machine` dependency: everything takes an injectable `Clock` (`utils/clock.py`,
  `FrozenClock` in tests). The `retry_worker` cron reads `ctx["clock"]` if one is set.
- Migration `0007_retries`: `call_attempts.retry_decision`, `retry_note`,
  `retry_evaluated_at` (idempotency and "why no retry" in the UI) and a partial index for the
  dispatcher. Existing ended attempts were marked `before_phase_9`, so old test calls are never
  retried.
- `exhausted` is a terminal status; `call_state.mark_exhausted` moves the last attempt there.
  Scheduled attempts may only become `queued` or `cancelled`; `queued` may go back to scheduled
  when the window closed or calling was paused before it dialed (rescheduled, not cancelled).
- More outcomes are retryable than the table lists: nobody spoke (`no_response`), and an
  answered call whose conversation wasn't stored. A call answered and hung up after 15 s with
  no answers is not retried (`not_started`).
- Callbacks: a time outside the window moves to the next slot with a note on the attempt and in
  the summary. A callback past `max_callbacks` or more than 14 days ahead becomes the new
  attention reason `callback_not_scheduled`. Callbacks are placed even when automatic retries
  are switched off.
- A manual call for a candidate with a scheduled retry or callback replaces it (the Call
  button isn't blocked by a schedule). A recruiter's opt-out also cancels queued calls.
- Dashboard: "Unanswered" and "Failed" look at the latest call that isn't only scheduled
  (otherwise every unanswered candidate would vanish from the tile as soon as its retry is
  scheduled); `exhausted` counts by its end reason. `make dashboard-check` uses the same rules.
- Resume: the pipeline engine loads earlier answers (values and declined fields from calls,
  not recruiter-typed values). The Realtime trial engine gets the matching opener only.
- `RETRY_INTERVAL_UNIT=minutes` (staging) is refused in production by config validation.
- Not done: the agent doesn't tell the candidate when it moves a callback into calling hours;
  invalid numbers can't be told apart from other Exotel failures until KYC (Phase 10).
