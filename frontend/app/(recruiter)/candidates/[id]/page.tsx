import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { CandidateDetail } from "./candidate-detail";

export const metadata = { title: "Candidate · CallZest" };

export default function CandidatePage() {
  // The id is only known at request time, so the client component reads it inside Suspense.
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <CandidateDetail />
    </Suspense>
  );
}
