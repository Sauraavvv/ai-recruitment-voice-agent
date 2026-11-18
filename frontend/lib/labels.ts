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
