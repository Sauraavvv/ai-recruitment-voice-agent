import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { EditJob } from "./edit-job";

export const metadata = { title: "Edit job · HireCall" };

export default function EditJobPage() {
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <EditJob />
    </Suspense>
  );
}
