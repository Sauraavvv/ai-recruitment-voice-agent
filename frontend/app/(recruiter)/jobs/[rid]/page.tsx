import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { JobView } from "./job-view";

export const metadata = { title: "Job · CallZest" };

export default function JobPage() {
  // The id is only known at request time, so the client component reads it inside Suspense.
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <JobView />
    </Suspense>
  );
}
