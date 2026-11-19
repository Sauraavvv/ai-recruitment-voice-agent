"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  MAX_CALLS_PER_ACTION,
  StartCallsDialog,
  type CallTarget,
} from "@/components/start-calls-dialog";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button, Card, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import {
  ACTIVE_CALL_STATUSES,
  CALL_STATUS_LABELS,
  SCREENING_STATUS_LABELS,
  formatDate,
  initials,
  yesNo,
} from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { listCandidates } from "@/services/candidates";
import type { CandidateListItem } from "@/types";

const PAGE_SIZE = 25;

export const CALL_STATUS_FILTERS: [string, string][] = [
  ["not_called", "Not called yet"],
  ...Object.entries(CALL_STATUS_LABELS),
];

/** Why a row's Call button is disabled ("" when it isn't). */
export function disabledReason(row: CandidateListItem): string {
  return row.eligibility.can_call ? "" : (row.eligibility.message ?? "Can't be called now");
}

export function CandidateList() {
  const notify = useToast();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [callStatus, setCallStatus] = useState("");
  const [interested, setInterested] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Map<string, string>>(new Map());
  const [targets, setTargets] = useState<CallTarget[] | null>(null);

  // Debounce typing so each keystroke doesn't hit the API.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const query = {
    q,
    screening_status: status,
    call_status: callStatus,
    interested,
    page,
    page_size: PAGE_SIZE,
  };
  const { data, error, loading, reload } = useLoad(JSON.stringify(query), () =>
    listCandidates(query),
  );
  const active =
    data?.items.some((c) => c.last_call && ACTIVE_CALL_STATUSES.has(c.last_call.call_status)) ??
    false;
  usePolling(reload, active);

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(q || status || callStatus || interested);

  function toggle(row: CandidateListItem) {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(row.id)) next.delete(row.id);
      else if (next.size < MAX_CALLS_PER_ACTION) next.set(row.id, row.name);
      else notify("info", `At most ${MAX_CALLS_PER_ACTION} calls per action.`);
      return next;
    });
  }

  function toggleAll(rows: CandidateListItem[], on: boolean) {
    setSelected((current) => {
      const next = new Map(current);
      for (const row of rows) {
        if (!on) next.delete(row.id);
        else if (next.size < MAX_CALLS_PER_ACTION && row.eligibility.can_call)
          next.set(row.id, row.name);
      }
      return next;
    });
  }

  const callable = data?.items.filter((c) => c.eligibility.can_call) ?? [];
  const allOnPage = callable.length > 0 && callable.every((c) => selected.has(c.id));

  return (
    <>
      <PageHeader
        title="Candidates"
        subtitle="Everyone added by upload or by hand, with their calls and screening results."
      >
        <Link href="/candidates/new" className={buttonClass("secondary")}>
          Add candidate
        </Link>
        <Link href="/candidates/upload" className={buttonClass("primary")}>
          Upload file
        </Link>
      </PageHeader>

      <Card>
        <div className="mb-5 flex flex-wrap gap-3">
          <input
            type="search"
            placeholder="Search name, phone or email"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputClass} max-w-xs`}
            aria-label="Search candidates"
          />
          <FilterSelect
            label="Call status"
            value={callStatus}
            onChange={(v) => {
              setCallStatus(v);
              setPage(1);
            }}
            options={CALL_STATUS_FILTERS}
            all="All call statuses"
          />
          <FilterSelect
            label="Screening status"
            value={status}
            onChange={(v) => {
              setStatus(v);
              setPage(1);
            }}
            options={Object.entries(SCREENING_STATUS_LABELS)}
            all="All screening statuses"
          />
          <FilterSelect
            label="Interest"
            value={interested}
            onChange={(v) => {
              setInterested(v);
              setPage(1);
            }}
            options={[
              ["true", "Interested"],
              ["false", "Not interested"],
            ]}
            all="Any interest"
          />
          {loading && data && <span className="self-center text-sm text-zinc-500">Loading…</span>}
        </div>

        {selected.size > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl bg-[#1d4ed8]/10 px-4 py-3 text-sm">
            <span className="text-zinc-200">
              {selected.size} selected{" "}
              <span className="text-zinc-500">(max {MAX_CALLS_PER_ACTION})</span>
            </span>
            <Button onClick={() => setTargets([...selected].map(([id, name]) => ({ id, name })))}>
              Call selected
            </Button>
            <Button variant="secondary" onClick={() => setSelected(new Map())}>
              Clear
            </Button>
          </div>
        )}

        {error && <ErrorState error={error} onRetry={reload} />}
        {!data && !error && <SkeletonRows rows={6} />}

        {data &&
          data.items.length === 0 &&
          (filtered ? (
            <EmptyState title="No candidates match these filters." />
          ) : (
            <EmptyState
              title="No candidates yet"
              action={{ href: "/candidates/upload", label: "Upload candidates" }}
            >
              Upload a CSV or Excel file, or add someone by hand, then start the screening calls.
            </EmptyState>
          ))}

        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs text-zinc-500 uppercase">
                <tr>
                  <th className="w-8 py-3 pr-2">
                    <input
                      type="checkbox"
                      aria-label="Select everyone who can be called on this page"
                      checked={allOnPage}
                      disabled={callable.length === 0}
                      onChange={(e) => toggleAll(callable, e.target.checked)}
                      className="accent-[#1d4ed8]"
                    />
                  </th>
                  <th className="py-3 pr-4 font-medium">Name</th>
                  <th className="py-3 pr-4 font-medium">Phone</th>
                  <th className="py-3 pr-4 font-medium">Job role</th>
                  <th className="py-3 pr-4 font-medium">Exp.</th>
                  <th className="py-3 pr-4 font-medium">Call</th>
                  <th className="py-3 pr-4 font-medium">Screening</th>
                  <th className="py-3 pr-4 font-medium">Interested</th>
                  <th className="py-3 pr-4 font-medium">Last call</th>
                  <th className="py-3 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-zinc-300">
                {data.items.map((c) => (
                  <Row
                    key={c.id}
                    row={c}
                    checked={selected.has(c.id)}
                    onToggle={() => toggle(c)}
                    onCall={() => setTargets([{ id: c.id, name: c.name }])}
                    onRetry={() => setTargets([{ id: c.id, name: c.name }])}
                  />
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
              Page {page} of {pages} · {total} candidate{total === 1 ? "" : "s"}
            </span>
            <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        )}
      </Card>

      <StartCallsDialog
        targets={targets}
        onClose={() => setTargets(null)}
        onStarted={() => {
          setSelected(new Map());
          reload();
        }}
      />
    </>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  all,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
  all: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${inputClass} max-w-48`}
      aria-label={label}
    >
      <option value="">{all}</option>
      {options.map(([v, text]) => (
        <option key={v} value={v}>
          {text}
        </option>
      ))}
    </select>
  );
}

