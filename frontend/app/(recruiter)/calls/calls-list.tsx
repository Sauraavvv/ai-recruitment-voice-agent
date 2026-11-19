"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { EmptyState, ErrorState, SkeletonRows } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button, Card, PageHeader, inputClass } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import {
  ACTIVE_CALL_STATUSES,
  ATTEMPT_TYPE_LABELS,
  CALL_STATUS_LABELS,
  END_REASON_LABELS,
  duration,
  formatDate,
} from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { searchCalls } from "@/services/calls";

const PAGE_SIZE = 25;

/** Start of a local day as an ISO timestamp (the API compares created_at in UTC). */
const dayStart = (date: string) => (date ? new Date(`${date}T00:00:00`).toISOString() : "");
const dayAfter = (date: string) => {
  if (!date) return "";
  const d = new Date(`${date}T00:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toISOString();
};

/** Every call attempt, newest first, with filters (phase-08 P8-T11). */
export function CallsList() {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const query = {
    q,
    call_status: status ? [status] : undefined,
    created_from: dayStart(from),
    created_to: dayAfter(to),
    page,
    page_size: PAGE_SIZE,
  };
  const { data, error, loading, reload } = useLoad(JSON.stringify(query), () => searchCalls(query));
  usePolling(reload, data?.items.some((c) => ACTIVE_CALL_STATUSES.has(c.call_status)) ?? false);
  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(q || status || from || to);

  return (
    <>
      <PageHeader title="Calls" subtitle="Every call attempt, newest first." />
      <Card>
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <input
            type="search"
            placeholder="Search candidate name or phone"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputClass} max-w-xs`}
            aria-label="Search calls"
          />
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className={`${inputClass} max-w-48`}
            aria-label="Call status"
          >
            <option value="">All statuses</option>
            {Object.entries(CALL_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <label className="text-xs text-zinc-500">
            From
            <input
              type="date"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                setPage(1);
              }}
              className={`${inputClass} mt-1 block w-40 [color-scheme:dark]`}
            />
          </label>
          <label className="text-xs text-zinc-500">
            To
            <input
              type="date"
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                setPage(1);
              }}
              className={`${inputClass} mt-1 block w-40 [color-scheme:dark]`}
            />
          </label>
          {loading && data && <span className="pb-2 text-sm text-zinc-500">Loading…</span>}
        </div>

        {error && <ErrorState error={error} onRetry={reload} />}
        {!data && !error && <SkeletonRows rows={6} />}
        {data &&
          data.items.length === 0 &&
          (filtered ? (
            <EmptyState title="No calls match these filters." />
          ) : (
            <EmptyState
              title="No calls yet"
              action={{ href: "/candidates", label: "Go to candidates" }}
            >
              Start screening calls from the candidate list or the dashboard.
            </EmptyState>
          ))}

        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs text-zinc-500 uppercase">
                <tr>
                  <th className="py-3 pr-4 font-medium">Candidate</th>
                  <th className="py-3 pr-4 font-medium">Attempt</th>
                  <th className="py-3 pr-4 font-medium">Status</th>
                  <th className="py-3 pr-4 font-medium">Ended</th>
                  <th className="py-3 pr-4 font-medium">Started</th>
                  <th className="py-3 pr-4 font-medium">Length</th>
                  <th className="py-3 pr-4 font-medium">Provider</th>
                  <th className="py-3 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-zinc-300">
                {data.items.map((c) => (
                  <tr key={c.id} className="transition hover:bg-white/[0.03]">
                    <td className="py-3 pr-4">
                      <Link
                        href={`/candidates/${c.candidate_id}`}
                        className="font-medium text-white hover:underline"
                      >
                        {c.candidate_name}
                      </Link>
                      <div className="text-xs text-zinc-500">{c.applied_role}</div>
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap">
                      #{c.attempt_number}{" "}
                      <span className="text-xs text-zinc-500">
                        {ATTEMPT_TYPE_LABELS[c.attempt_type] ?? c.attempt_type}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      <StatusBadge kind="call" status={c.call_status} />
                    </td>
                    <td className="py-3 pr-4 text-xs">
                      {c.end_reason ? (END_REASON_LABELS[c.end_reason] ?? c.end_reason) : "—"}
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap text-zinc-500">
                      {formatDate(c.start_time ?? c.created_at)}
                    </td>
                    <td className="py-3 pr-4 tabular-nums">{duration(c.duration_seconds)}</td>
                    <td className="py-3 pr-4 text-xs text-zinc-500">{c.provider_status ?? "—"}</td>
                    <td className="py-3 text-right">
                      {c.has_transcript && (
                        <Link
                          href={`/candidates/${c.candidate_id}?call=${c.id}`}
                          className="rounded-lg px-2 py-1 text-xs text-[#93b4ff] hover:bg-white/5"
                        >
                          Transcript
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && total > 0 && (
          <div className="mt-5 flex items-center gap-3 text-sm text-zinc-400">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <span>
              Page {page} of {pages} · {total} call{total === 1 ? "" : "s"}
            </span>
            <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
