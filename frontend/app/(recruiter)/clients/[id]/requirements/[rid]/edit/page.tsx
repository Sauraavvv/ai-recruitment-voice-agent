import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { EditRequirement } from "./edit-requirement";

export const metadata = { title: "Edit requirement · HireCall" };

export default function EditRequirementPage() {
  // The ids are only known at request time, so the client component reads them inside Suspense.
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <EditRequirement />
    </Suspense>
  );
}
