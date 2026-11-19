# Automatic retries and callbacks (Phase 9)

How HireCall follows up a call that didn't finish the screening: when it tries again, when it
stops, and how a callback the candidate asked for is placed. Plan: [phase-09](phases/phase-09-auto-retry.md).

## 1. The flow

```text
call ends (webhook, reconciler, dial failure)          conversation finalized (phase 7)
        │                                                        │
        └──────────────► retry_service.evaluate(attempt) ◄───────┘
                              │  locks the attempt; runs once (retry_evaluated_at)
                              ▼
            classify (what happened) ─► decide (the rules below)
                              │
   retry ──► new attempt  retry_scheduled     type=retry     next_retry_at = retry time
   callback ► new attempt callback_requested  type=callback  next_retry_at = asked time (in window)
   exhausted ► this attempt → exhausted (status kept in provider_status, reason in end_reason)
   none ────► nothing; the reason is stored: retry_decision = no_retry:<reason>

cron dispatch_retries, every 5 minutes (worker)
   1. evaluate attempts nobody evaluated (lost webhook, worker down, no finalization)
   2. due attempts (FOR UPDATE SKIP LOCKED, 20 at a time) → re-check → queued → initiate_call
   3. queued attempts older than 10 minutes → enqueue again (same job id: never a second job)
```

An answered call is decided after finalization, because the decision needs the conversation's
outcome. If finalization never runs, the cron decides 15 minutes after the call with what was
stored. Other ended attempts are picked up by the cron after 2 minutes if the webhook path
missed them.

## 2. Outcome → decision

| What happened | Decision |
|---|---|
| No answer, busy | Retry while attempts are left, else **exhausted** |
| Failed: provider error, network, no free line, our dial refused | Retry (same limit) |
| Answered, but our stream never connected or nothing was stored | Retry (temporary failure) |
| Answered, nobody spoke (`no_response`, e.g. voicemail) | Retry |
| Answered, our STT/LLM/TTS failed before any answer (`error`) | Retry |
| Answered, hung up in the first 15 s with no answers | Retry |
| Answered, hung up later with no answers | No retry (`not_started`) |
| Screening completed | No retry |
| Partially completed (some answers, then hung up) | No automatic retry: **Needs attention** → manual retry (decision 2026-11-19) |
| Declined, opted out, wrong person, escalated | No retry |
| Callback with a time | Callback at that time, moved into calling hours if needed (§4) |
| Callback without a time ("call me later") | No automatic call: **Needs attention** (vague callback) |
| Invalid number | No retry. Exotel's callbacks don't say why a call failed, so today every `failed` is treated as temporary [Verify after KYC, Phase 10] |
| Cancelled by a recruiter | No retry |

A retry is never scheduled when the candidate opted out, was deleted, declined, is the wrong
person or the job is closed (`stop_reason`), or when a newer attempt already exists.

## 3. Limits

- **Calls per candidate** (`max_attempts`, default 3): first, retry and manual calls that were
  dialed. Cancelled attempts don't count. When a retryable outcome happens on the last allowed
  attempt, that attempt becomes `exhausted` and the candidate appears under Needs attention.
- **Manual calls count** (decision 2026-11-19). Past the limit, the API answers
  `max_attempts_reached`; the recruiter confirms ("Call anyway") and the request is sent again
  with `override_limit: true`.
- **Callbacks** (`max_callbacks`, default 2) don't count toward the calls. Past the limit, the
  callback isn't scheduled and shows as "Callback not scheduled" under Needs attention. An
  unanswered callback follows the normal retry rules.
- **Automatic retries off** (`enabled: false`): unanswered calls aren't retried. Callbacks the
  candidate asked for are still placed: the agent promised them.

## 4. Times

All times are stored in UTC; the calling window (Settings → Calling hours, default Mon–Sat
10:00–19:00 Asia/Kolkata) is evaluated in `APP_TIMEZONE`. `utils/calling_window.py` does the
maths; `utils/clock.py` is the injectable clock the tests freeze.

