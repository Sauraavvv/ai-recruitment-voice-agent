import { redirect } from "next/navigation";

// The jobs list moved to /jobs. The older single-job editor (job-settings.tsx) belongs to the
// original job flow, which is switched off for now.
export default function OldJobSettingsPage() {
  redirect("/jobs");
}
