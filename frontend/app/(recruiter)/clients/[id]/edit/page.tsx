import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { EditClient } from "./edit-client";

export const metadata = { title: "Edit client · HireCall" };

export default function EditClientPage() {
  // The id is only known at request time, so the client component reads it inside Suspense.
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <EditClient />
    </Suspense>
  );
}
