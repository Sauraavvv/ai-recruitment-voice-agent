"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState } from "@/components/states";
import { Alert, Card, PageHeader, buttonClass } from "@/components/ui";
import { KpiBar } from "@/components/kpi-bar";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";
import { listClients } from "@/services/clients";
import type { ClientListItem, ClientStatus } from "@/types";

import { ClientProfileCard } from "./client-card";
import { CLIENT_STATUS } from "./form-kit";

const DOT: Record<ClientStatus, string> = {
  active: "bg-green-400",
  on_hold: "bg-amber-400",
  closed: "bg-zinc-500",
};

export function ClientList() {
  const { data: user } = useLoad("me", me);
  if (!user) return <SkeletonGallery />;
  if (user.role !== "super_admin") {
    return (
      <>
        <PageHeader title="Clients" />
        <Alert kind="info">
          Clients are added and managed by your company&apos;s super admin. To add a job for a
          client, use{" "}
          <Link href="/jobs/new" className="underline">
            Add job
          </Link>{" "}
          in Jobs.
        </Alert>
      </>
    );
  }
  return <ClientGallery />;
}

/** Super admins: the organization's clients as a gallery of cards, with totals on top. */
function ClientGallery() {
  // A company has tens of clients, not thousands: load them all, search and filter here
  const { data, error, reload } = useLoad("clients:all", () => listClients());
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ClientStatus | "">("");

  const counts = useMemo(() => {
    const all = data ?? [];
    return {
      total: all.length,
      active: all.filter((c) => c.status === "active").length,
      on_hold: all.filter((c) => c.status === "on_hold").length,
      open: all.reduce((sum, c) => sum + c.open_requirements, 0),
    };
  }, [data]);

  const shown = useMemo(() => {
    const words = search.trim().toLowerCase();
    return (data ?? []).filter(
      (c) =>
        (!status || c.status === status) &&
        (!words ||
          [c.name, c.city, c.state, c.industry, c.contact_name]
            .join(" ")
            .toLowerCase()
            .includes(words)),
    );
  }, [data, search, status]);

  return (
    <>
      <PageHeader title="Clients" subtitle="The companies you're hiring for.">
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
            placeholder="Search clients"
            aria-label="Search clients"
            className="w-full rounded-full border border-white/10 bg-[#18191c] py-2 pr-4 pl-10 text-sm text-white outline-none placeholder:text-zinc-500 focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/30"
          />
        </label>
        <Link href="/clients/new" className={buttonClass("primary")}>
          + Add client
        </Link>
      </PageHeader>

      <KpiBar
        items={[
          {
            label: "Total clients",
            value: counts.total,
            on: !status,
            onClick: () => setStatus(""),
          },
          {
            label: "Active",
            value: counts.active,
            dot: DOT.active,
            on: status === "active",
            onClick: () => setStatus(status === "active" ? "" : "active"),
          },
          {
            label: "On hold",
            value: counts.on_hold,
            dot: DOT.on_hold,
            on: status === "on_hold",
            onClick: () => setStatus(status === "on_hold" ? "" : "on_hold"),
          },
          { label: "Open requirements", value: counts.open },
        ]}
      />

      <Divider
        label={status ? `${CLIENT_STATUS[status].label} clients` : "All clients"}
        count={data ? shown.length : undefined}
      />

      {error && !data ? (
        <Card>
          <ErrorState error={error} onRetry={reload} />
        </Card>
      ) : !data ? (
        <SkeletonGallery />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState
            title="No clients yet"
            action={{ href: "/clients/new", label: "Add your first client" }}
          >
            Add a company you&apos;re hiring for. Its openings and screening calls will live here.
          </EmptyState>
        </Card>
      ) : (
        <ul className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {shown.map((c) => (
            <li key={c.id}>
              <ClientTile client={c} />
            </li>
          ))}
          {shown.length === 0 && (
            <li className="flex min-h-[200px] items-center justify-center rounded-3xl bg-[#18191c] p-6 text-center text-sm text-zinc-500 sm:col-span-1 xl:col-span-2">
              No clients match. Try another search or status.
            </li>
          )}
        </ul>
      )}
    </>
  );
}

/** A hairline that fades in from both edges, with a small label in the middle. */
function Divider({ label, count }: { label: string; count?: number }) {
  return (
    <div className="my-6 flex items-center gap-4" role="separator" aria-label={label}>
      <span className="h-px flex-1 bg-gradient-to-r from-transparent to-white/15" />
      <span className="flex items-center gap-2 rounded-full border border-white/10 bg-[#18191c] px-3.5 py-1 text-xs font-medium tracking-wide text-zinc-300">
        <span className="h-1 w-1 rounded-full bg-zinc-500" />
        {label}
        {count !== undefined && (
          <span className="rounded-full bg-white/5 px-1.5 text-[11px] text-zinc-400">{count}</span>
        )}
      </span>
      <span className="h-px flex-1 bg-gradient-to-l from-transparent to-white/15" />
    </div>
  );
}

/** One client as its full visiting card (the same card as the form's live preview); the
 * whole card opens the client. */
function ClientTile({ client: c }: { client: ClientListItem }) {
  const s = CLIENT_STATUS[c.status];
  return (
    <Link
      href={`/clients/${c.id}`}
      className={`group block h-full rounded-3xl transition duration-200 hover:-translate-y-1 hover:shadow-[0_16px_40px_-16px_rgba(0,0,0,0.8)] focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:outline-none [&>div]:h-full ${
        c.status === "closed" ? "opacity-60" : ""
      }`}
    >
      <ClientProfileCard
        data={c}
        badges={
          <>
            <span
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${s.tone}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${DOT[c.status]}`} />
              {s.label}
            </span>
            {c.is_confidential && (
              <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-[11px] font-medium text-zinc-300">
                Confidential
              </span>
            )}
          </>
        }
        footer={
          <div className="flex items-center justify-between border-t border-white/5 pt-4 text-xs">
            <span className="text-zinc-400">
              <span className="font-display mr-1 text-base font-semibold text-white">
                {c.open_requirements}
              </span>
              open {c.open_requirements === 1 ? "requirement" : "requirements"}
            </span>
            <span className="text-zinc-500 transition group-hover:translate-x-0.5 group-hover:text-white">
              Open →
            </span>
          </div>
        }
      />
    </Link>
  );
}

function SkeletonGallery() {
  return (
    <div role="status" aria-label="Loading">
      <div className="mb-6 h-[90px] animate-pulse rounded-3xl bg-[#18191c]" />
      <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-[320px] animate-pulse rounded-3xl bg-[#18191c]" />
        ))}
      </div>
    </div>
  );
}
