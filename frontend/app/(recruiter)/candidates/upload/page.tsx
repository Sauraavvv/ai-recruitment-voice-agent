import { Suspense } from "react";

import { Muted } from "@/components/ui";

import { UploadFlow } from "./upload-flow";

export const metadata = { title: "Upload candidates · HireCall" };

export default function UploadPage() {
  // UploadFlow reads ?requirement=<id>, only known at request time
  return (
    <Suspense fallback={<Muted>Loading…</Muted>}>
      <UploadFlow />
    </Suspense>
  );
}
