import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { ClientDetail } from "./client-detail";

export const metadata = { title: "Client · HireCall" };

export default function ClientPage() {
  // The id is only known at request time, so the client component reads it inside Suspense.
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <ClientDetail />
    </Suspense>
  );
}
