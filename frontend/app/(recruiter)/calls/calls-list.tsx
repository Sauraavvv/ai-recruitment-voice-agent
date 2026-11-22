"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { ClientFilter } from "@/components/client-filter";
import { RoundAnswers } from "@/components/round-answers";
import { AI_NOTE, EvaluationBadge } from "@/components/round-evaluation";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button, Card, PageHeader, inputClass } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import {
  ACTIVE_CALL_STATUSES,
  ATTEMPT_TYPE_LABELS,
  CALL_PURPOSE_LABELS,
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

type Purpose = "screening" | "telephonic";

const COPY: Record<Purpose, { title: string; subtitle: string; empty: string }> = {
  screening: {
    title: "Screening calls",
    subtitle: "Every screening call, newest first.",
    empty: "Start screening calls from a job's candidates.",
  },
  telephonic: {
    title: "Telephonic round",
    subtitle: "Every telephonic round call across your jobs, newest first, with the answers.",
    empty: "Approve a job's telephonic questions, then call the interested candidates from there.",
  },
};

/** One kind of call (screening or the telephonic round), newest first, with filters. */
export function CallsList({ purpose }: { purpose: Purpose }) {
  const copy = COPY[purpose];
  const round = purpose === "telephonic";
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [client, setClient] = useState("");
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
    purpose,
    client_id: client,
    page,
    page_size: PAGE_SIZE,
  };
  const { data, error, loading, reload } = useLoad(JSON.stringify(query), () => searchCalls(query));
  usePolling(reload, data?.items.some((c) => ACTIVE_CALL_STATUSES.has(c.call_status)) ?? false);
  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(q || status || from || to || client);

  return (
    <>
      <PageHeader title={copy.title} subtitle={copy.subtitle} />
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
          <ClientFilter
            value={client}
            onChange={(v) => {
              setClient(v);
              setPage(1);
            }}
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
            <EmptyState title="No calls yet" action={{ href: "/jobs", label: "Go to jobs" }}>
              {copy.empty}
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
                  {!round && <th className="py-3 pr-4 font-medium">Provider</th>}
                  {round && (
                    <th className="py-3 pr-4 font-medium" title={AI_NOTE}>
                      AI score
                    </th>
                  )}
                  <th className="py-3 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-zinc-300">
                {data.items.map((c) => (
                  <Fragment key={c.id}>
                    <tr
                      className={`transition hover:bg-white/[0.03] ${open === c.id ? "bg-white/[0.03]" : ""}`}
                    >
                      <td className="py-3 pr-4">
                        <Link
                          href={`/candidates/${c.candidate_id}`}
                          className="font-medium text-white hover:underline"
                        >
                          {c.candidate_name}
                        </Link>
                        {c.round ? (
                          <div className="text-xs text-zinc-500">
                            <Link
                              href={`/clients/${c.round.client_id}/requirements/${c.round.requirement_id}`}
                              className="hover:text-zinc-300 hover:underline"
                            >
                              {c.round.title}
                            </Link>{" "}
                            · questions v{c.round.version}
                          </div>
                        ) : (
                          <div className="text-xs text-zinc-500">{c.applied_role}</div>
                        )}
                      </td>
                      <td className="py-3 pr-4 whitespace-nowrap">
                        #{c.attempt_number}{" "}
                        <span className="text-xs text-zinc-500">
                          {ATTEMPT_TYPE_LABELS[c.attempt_type] ?? c.attempt_type}
                          {!round &&
                            c.purpose === "telephonic" &&
                            ` · ${CALL_PURPOSE_LABELS.telephonic}`}
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
                      {!round && (
                        <td className="py-3 pr-4 text-xs text-zinc-500">
                          {c.provider_status ?? "—"}
                        </td>
                      )}
                      {round && (
                        <td className="py-3 pr-4">
                          <EvaluationBadge badge={c.evaluation} />
                        </td>
                      )}
                      <td className="py-3 text-right whitespace-nowrap">
                        {round && c.has_transcript && (
                          <button
                            type="button"
                            onClick={() => setOpen(open === c.id ? null : c.id)}
                            aria-expanded={open === c.id}
                            className="rounded-lg px-2 py-1 text-xs text-zinc-300 hover:bg-white/5 hover:text-white"
                          >
                            {open === c.id ? "Hide answers" : "Answers"}
                          </button>
                        )}
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
                    {open === c.id && (
                      <tr>
                        <td colSpan={7} className="pt-1 pb-4">
                          <RoundAnswers attemptId={c.id} onEvaluated={reload} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
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
