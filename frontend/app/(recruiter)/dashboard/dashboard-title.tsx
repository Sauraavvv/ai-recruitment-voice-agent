"use client";

import { possessive } from "@/lib/organization";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";

/** "<Company>'s Dashboard": the company the account signed up with, for everyone in it. */
export function DashboardTitle() {
  const { data: user } = useLoad("me", me);
  return (
    // Two words with a real gap between them (the display font's own space is very narrow)
    <h1 className="font-display flex flex-wrap items-baseline gap-x-2.5 text-2xl font-semibold text-white">
      {user && <span>{possessive(user.organization.name)}</span>}
      <span>Dashboard</span>
    </h1>
  );
}

/** The title and the line under it. */
export function DashboardHeading() {
  return (
    <div>
      <DashboardTitle />
      <p className="mt-1 text-sm text-zinc-500">
        All your calls and screening results at a glance.
      </p>
    </div>
  );
}
