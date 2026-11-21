import { Suspense } from "react";

import { DashboardHeading } from "./dashboard-title";
import { DashboardView } from "./dashboard-view";

export const metadata = { title: "Dashboard · HireCall" };

export default function DashboardPage() {
  // DashboardView reads the clock for live-call timers: render it at request time. It draws
  // the title itself, with the Today / 7 days / All time switch beside it.
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <DashboardHeading />
          <div className="h-40 rounded-3xl bg-[#18191c]" />
        </div>
      }
    >
      <DashboardView />
    </Suspense>
  );
}
