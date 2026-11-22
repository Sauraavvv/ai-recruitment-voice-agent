"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState } from "@/components/states";
import { Card, PageHeader, buttonClass } from "@/components/ui";
import { KpiBar } from "@/components/kpi-bar";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";
import { listJobs } from "@/services/requirements";
import type { RequirementStatus } from "@/types";

import { RequirementRow } from "../clients/[id]/client-overview";
import { REQUIREMENT_STATUS } from "../clients/[id]/requirements/requirement-form";

/** The jobs this account sees (a super admin: every job of the company; a recruiter: the ones
 * they created), with search and a status filter on the totals. Both add jobs from here. */
export function AllJobs() {
  const { data: user } = useLoad("me", me);
  const isSuperAdmin = user?.role === "super_admin";
  const { data, error, reload } = useLoad("jobs", listJobs);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<RequirementStatus | "">("");

  const totals = useMemo(() => {
    const all = data ?? [];
    const open = all.filter((j) => j.status === "open");
    return {
      all: all.length,
      open: open.length,
      on_hold: all.filter((j) => j.status === "on_hold").length,
      needed: open.reduce((sum, j) => sum + j.openings, 0),
      interested: all.reduce((sum, j) => sum + j.interested, 0),
    };
  }, [data]);

  const shown = useMemo(() => {
    const words = search.trim().toLowerCase();
    return (data ?? []).filter(
      (j) =>
        (!status || j.status === status) &&
        (!words ||
          [j.title, j.client_name, j.location, j.created_by_name, ...j.skills]
            .join(" ")
            .toLowerCase()
            .includes(words)),
    );
  }, [data, search, status]);

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle={
          isSuperAdmin
            ? "Every opening across your clients, from every recruiter."
            : "The jobs you've added."
        }
      >
        <label className="relative w-full sm:w-72">
          <svg
            viewBox="0 0 24 24"
            className="pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-zinc-500"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search jobs"
            aria-label="Search jobs by role, client, location, skill or creator"
            className="w-full rounded-full border border-white/10 bg-[#18191c] py-2 pr-4 pl-10 text-sm text-white outline-none placeholder:text-zinc-500 focus:border-white/30"
          />
        </label>
        {isSuperAdmin && (
          <Link href="/clients" className={buttonClass("secondary")}>
            Clients
          </Link>
        )}
        <Link href="/jobs/new" className={buttonClass()}>
          + Add job
        </Link>
      </PageHeader>

      <KpiBar
        items={[
          { label: "Total jobs", value: totals.all, on: !status, onClick: () => setStatus("") },
          {
            label: "Open",
            value: totals.open,
            dot: "bg-green-400",
            on: status === "open",
            onClick: () => setStatus(status === "open" ? "" : "open"),
          },
          {
            label: "On hold",
            value: totals.on_hold,
            dot: "bg-amber-400",
            on: status === "on_hold",
            onClick: () => setStatus(status === "on_hold" ? "" : "on_hold"),
          },
          { label: "People needed", value: totals.needed },
          { label: "Interested", value: totals.interested },
        ]}
      />

      <div className="my-6 flex items-center gap-4" role="separator">
        <span className="h-px flex-1 bg-gradient-to-r from-transparent to-white/15" />
        <span className="flex items-center gap-2 rounded-full border border-white/10 bg-[#18191c] px-3.5 py-1 text-xs font-medium tracking-wide text-zinc-300">
          <span className="h-1 w-1 rounded-full bg-zinc-500" />
          {status ? `${REQUIREMENT_STATUS[status].label} jobs` : "All jobs"}
          {data && (
            <span className="rounded-full bg-white/5 px-1.5 text-[11px] text-zinc-400">
              {shown.length}
            </span>
          )}
        </span>
        <span className="h-px flex-1 bg-gradient-to-l from-transparent to-white/15" />
      </div>

      {error && !data ? (
        <Card>
          <ErrorState error={error} onRetry={reload} />
        </Card>
      ) : !data ? (
        <Skeleton />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState title="No jobs yet" action={{ href: "/jobs/new", label: "+ Add job" }}>
            Add a job for one of your clients, then upload its candidate list.
          </EmptyState>
        </Card>
      ) : shown.length === 0 ? (
        <p className="rounded-3xl bg-[#18191c] p-10 text-center text-sm text-zinc-500">
          No jobs match. Try another search or status.
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((j) => (
            <li key={j.id}>
              <RequirementRow
                clientId={j.client_id}
                clientName={j.client_name}
                href={`/jobs/${j.id}`}
                r={j}
              />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="h-[120px] animate-pulse rounded-3xl bg-[#18191c]" />
      ))}
    </div>
  );
}
