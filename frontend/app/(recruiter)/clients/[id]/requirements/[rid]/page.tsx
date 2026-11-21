import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { RequirementDetail } from "./requirement-detail";

export const metadata = { title: "Requirement · HireCall" };

export default function RequirementPage() {
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <RequirementDetail />
    </Suspense>
  );
}
