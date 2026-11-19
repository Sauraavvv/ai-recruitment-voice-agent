export const SCREENING_STATUS_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  partially_completed: "Partially completed",
  completed: "Completed",
  declined: "Declined",
  opted_out: "Opted out",
  callback_requested: "Callback requested",
  wrong_person: "Wrong person",
};

export function yesNo(value: boolean | null | undefined) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "—";
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export const CALL_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  queued: "Queued",
  initiating: "Dialling",
  ringing: "Ringing",
  in_progress: "On call",
  completed: "Completed",
  no_answer: "No answer",
  busy: "Busy",
  failed: "Failed",
  cancelled: "Cancelled",
  callback_requested: "Callback requested",
  retry_scheduled: "Retry scheduled",
  exhausted: "No more attempts",
};

/** Calls that are still happening (or about to). */
export const LIVE_CALL_STATUSES = new Set([
  "pending",
  "queued",
  "initiating",
  "ringing",
  "in_progress",
]);

export const END_REASON_LABELS: Record<string, string> = {
  agent_completed: "Screening finished",
  candidate_hangup: "Candidate hung up",
  declined: "Not interested",
  opted_out: "Asked not to be called",
  callback_scheduled: "Callback scheduled",
  wrong_person: "Wrong person",
  silence_timeout: "No response",
  max_duration: "Time limit reached",
  escalated: "Needs a recruiter",
  no_answer: "No answer",
  busy: "Busy",
  invalid_number: "Invalid number",
  provider_failed: "Call failed",
  technical_failure: "Technical problem",
  cancelled: "Cancelled",
};

/** Status pill colours; the label is always shown, colour only supports it. */
export const SCREENING_STATUS_TONE: Record<string, string> = {
  completed: "bg-[#0ca30c]/15 text-[#5fd35f]",
  partially_completed: "bg-amber-500/15 text-amber-300",
  in_progress: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  callback_requested: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  declined: "bg-red-500/15 text-red-300",
  opted_out: "bg-red-500/15 text-red-300",
  wrong_person: "bg-red-500/15 text-red-300",
};

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

/** Call statuses that are about to dial or on the line (poll fast while one is visible). */
export const ACTIVE_CALL_STATUSES = new Set(["queued", "initiating", "ringing", "in_progress"]);

/** Call status pill colours; the label is always shown as text too. */
export const CALL_STATUS_TONE: Record<string, string> = {
  completed: "bg-[#0ca30c]/15 text-[#5fd35f]",
  in_progress: "bg-[#0ca30c]/15 text-[#5fd35f]",
  ringing: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  initiating: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  queued: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  pending: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  retry_scheduled: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  callback_requested: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  no_answer: "bg-amber-500/15 text-amber-300",
  busy: "bg-amber-500/15 text-amber-300",
  failed: "bg-red-500/15 text-red-300",
  exhausted: "bg-red-500/15 text-red-300",
  cancelled: "bg-white/5 text-zinc-400",
};

export const ATTEMPT_TYPE_LABELS: Record<string, string> = {
  initial: "First call",
  manual: "Manual",
  retry: "Retry",
  callback: "Callback",
};

export const ATTENTION_LABELS: Record<string, string> = {
  callback_due: "Callback due",
  data_conflict: "Answers disagree",
  unanswered_question: "Question for a recruiter",
  vague_callback: "Callback, no time given",
  technical_failure: "Call failed",
  partially_completed: "Screening incomplete",
  wrong_person: "Wrong person",
  attempts_exhausted: "No more attempts",
  callback_not_scheduled: "Callback not scheduled",
  sheets_sync_failed: "Sheet sync failed",
};

