import Link from "next/link";

import { Logo } from "@/components/logo";
import { PageHeader, buttonClass } from "@/components/ui";

import { ProviderCards } from "./provider-cards";
import { SystemStatus } from "./system-status";

export const metadata = { title: "System status · HireCall" };

// A public page of its own, without the sidebar: the status of the whole site, no login needed.
export default function StatusPage() {
  return (
    <main className="min-h-screen flex-1 bg-black px-4 py-8 text-white sm:px-8">
      <div className="mx-auto w-full max-w-6xl">
        <div className="mb-8 flex items-center justify-between gap-3">
          <Link href="/dashboard" aria-label="HireCall dashboard">
            <Logo className="text-white" markClassName="h-7 w-7" textClassName="text-xl" />
          </Link>
          <Link href="/dashboard" className={buttonClass("secondary")}>
            Go to dashboard
          </Link>
        </div>
        <PageHeader
          title="System status"
          subtitle="HireCall's own services and the connections calls depend on."
        />
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <SystemStatus />
          <ProviderCards />
        </div>
      </div>
    </main>
  );
}
