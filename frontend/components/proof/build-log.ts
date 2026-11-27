/**
 * The build log on /proof: the phase reports written during development (when the product was
 * still called HireCall), summarised. The Google Sheets sync of phase 7 was removed later, so it
 * is left out here.
 */

export type Phase = {
  n: number;
  title: string;
  date: string;
  summary: string;
  done: string[];
  checked: string[];
};

export const PHASES: Phase[] = [
  {
    n: 0,
    title: "Project foundation",
    date: "18 Nov 2026",
    summary:
      "The base every later phase is built on: the recruiter web app, the server, the database for candidates and calls, and a background worker that places calls.",
    done: [
      "Every part of the system starts with a single command.",
      "Every setting is checked at start-up; a missing or unsafe one stops it with a clear message.",
      "Health checks show at once whether the app, server, database and worker are working.",
      "Logs are structured and hide passwords and keys automatically.",
    ],
    checked: [
      "All 8 acceptance checks passed.",
      "Stopping the database, cache or worker was detected, and each recovered after a restart.",
      "19 automated checks passed.",
    ],
  },
  {
    n: 1,
    title: "Candidates, jobs and file import",
    date: "18 Nov 2026",
    summary:
      "Recruiters sign in, set up the job, add candidates by hand or from a spreadsheet, and search, filter and edit them.",
    done: [
      "Secure sign-in with protection against repeated wrong passwords.",
      "Import from .csv or .xlsx: columns matched automatically, every row previewed as valid, duplicate or invalid, with the reason, before anything is saved.",
      "Consent is recorded; calls are blocked without it.",
      "Each phone number belongs to one person, so re-importing a file never creates duplicates or overwrites results.",
    ],
    checked: [
      "A 10-row test file with mixed problems imported 8 valid candidates and reported the rest correctly.",
      "Re-importing the same file changed nothing.",
      "Every protected page and action refuses access without sign-in (18 checked).",
      "128 automated checks passed.",
    ],
  },
  {
    n: 2,
    title: "The AI screening conversation",
    date: "18 Nov 2026",
    summary:
      "The AI recruiter's conversation, first as text: it says it's an AI, checks it has the right person, asks the questions one at a time and records each answer.",
    done: [
      "Ten standard questions (location, company, experience, CTC, notice period and more), plus each job's own.",
      "Answers are recorded only from the candidate's own words, with the quote kept as evidence.",
      "Unclear answers are asked again, corrections are accepted, and answers are read back at the end.",
      "Clean exits for wrong person, not interested, call me later, don't call me again, and questions for a recruiter.",
      "Fixed rules decide the order and when the call is complete; the AI understands and phrases.",
    ],
    checked: [
      "48 of 48 test conversations passed; safety checks 100%.",
      "No question was ever asked twice.",
      "Average reply time 2.3 seconds (target 2.5 s).",
      "228 automated checks passed.",
    ],
  },
  {
    n: 3,
    title: "The AI's voice",
    date: "18 Nov 2026",
    summary:
      "A natural voice that is clear on a phone line, says Indian formats like lakhs and LPA properly, and starts speaking quickly.",
    done: [
      "Chosen in a listening test: 18 voices compared at real phone quality.",
      "A backup voice takes over automatically if the main one fails, even mid-call.",
      "Numbers, salaries, dates and phone numbers are spoken the Indian way (\"twelve lakhs\").",
      "Common lines are prepared in advance and play instantly; long replies play sentence by sentence.",
    ],
    checked: [
      "The chosen voice scored 4/5 for clarity on all 15 test lines.",
      "The backup voice took over within 2 seconds in a simulated outage.",
      "310 automated checks passed.",
    ],
  },
  {
    n: 4,
    title: "Understanding the candidate",
    date: "18 Nov 2026",
    summary:
      "Live speech recognition, so the AI understands Indian-English over a phone line quickly enough for a natural conversation.",
    done: [
      "Live transcription at phone quality, with job words (company, city, \"CTC\") boosted on every call.",
      "Our own end-of-speech detector, which roughly halves the wait before the AI replies.",
      "Keeps short answers like \"yes\" or \"mm-hmm\" when a yes/no is expected; ignores fillers.",
      "Reconnects on its own if the connection drops, without losing what was said.",
    ],
    checked: [
      "Key details correct in 90.8% of noisy test clips and 95% of clean clips.",
      "End of speech detected in about 0.85 seconds.",
      "385 automated checks passed.",
    ],
  },
  {
    n: 5,
    title: "Real phone calls",
    date: "19 Nov 2026",
    summary:
      "Real outbound phone calls with live two-way audio, every call's status tracked, and calls that must not be made refused.",
    done: [
      "Before every call: consent, not opted out, valid number, job active, inside calling hours, no other call in progress, checked again just before dialing.",
      "Only the allowed number of calls run at once; the rest wait in line.",
      "Every status update is stored once, even when it arrives twice or out of order.",
      "Stuck calls are found and closed automatically.",
    ],
    checked: [
      "All 8 acceptance checks passed on real calls: answered, hung up, rejected, rung out.",
      "Audio rated clear (4 out of 5).",
      "474 automated checks passed.",
    ],
  },
  {
    n: 6,
    title: "Live screening calls",
    date: "19 Nov 2026",
    summary:
      "Voice, listening and conversation together on a real call: CallZest calls the candidate, holds the screening and saves the transcript and answers.",
    done: [
      "Natural turn-taking: the AI waits for the candidate to finish and joins an answer split by a pause.",
      "If the candidate speaks over the AI it stops and listens; a short \"yes\" doesn't stop it.",
      "Silence is handled politely; long calls are wrapped up with a read-back.",
      "The transcript is saved line by line; recruiters can watch live and end a call.",
    ],
    checked: [
      "First sound after the candidate stops speaking: 0.72 seconds (median).",
      "Full reply: 3.25 seconds (median), within the agreed 3.5 s.",
      "All 51 test conversations passed; 576 automated checks passed.",
    ],
  },
  {
    n: 7,
    title: "Final results",
    date: "19 Nov 2026",
    summary:
      "After every call the answers are checked once more against the whole conversation, saved to the candidate and summarised.",
    done: [
      "A careful second pass over the full transcript: every value needs a quote; anything the candidate didn't say is rejected.",
      "Confirmed answers win, later corrections are taken, and two different answers go to the recruiter to choose.",
      "A short summary of each call, and the candidate's status updated.",
      "All updates for a call are saved together, and an older call finished late never overwrites a newer one.",
    ],
    checked: [
      "A real complete call was finalised correctly.",
      "Automated checks for every rule above.",
    ],
  },
  {
    n: 8,
    title: "Dashboard and recruiter controls",
    date: "19 Nov 2026",
    summary:
      "Everything in one place: numbers at a glance, what needs attention, live calls, and the recruiter's controls.",
    done: [
      "Dashboard with key numbers for today, 7 days or all time, recent activity, live calls and charts.",
      "Needs attention: callbacks due, answers that disagree, questions for a recruiter, failed calls.",
      "Calling up to 20 candidates at once after a confirmation that shows who is called and who is skipped.",
      "Settings: pause all calling, calling days and hours, the AI's introduction, retries.",
    ],
    checked: [
      "Dashboard numbers: 9 of 9 match the database exactly.",
      "Pausing calling blocks every way of starting a call.",
      "689 automated checks and a full browser test passed.",
    ],
  },
  {
    n: 9,
    title: "Automatic retries and callbacks",
    date: "19 Nov 2026",
    summary:
      "Unanswered calls are tried again, callbacks happen when the candidate asked, and nobody who opted out is ever called again.",
    done: [
      "Unanswered, busy or failed calls are retried after 2, 3 or 4 days, inside calling hours, alternating morning and afternoon.",
      "\"Call me tomorrow at 5\" becomes a callback at that time; vague requests go to the recruiter.",
      "On a retry the AI doesn't ask again what it already knows.",
      "Several protections make sure the same call is never dialed twice, even after a restart.",
    ],
    checked: [
      "Retry timing tested for 2, 3 and 4 days, weekends and the end of calling hours.",
      "Four simultaneous decisions on the same call created exactly one retry.",
      "771 automated checks and the browser test passed.",
    ],
  },
];

/** Moments in the live call recording, for the chapter buttons. */
export const MOMENTS: { at: number; label: string }[] = [
  { at: 0, label: "The candidate in the app" },
  { at: 7, label: "Starting the call" },
  { at: 16, label: "Dialling" },
  { at: 21, label: "The phone is answered" },
  { at: 36, label: "The AI speaks (audio)" },
  { at: 84, label: "Transcript fills in live" },
  { at: 105, label: "Live call on the dashboard" },
  { at: 173, label: "The call ends" },
];
