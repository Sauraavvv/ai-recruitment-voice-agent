import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { NewRequirement } from "./new-requirement";

export const metadata = { title: "Add requirement · HireCall" };

export default function NewRequirementPage() {
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <NewRequirement />
    </Suspense>
  );
}