/** Why an ended call was or wasn't followed up automatically (phase-09, `retry_decision`). */
const NO_RETRY_LABELS: Record<string, string> = {
  completed: "screening complete",
  declined: "not interested",
  opted_out: "asked not to be called",
  wrong_person: "wrong person",
  partial: "screening incomplete: call again from here if needed",
  cancelled: "cancelled",
  invalid_number: "invalid number",
  vague_callback: "callback without a time: call when it suits them",
  callback_limit: "callback limit reached",
  callback_too_far: "callback more than 14 days ahead",
  retry_disabled: "automatic retries are off",
  superseded: "a newer call was made",
  already_scheduled: "another call was already scheduled",
  candidate_deleted: "candidate deleted",
  job_inactive: "job closed",
  escalated: "needs a recruiter",
  not_started: "answered, but the screening didn't start",
  replaced_by_manual_call: "replaced by a manual call",
  max_attempts_reached: "no attempts left",
};

export function retryDecisionLabel(code: string | null | undefined): string | null {
  if (!code || code === "before_phase_9") return null;
  if (code === "retry_scheduled") return "Retry scheduled";
  if (code === "callback_scheduled") return "Callback scheduled";
  if (code === "exhausted") return "No more attempts";
  const reason = code.replace(/^no_retry:/, "").replace(/^ineligible:/, "");
  return `Not retried: ${NO_RETRY_LABELS[reason] ?? reason.replace(/_/g, " ")}`;
}

/** "20 Nov, 10:30" (the viewer's timezone, like every other date on the page). */
export function shortDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

type RetryStatusLike = {
  kind: "retry" | "callback" | "exhausted";
  at?: string | null;
  attempt?: number | null;
  max_attempts: number;
  attempts_made: number;
};

/** phase-09 P9-T8: "Retry · 20 Nov, 10:30 · attempt 2 of 3", "Callback · 19 Nov, 17:00",
 *  "No more attempts (3 of 3)". */
export function retryStatusText(status: RetryStatusLike | null | undefined): string | null {
  if (!status) return null;
  if (status.kind === "exhausted")
    return `No more attempts (${status.attempts_made} of ${status.max_attempts})`;
  if (status.kind === "callback") return `Callback · ${shortDate(status.at)}`;
  const which = status.attempt ? ` · attempt ${status.attempt} of ${status.max_attempts}` : "";
  return `Retry · ${shortDate(status.at)}${which}`;
}

export const FIELD_LABELS: Record<string, string> = {
  current_location: "Location",
  current_company: "Current company",
  total_experience: "Total experience",
  relevant_experience: "Relevant experience",
  current_ctc: "Current CTC",
  expected_ctc: "Expected CTC",
  notice_period: "Notice period",
  reason_for_change: "Reason for change",
  interested: "Interested",
  interview_availability: "Interview availability",
};

export const fieldLabel = (key: string) =>
  FIELD_LABELS[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** A screening value as the recruiter reads it (units for numbers, Yes/No). */
export function fieldValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (key.endsWith("_ctc")) return `${value} LPA`;
    if (key.endsWith("_experience")) return `${value} yrs`;
  }
  return String(value);
}

export const FIELD_STATUS_LABELS: Record<string, string> = {
  answered: "Answered",
  confirmed: "Confirmed",
  declined: "Declined",
  unknown: "Unclear",
  missing: "Missing",
  conflict: "Conflict",
};

export const FIELD_STATUS_TONE: Record<string, string> = {
  confirmed: "bg-[#0ca30c]/15 text-[#5fd35f]",
  answered: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  declined: "bg-white/5 text-zinc-400",
  unknown: "bg-amber-500/15 text-amber-300",
  missing: "bg-white/5 text-zinc-500",
  conflict: "bg-red-500/15 text-red-300",
};

export function duration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export function timeAgo(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "—";
  const minutes = Math.round((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 0) {
    const ahead = -minutes;
    if (ahead < 60) return `in ${ahead} min`;
    if (ahead < 24 * 60) return `in ${Math.round(ahead / 60)} h`;
    return `in ${Math.round(ahead / 1440)} d`;
  }
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
