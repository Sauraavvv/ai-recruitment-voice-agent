import Link from "next/link";

import { SystemStatus } from "./system-status";

export const metadata = { title: "System status · HireCall" };

export default function StatusPage() {
  return (
    <main className="mx-auto w-full max-w-xl flex-1 px-4 py-12">
      <h1 className="text-2xl font-semibold">HireCall</h1>
      <p className="mt-1 mb-8 text-sm text-zinc-500">
        System status ·{" "}
        <Link href="/dashboard" className="underline">
          Go to dashboard
        </Link>
      </p>
      <SystemStatus />
    </main>
  );
}
