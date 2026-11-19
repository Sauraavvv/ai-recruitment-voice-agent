import { Suspense } from "react";

import { DashboardView } from "./dashboard-view";

export const metadata = { title: "Dashboard · HireCall" };

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold text-white">Dashboard</h1>
        <p className="mt-1 text-sm text-zinc-500">Calls and screening results at a glance.</p>
      </div>
      {/* DashboardView reads the clock for live-call timers: render it at request time */}
      <Suspense fallback={<div className="h-40 rounded-3xl bg-[#18191c]" />}>
        <DashboardView />
      </Suspense>
    </div>
  );
}
