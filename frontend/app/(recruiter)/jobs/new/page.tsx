import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { NewJob } from "./new-job";

export const metadata = { title: "Add job · HireCall" };

export default function NewJobPage() {
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <NewJob />
    </Suspense>
  );
}