- **Retry time:** `interval_days` (2, 3 or 4) calendar days after the call ended. With
  **alternating slots** (default on) a morning call (before the window's midpoint, 14:30) is
  retried at the afternoon opening (14:30), an afternoon call at the morning opening (10:00);
  without it, at the same time of day. A day that isn't a calling day moves it to the next
  calling day; a time after the last slot moves it to the next opening.
- **Last slot:** nothing is scheduled later than 30 minutes before the window closes, so the
  5-minute dispatcher and a wait for a free line still fall inside the window.
- **Callback time:** the time the agent resolved (`callback_time_iso`, IST). Kept if it's in
  the future, within 14 days and inside the window. Outside the window it moves to the next
  slot and a note is stored on the attempt (`retry_note`) and added to the call summary, e.g.
  "Callback asked for Thu 19 Nov 21:00, outside calling hours (…); moved to Fri 20 Nov 10:00".
  The agent itself still confirms the time the candidate asked for (see §8).
- **At dispatch:** outside the window → moved to the next opening; calling paused or telephony
  not configured → left as it is until that changes. A retry or callback that reaches the
  dialer after the window closed (it waited for a free line) or while calling is paused goes
  back on the schedule instead of being cancelled.

## 5. Opt-out and other stops

Checked at three points: scheduling (`evaluate`), dispatch and the worker's initiation.

- The agent's opt-out is written at once at the end of the call; finalization cancels anything
  scheduled in the same transaction (`call_service.cancel_scheduled`).
- A recruiter's opt-out (candidate page, `PATCH /candidates/{id}`) cancels scheduled **and
  queued** calls in the same transaction.
- Declined, wrong person, deleted candidate, closed job: cancelled at dispatch
  (`failure_reason = ineligible:<reason>`).

## 6. No duplicates

1. One live or scheduled attempt per candidate (partial unique index, Phase 5).
2. Unique `(candidate_id, attempt_number)`.
3. `FOR UPDATE SKIP LOCKED` in the dispatcher; `evaluate` locks the ended attempt and runs once.
4. Job id `call:<attempt id>`; `initiate_call` dials only a `queued` attempt.

A manual call for a candidate with a scheduled retry or callback replaces it (the scheduled one
is cancelled with `replaced_by_manual_call`, same savepoint).

## 7. Resuming

A retry or callback starts the agent with the answers from earlier calls
(`retry_service.known_answers`: values with their status, and fields the candidate declined;
values a recruiter typed or imported are still asked). The opener matches:

- callback: "Hi Rahul, I'm an AI recruitment assistant calling on behalf of Acme. You asked us
  to call back about the Backend Developer role. Is now a good time?"
- earlier answers: "… calling again on behalf of Acme about a Backend Developer role. We spoke
  earlier, so I only have a few questions left. Is now a good time?"

The Settings page introduction template is used for first calls only.

## 8. Known limits

- The Realtime engine (trial) uses the matching opener but doesn't load earlier answers yet.
- When a callback is moved into calling hours, the candidate isn't told the new time during the
  call; the recruiter sees the note.
- Exotel doesn't tell an invalid number from other failures (§2).
- Retries of many candidates due at the same minute wait in line for `MAX_CONCURRENT_CALLS`
  lines (up to one hour, then `no_free_line`, which is retried like any failure).

## 9. Configuration

| Setting | Where | Default |
|---|---|---|
| Retry unanswered calls automatically | Settings → Retries and callbacks; `RETRY_ENABLED` | on |
| Calls per candidate | Settings; `MAX_CALL_ATTEMPTS` | 3 |
| Days between attempts (2/3/4) | Settings; `RETRY_INTERVAL_DAYS` | 2 |
| Callbacks per candidate | Settings; `MAX_CALLBACKS` | 2 |
| Alternate morning and afternoon | Settings; `RETRY_ALTERNATE_SLOTS` | on |
| Calling hours | Settings → Calling; `CALLING_DAYS`, `CALLING_HOUR_START/END` | Mon–Sat 10–19 |
| Interval unit (staging only) | `RETRY_INTERVAL_UNIT=minutes`; refused when `APP_ENV=production` | days |

## 10. Trying it on a real phone (staging)

1. In `.env`: `RETRY_INTERVAL_UNIT=minutes` (the interval becomes 2 minutes), then
   `docker compose restart backend worker`. Run `make tunnel`. Calls go out only inside calling
   hours (or widen them on the Settings page for the test).
2. **No answer → retry (P9-AC1, AC2):** call the tester's phone from the candidate page and
   don't answer. The call history shows "Retry scheduled" and the next attempt with its due
   time (end + 2 minutes). Within 5 minutes after that time the phone rings again.
3. **Exhausted (P9-AC3):** don't answer the second and third calls either. The third shows
   "No more attempts"; nothing rings again; the candidate is under Needs attention.
4. **Opt-out (P9-AC4):** with a retry scheduled, answer a manual call and say "please don't
   call me again". The scheduled retry is cancelled (`opted_out`), nothing rings again.
5. **Callback (P9-AC5):** answer and say "I'm busy, call me back in ten minutes". A callback
   attempt appears at that time, and the call opens with "you asked us to call back".
6. Set `RETRY_INTERVAL_UNIT=days` again afterwards.

Logs: `retry_evaluated` (decision per call), `retries_dispatched`, `call_rescheduled`,
`scheduled_calls_cancelled`, `queued_calls_requeued`.
