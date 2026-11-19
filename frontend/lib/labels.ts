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