export function Row({
  row: c,
  checked,
  onToggle,
  onCall,
  onRetry,
}: {
  row: CandidateListItem;
  checked: boolean;
  onToggle: () => void;
  onCall: () => void;
  onRetry: () => void;
}) {
  const reason = disabledReason(c);
  const last = c.last_call;
  // a finished call can be retried (same eligibility rules); otherwise a first call
  const canRetry = Boolean(last?.terminal) && c.eligibility.can_call;
  return (
    <tr className="transition hover:bg-white/[0.03]">
      <td className="py-3 pr-2">
        <input
          type="checkbox"
          aria-label={`Select ${c.name}`}
          checked={checked}
          disabled={!c.eligibility.can_call}
          title={reason || undefined}
          onChange={onToggle}
          className="accent-[#1d4ed8]"
        />
      </td>
      <td className="py-3 pr-4">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-medium text-white">
            {initials(c.name)}
          </span>
          <span className="min-w-0">
            <Link
              href={`/candidates/${c.id}`}
              className="block truncate font-medium text-white hover:underline"
            >
              {c.name}
            </Link>
            {c.open_conflicts > 0 && (
              <span className="block text-xs text-red-300">
                {c.open_conflicts} answer{c.open_conflicts === 1 ? "" : "s"} to check
              </span>
            )}
          </span>
          {c.opted_out && (
            <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-300">
              Opted out
            </span>
          )}
        </div>
      </td>
      <td className="py-3 pr-4 whitespace-nowrap tabular-nums">{c.phone}</td>
      <td className="py-3 pr-4">{c.applied_role}</td>
      <td className="py-3 pr-4 whitespace-nowrap">
        {c.total_experience == null ? "—" : `${c.total_experience} yrs`}
      </td>
      <td className="py-3 pr-4">
        {last ? (
          <StatusBadge kind="call" status={last.call_status} />
        ) : (
          <span className="text-xs text-zinc-500">Not called</span>
        )}
      </td>
      <td className="py-3 pr-4">
        <StatusBadge kind="screening" status={c.screening_status} />
      </td>
      <td className="py-3 pr-4">{yesNo(c.interested)}</td>
      <td className="py-3 pr-4 whitespace-nowrap text-zinc-500">
        {last ? formatDate(last.at) : "—"}
      </td>
      <td className="py-3">
        <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
          <Link
            href={`/candidates/${c.id}`}
            className="rounded-lg px-2 py-1 text-xs text-zinc-300 hover:bg-white/5"
          >
            View
          </Link>
          {c.last_call_has_transcript && last && (
            <Link
              href={`/candidates/${c.id}?call=${last.id}`}
              className="rounded-lg px-2 py-1 text-xs text-zinc-300 hover:bg-white/5"
            >
              Transcript
            </Link>
          )}
          {last?.terminal ? (
            <button
              type="button"
              onClick={onRetry}
              disabled={!canRetry}
              title={reason || "Call again"}
              aria-label={`Retry ${c.name}${reason ? ` (${reason})` : ""}`}
              className="rounded-lg bg-[#24262b] px-2.5 py-1 text-xs text-zinc-200 hover:bg-[#2c2f35] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Retry
            </button>
          ) : (
            <button
              type="button"
              onClick={onCall}
              disabled={!c.eligibility.can_call}
              title={reason || "Start a screening call"}
              aria-label={`Call ${c.name}${reason ? ` (${reason})` : ""}`}
              className="rounded-lg bg-[#1d4ed8] px-2.5 py-1 text-xs text-white hover:bg-[#2563eb] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Call
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
