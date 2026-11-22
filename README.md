# CallZest

AI recruitment voice calling agent.

Recruiters add or import candidates, and an AI recruiter calls them on a real phone line, holds a short screening conversation in English, and records structured answers, a transcript and a summary. Results appear in the app.

**Status:** Phases 0 to 9 are complete. Phase 10 (real-world testing and going live) is next.

## Phases

- [Phase 0: Project foundation](#phase-0-project-foundation)
- [Phase 1: Candidates, jobs and file import](#phase-1-candidates-jobs-and-file-import)
- [Phase 2: The AI screening conversation](#phase-2-the-ai-screening-conversation)
- [Phase 3: The AI's voice](#phase-3-the-ais-voice)
- [Phase 4: Understanding the candidate (speech to text)](#phase-4-understanding-the-candidate-speech-to-text)
- [Phase 5: Real phone calls](#phase-5-real-phone-calls)
- [Phase 6: Live screening calls](#phase-6-live-screening-calls)
- [Phase 7: Final results and Google Sheet sync](#phase-7-final-results-and-google-sheet-sync)
- [Phase 8: Dashboard and recruiter controls](#phase-8-dashboard-and-recruiter-controls)
- [Phase 9: Automatic retries and callbacks](#phase-9-automatic-retries-and-callbacks)

## Phase 0: Project foundation

*Completed 18 November 2026*

We set up the base that every later phase is built on: the recruiter web app, the server behind it, the database that stores candidates and calls, and a background worker for jobs that run on their own, such as placing calls.

### What was done

- All parts of the system start together with a single command, on any developer machine.
- Every setting is checked when the system starts. A missing or unsafe setting stops it with a clear message instead of failing later.
- Health checks report whether the web app, server, database and background worker are working, so a problem is visible at once.
- Activity logs are structured and hide passwords and keys automatically.
- Setup, architecture and integration notes were written so the work can be picked up by anyone.

### How it was done

- We built a minimal but complete skeleton first, so every later feature lands in a tested structure instead of being bolted on.
- Secrets are kept out of the code repository from day one.
- We stopped each part on purpose and confirmed the health check reported it correctly, then restarted it and confirmed recovery.

### How we checked it

- All 8 acceptance checks for this phase passed.
- Stopping the database, the cache or the background worker was detected; each recovered after a restart.
- 19 automated checks passed; code style and type checks were clean.

### Next

- Phase 1: candidates, jobs and file import.

## Phase 1: Candidates, jobs and file import

*Completed 18 November 2026*

Recruiters can now sign in, set up the job, add candidates by hand or import them from a spreadsheet, and search, filter and edit them. This is the data every screening call works from.

### What was done

- Secure recruiter sign-in with protection against repeated wrong passwords.
- Job settings: title, company, location, experience and the screening questions.
- Candidate list with search by name, phone or email, filters and sorting.
- Import from .csv or .xlsx: columns are matched automatically, and a preview shows every row as valid, duplicate or invalid, with the reason, before anything is saved.
- Consent: the recruiter confirms the candidates agreed to be contacted. Calls are blocked without it.
- Candidate page with details, editing, opt-out and delete.

### How it was done

- Each phone number belongs to one person across all jobs, so re-importing a file never creates duplicates or overwrites screening results.
- Deleting a candidate hides them and blocks calls, but keeps their history.
- Every row error names the row, the field and the reason (for example: row 4, phone, not a valid number).

### How we checked it

- A 10-row test file with mixed problems imported 8 valid candidates and reported the rest correctly.
- Re-importing the same file changed nothing.
- Data survived a full restart of the system.
- Every protected page and action refuses access without sign-in (18 checked).
- 128 automated checks passed.

### Next

- Phase 2: the AI screening conversation.

## Phase 2: The AI screening conversation

*Completed 18 November 2026*

We built the AI recruiter's conversation logic, first as text. It introduces itself as an AI, checks it is speaking with the right person, asks the job's screening questions one at a time, and records each answer in a structured form.

### What was done

- The ten standard questions: location, current company, total and relevant experience, current and expected salary (CTC), notice period, reason for change, interest in the role and interview availability. Jobs can add their own questions.
- Answers are recorded only from the candidate's own words, with the exact quote kept as evidence.
- Unclear answers are asked again (at most twice); a salary range is clarified once; corrections are accepted and the earlier answer is kept in the history.
- At the end the AI reads the answers back for confirmation.
- Clean exits for: wrong person, not interested, "call me later" (with a time, or flagged for a recruiter if vague), "don't call me again", and questions only a recruiter can answer.
- A short, neutral summary of every conversation.

### How it was done

- The order of questions, what is still missing and when the call is complete are decided by fixed rules, not by the AI. The AI understands the answers and phrases the replies. This keeps calls predictable and prevents repeated questions.
- Fixed lines (greeting, the AI disclosure, closings) are always said word for word.
- We wrote 16 realistic conversations, including difficult ones, and ran each three times against the live AI.

### How we checked it

- 48 out of 48 test conversations passed; safety checks 100%.
- No question was ever asked twice.
- Average reply time 2.3 seconds (target agreed: 2.5 s); during calls a short "Okay" plays while the AI thinks.
- 228 automated checks passed.

### Next

- Phase 3: giving the AI a voice.

## Phase 3: The AI's voice

*Completed 18 November 2026*

We gave the AI recruiter a natural speaking voice that sounds clear on a phone line, handles Indian formats such as lakhs and LPA, and starts speaking quickly.

### What was done

- The voice was chosen in a listening test: 18 voices compared at real phone quality; the chosen voice scored 4 out of 5 for clarity on all 15 test lines.
- If the main voice ever fails, a backup voice takes over automatically, even in the middle of a call.
- Numbers, salaries, dates, times and phone numbers are spoken the Indian way ("twelve lakhs", "C T C").
- Common lines (greetings, "Okay", "Got it", closings) are prepared in advance and play instantly.

### How it was done

- Long replies are split into sentences: the first sentence plays while the next is still being prepared.
- Every voice request has a time limit and a retry; if speech still fails, the call plays a short apology instead of going silent.

### How we checked it

- All acceptance checks passed, including the listening test.
- Backup voice took over within 2 seconds during a simulated outage.
- 310 automated checks passed.

### Next

- Phase 4: understanding what the candidate says.

## Phase 4: Understanding the candidate (speech to text)

*Completed 18 November 2026*

We connected live speech recognition so the AI understands what candidates say over a phone line, quickly enough for a natural conversation.

### What was done

- Live transcription of Indian-English speech at phone quality.
- Detects when the candidate has finished speaking, so the AI replies at the right moment.
- Ignores fillers ("umm") and keeps short answers such as "yes" or "mm-hmm" when a yes/no answer is expected.
- Reconnects on its own if the connection drops, without losing what was said.

### How it was done

- We compared five settings on 78 test recordings with three Indian-English voices and realistic line noise, and picked the most accurate one.
- We added our own end-of-speech detector, which roughly halves the waiting time before the AI replies.
- Job-specific words (company names, city, "CTC", "notice period") are boosted on every call.

### How we checked it

- Key details (numbers, names, durations) correct in 90.8% of noisy test clips and 95% of clean clips.
- End of speech detected in about 0.85 seconds with our detector.
- Silence, dropped connections and two calls at once all handled.
- 385 automated checks passed.

### Still open

- Accuracy on recordings of real people (only synthetic voices were measured so far).

### Next

- Phase 5: placing real phone calls.

## Phase 5: Real phone calls

*Completed 19 November 2026*

CallZest can now place real outbound phone calls with live two-way audio, follow each call's status, and refuse calls that must not be made.

### What was done

- Outbound calls through our telephony partner, with live audio both ways.
- Every call's status is tracked: queued, dialing, ringing, on the call, completed, not answered, busy or failed.
- Before every call the system checks: consent recorded, not opted out, valid number, job active, inside calling hours (Mon to Sat, 10 AM to 7 PM IST), and no other call for that person in progress. The check is repeated just before dialing.
- Only the allowed number of calls run at the same time; the rest wait in line.
- Calls that get stuck are found and closed automatically.

### How it was done

- Every status update from the phone network is stored once, even if it arrives twice or out of order.
- We tested on real calls: answered, hung up by the candidate, rejected, rung out, and an unverified number.

### How we checked it

- All 8 acceptance checks passed on real calls to the tester's phone.
- Audio clear (4 out of 5); the call dropped within 2 seconds after our side hung up.
- 474 automated checks passed.

### Still open

- Account verification with the telephony partner before calling real candidates (planned before go-live).

### Next

- Phase 6: the full screening conversation over a real call.

## Phase 6: Live screening calls

*Completed 19 November 2026*

The voice, the listening and the conversation now work together on a real phone call: CallZest calls the candidate, holds the screening conversation and saves the transcript and answers.

### What was done

- Natural turn-taking: the AI waits until the candidate has finished, and joins two parts of an answer split by a pause.
- Interruptions: if the candidate speaks over the AI, it stops and listens; short "yes" or "okay" sounds don't stop it.
- While the AI thinks, a short "Okay" or "Got it" plays, and "One moment" if it takes longer.
- Silence handling: the question is repeated, then "are you still there?", then a polite goodbye.
- Long calls are wrapped up with a read-back at 10 minutes.
- The transcript is saved line by line during the call; recruiters can watch it live and end a call.
- "Call now" on the candidate page.

### How it was done

- Each call runs its own session that listens, decides and speaks at the same time, and cleans up fully when the call ends.
- We made 7 real calls and adjusted the conversation from what we heard.

### How we checked it

- First sound after the candidate stops speaking: 0.72 seconds (median).
- Full reply: 3.25 seconds (median), within the agreed 3.5 s.
- All 51 test conversations passed after the changes.
- 576 automated checks passed.

### Still open

- Calls by more testers, opt-out and noisy-background tests, and two calls at once (planned before go-live).

### Next

- Phase 7: final results and the Google Sheet.

## Phase 7: Final results and Google Sheet sync

*Completed 19 November 2026. The Google Sheet copy was removed on 22 November 2026: the app is
now the only record of candidates.*

After every call, the answers are checked once more against the whole conversation, saved to the candidate, summarised, and copied to the team's Google Sheet.

### What was done

- A careful second pass over the complete transcript after the call. Every value must come with a quote from the candidate; anything not said by the candidate is rejected.
- Answers confirmed during the call win; later corrections are taken; if the candidate gave two different answers, the recruiter is asked to choose.
- A short summary of each call, with a facts-only version if needed.
- Candidate status updated: completed, partially completed, callback requested, declined, opted out or wrong person.
- Every candidate is copied to the team's Google Sheet (23 columns) and kept up to date after every change: new, edited, imported, called or finalised.

### How it was done

- All updates for one call are saved together, so a candidate is never left half-updated.
- If the sheet is unreachable, changes wait and are retried automatically (from 1 minute up to 6 hours). Nothing is lost.
- An older call finished late never overwrites a newer one.

### How we checked it

- A real complete call was finalised and copied to the sheet correctly.
- Sheet comparison tool: database and sheet match.
- Automated checks for every rule above.

### Still open

- A real partially completed call, and a test of removing and restoring sheet access.

### Next

- Phase 8: dashboard and recruiter controls.

## Phase 8: Dashboard and recruiter controls

*Completed 19 November 2026*

Recruiters now see everything in one place and control calling themselves: numbers at a glance, what needs attention, live calls, and settings.

### What was done

- Dashboard: key numbers (candidates, screened, interested, calls completed, on call, waiting, unanswered, failed, retries) for today, 7 days or all time; what needs attention; recent activity; live calls; charts.
- Needs attention: callbacks due, answers that disagree, questions for a recruiter, failed calls, incomplete screenings, wrong person, attempts used up, sheet problems.
- Candidate list with call status, last call, Call / Retry buttons that explain why they're disabled, and calling up to 20 candidates at once after a confirmation that lists who will be called and who is skipped.
- Candidate page: summary, answers with the candidate's words, call history with Retry / Cancel / End call, transcript.
- Calls page with filters.
- Settings: pause all calling, calling days and hours, calls at the same time, the AI's introduction with a live preview, retries, and the Google Sheet.

### How it was done

- Pages refresh every 3 seconds while a call is live, every 30 seconds otherwise.
- Every number on the dashboard was cross-checked against the database.
- A full click-through test runs the main recruiter flow in a real browser.

### How we checked it

- Dashboard numbers: 9 of 9 match the database exactly.
- Pausing calling blocks every way of starting a call.
- No password or key is ever shown in the app.
- 689 automated checks and the browser test passed.

### Still open

- A real call started from the app.

### Next

- Phase 9: automatic retries and callbacks.

## Phase 9: Automatic retries and callbacks

*Completed 19 November 2026*

Calls that aren't answered are tried again automatically, callbacks happen at the time the candidate asked for, and nobody who declined or opted out is ever called again.

### What was done

- Not answered, busy or failed calls are retried after 2, 3 or 4 days (recruiter's choice), inside calling hours, alternating morning and afternoon.
- At most 3 calls per candidate (configurable). After the last one the candidate is marked "No more attempts" and appears under Needs attention. A recruiter can still call once more after confirming.
- Callbacks are placed at the time the candidate asked for ("tomorrow at 5"). A time outside calling hours moves to the next opening, with a note in the summary. Up to 2 callbacks; vague requests go to the recruiter.
- A call where the candidate hung up halfway isn't retried automatically; it appears under Needs attention.
- On a retry or callback, the AI doesn't ask again what it already knows, and opens with "you asked us to call back…".
- Everywhere in the app: "Retry · 20 Nov, 10:00 · attempt 2 of 3", "Callback · 20 Nov, 17:00", and why a call wasn't retried.

### How it was done

- The decision is made once per call, right after it ends, and checked again every 5 minutes so nothing is missed.
- Opt-out and declined are checked when a retry is scheduled, when it is due, and just before dialing.
- Several protections make sure the same call is never dialed twice, even if the system restarts in the middle.

### How we checked it

- Retry timing tested for 2, 3 and 4 days, weekends and the end of calling hours.
- Three misses lead to "No more attempts" and no fourth call.
- Four simultaneous decisions on the same call created exactly one retry.
- 771 automated checks and the browser test passed.

### Still open

- Retry, callback and opt-out tests on a real phone (prepared, waiting for a test session).

### Next

- Phase 10: real-world testing and going live.
