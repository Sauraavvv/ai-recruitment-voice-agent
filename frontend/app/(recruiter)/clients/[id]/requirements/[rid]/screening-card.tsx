"use client";

import Link from "next/link";
import { type ReactNode, useMemo, useState } from "react";

import {
  MAX_CALLS_PER_ACTION,
  StartCallsDialog,
  type CallTarget,
} from "@/components/start-calls-dialog";
import { ErrorState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { Button, buttonClass } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import { ACTIVE_CALL_STATUSES, initials, retryStatusText, timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { listCandidates } from "@/services/candidates";
import type { CandidateListItem } from "@/types";

import { disabledReason } from "../../../../candidates/candidate-list";

const PAGE_SIZE = 100;

type Filter = "all" | "not_called" | "pending" | "interested" | "not_interested";

// Where a candidate stands after screening; the order is the bar's order
const GROUPS: { key: Exclude<Filter, "all">; label: string; bar: string; dot: string }[] = [
  { key: "interested", label: "Interested", bar: "bg-green-400", dot: "bg-green-400" },
  { key: "not_interested", label: "Not interested", bar: "bg-red-400/80", dot: "bg-red-400" },
  { key: "pending", label: "Called, no answer yet", bar: "bg-zinc-400", dot: "bg-zinc-400" },
  { key: "not_called", label: "Not called", bar: "bg-white/10", dot: "bg-zinc-600" },
];

function groupOf(r: CandidateListItem): Exclude<Filter, "all"> {
  if (r.interested === true) return "interested";
  if (r.interested === false) return "not_interested";
  return r.last_call ? "pending" : "not_called";
}

/** A requirement's candidates and their screening calls: upload, call, see who's interested. */
export function ScreeningCard({ requirementId }: { requirementId: string }) {
  const [targets, setTargets] = useState<CallTarget[] | null>(null);
  const [selected, setSelected] = useState<Map<string, string>>(new Map());
  const [filter, setFilter] = useState<Filter>("all");
  const { data, error, reload } = useLoad(`screening:${requirementId}`, () =>
    listCandidates({ requirement_id: requirementId, page_size: PAGE_SIZE, sort: "-created_at" }),
  );
  const rows = useMemo(() => data?.items ?? [], [data]);
  const active = rows.some((r) => r.last_call && ACTIVE_CALL_STATUSES.has(r.last_call.call_status));
  usePolling(reload, active);

  const upload = `/candidates/upload?requirement=${requirementId}`;
  const notCalledYet = rows.filter((r) => r.eligibility.can_call && !r.last_call);
  const counts = useMemo(() => {
    const out: Record<Filter, number> = {
      all: rows.length,
      not_called: 0,
      pending: 0,
      interested: 0,
      not_interested: 0,
    };
    for (const r of rows) out[groupOf(r)] += 1;
    return out;
  }, [rows]);
  const shown = filter === "all" ? rows : rows.filter((r) => groupOf(r) === filter);
  const selectable = shown.filter((r) => r.eligibility.can_call);
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.id));

  function toggle(row: CandidateListItem) {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(row.id)) next.delete(row.id);
      else next.set(row.id, row.name);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) => {
      const next = new Map(current);
      for (const r of selectable) {
        if (allSelected) next.delete(r.id);
        else next.set(r.id, r.name);
      }
      return next;
    });
  }

  return (
    <section className="flex h-full flex-col rounded-3xl bg-[#18191c] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/5 text-zinc-300">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
            </svg>
          </span>
          <div>
            <h2 className="font-display text-lg font-semibold text-white">Screening calls</h2>
            <p className="text-sm text-zinc-500">
              Upload a list, call it, and see who&apos;s interested.
            </p>
          </div>
        </div>
        {rows.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Link href={upload} className={buttonClass("secondary")}>
              Upload list
            </Link>
            <Button
              disabled={notCalledYet.length === 0}
              title={notCalledYet.length === 0 ? "Nobody left who can be called now" : undefined}
              onClick={() =>
                setTargets(
                  notCalledYet
                    .slice(0, MAX_CALLS_PER_ACTION)
                    .map((r) => ({ id: r.id, name: r.name })),
                )
              }
            >
              Call not-called ({Math.min(notCalledYet.length, MAX_CALLS_PER_ACTION)})
            </Button>
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-1 flex-col">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data ? (
          <div className="space-y-3" role="status" aria-label="Loading">
            <div className="h-16 animate-pulse rounded-2xl bg-white/[0.03]" />
            <div className="h-48 animate-pulse rounded-2xl bg-white/[0.03]" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyUpload href={upload} />
        ) : (
          <>
            <Breakdown counts={counts} />

            <div className="mt-6 flex flex-wrap items-center gap-1.5 border-b border-white/5 pb-3">
              <Tab on={filter === "all"} onClick={() => setFilter("all")} count={counts.all}>
                All
              </Tab>
              {GROUPS.map((g) => (
                <Tab
                  key={g.key}
                  on={filter === g.key}
                  onClick={() => setFilter(g.key)}
                  count={counts[g.key]}
                  dot={g.dot}
                >
                  {g.label}
                </Tab>
              ))}
            </div>

            {selected.size > 0 && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white/[0.04] px-4 py-2.5 text-sm">
                <span className="text-zinc-300">
                  <span className="font-semibold text-white">{selected.size}</span> selected
                </span>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setSelected(new Map())}>
                    Clear
                  </Button>
                  <Button
                    onClick={() => setTargets([...selected].map(([id, name]) => ({ id, name })))}
                  >
                    Call selected ({selected.size})
                  </Button>
                </div>
              </div>
            )}

            <div className="mt-2 hidden grid-cols-[20px_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-4 px-3 py-2 text-[11px] tracking-wider text-zinc-500 uppercase md:grid">
              <input
                type="checkbox"
                aria-label="Select everyone who can be called"
                checked={allSelected}
                disabled={selectable.length === 0}
                onChange={toggleAll}
                className="accent-zinc-300"
              />
              <span>Candidate</span>
              <span>Call</span>
              <span>Result</span>
              <span className="sr-only">Actions</span>
            </div>

            {shown.length === 0 ? (
              <p className="py-10 text-center text-sm text-zinc-500">Nobody here.</p>
            ) : (
              <ul className="space-y-1.5">
                {shown.map((r) => (
                  <CandidateRow
                    key={r.id}
                    row={r}
                    checked={selected.has(r.id)}
                    onToggle={() => toggle(r)}
                    onCall={() => setTargets([{ id: r.id, name: r.name }])}
                  />
                ))}
              </ul>
            )}

            {data.meta.total > rows.length && (
              <p className="mt-3 text-xs text-zinc-500">
                Showing the newest {rows.length} of {data.meta.total}.
              </p>
            )}
            {notCalledYet.length === 0 && counts.not_called > 0 && rows[0].eligibility.message && (
              <p className="mt-3 text-xs text-zinc-500">
                Nobody can be called right now: {rows[0].eligibility.message}
              </p>
            )}
          </>
        )}
      </div>

      <StartCallsDialog
        targets={targets}
        onClose={() => setTargets(null)}
        onStarted={() => {
          setSelected(new Map());
          reload();
        }}
      />
    </section>
  );
}

/** One stacked bar of where everyone stands, with a legend. */
function Breakdown({ counts }: { counts: Record<Filter, number> }) {
  const total = Math.max(counts.all, 1);
  return (
    <div>
      <div className="flex items-end justify-between gap-4">
        <div>
          <span className="font-display text-4xl font-semibold tracking-tight text-white">
            {counts.all}
          </span>
          <span className="ml-2 text-sm text-zinc-500">
            {counts.all === 1 ? "candidate" : "candidates"}
          </span>
        </div>
        <div className="text-right text-sm text-zinc-500">
          <span className="font-display text-2xl font-semibold text-green-400">
            {counts.interested}
          </span>{" "}
          interested
        </div>
      </div>
      <div className="mt-4 flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-white/5">
        {GROUPS.map((g) =>
          counts[g.key] > 0 ? (
            <div
              key={g.key}
              className={`${g.bar} transition-all duration-500 first:rounded-l-full last:rounded-r-full`}
              style={{ width: `${(counts[g.key] / total) * 100}%` }}
              title={`${g.label}: ${counts[g.key]}`}
            />
          ) : null,
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-zinc-400">
        {GROUPS.map((g) => (
          <span key={g.key} className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${g.dot}`} />
            {g.label}
            <span className="font-medium text-zinc-200">{counts[g.key]}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Tab({
  on,
  onClick,
  count,
  dot,
  children,
}: {
  on: boolean;
  onClick: () => void;
  count: number;
  dot?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition ${
        on ? "bg-white/10 text-white" : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
      }`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />}
      {children}
      <span className={on ? "text-zinc-300" : "text-zinc-600"}>{count}</span>
    </button>
  );
}

function ResultPill({ value }: { value: boolean | null | undefined }) {
  if (value === true)
    return (
      <span className="rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-300">
        ✓ Interested
      </span>
    );
  if (value === false)
    return (
      <span className="rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-medium text-red-300">
        ✕ Not interested
      </span>
    );
  return <span className="text-xs text-zinc-600">—</span>;
}

function CandidateRow({
  row: c,
  checked,
  onToggle,
  onCall,
}: {
  row: CandidateListItem;
  checked: boolean;
  onToggle: () => void;
  onCall: () => void;
}) {
  const reason = disabledReason(c);
  const last = c.last_call;
  const retry =
    c.retry_status && c.retry_status.kind !== "exhausted" ? retryStatusText(c.retry_status) : null;
  const facts = [c.phone, c.total_experience == null ? "" : `${c.total_experience} yrs`]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      className={`grid grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 rounded-2xl px-3 py-3 transition md:grid-cols-[20px_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_auto] ${
        checked ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
      }`}
    >
      <input
        type="checkbox"
        aria-label={`Select ${c.name}`}
        checked={checked}
        disabled={!c.eligibility.can_call}
        title={reason || undefined}
        onChange={onToggle}
        className="accent-zinc-300"
      />

      <div className="flex min-w-0 items-center gap-3">
        <span className="font-display flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/5 text-xs font-semibold text-zinc-200">
          {initials(c.name)}
        </span>
        <div className="min-w-0">
          <Link
            href={`/candidates/${c.id}`}
            className="block truncate font-medium text-white hover:underline"
          >
            {c.name}
          </Link>
          <div className="truncate text-xs text-zinc-500 tabular-nums">{facts}</div>
          {(c.opted_out || c.open_conflicts > 0) && (
            <div className="mt-0.5 text-xs text-red-300">
              {c.opted_out
                ? "Opted out"
                : `${c.open_conflicts} answer${c.open_conflicts === 1 ? "" : "s"} to check`}
            </div>
          )}
        </div>
      </div>

      <div className="col-start-2 min-w-0 md:col-start-auto">
        {last ? (
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge kind="call" status={last.call_status} />
            <span className="text-xs text-zinc-500">{timeAgo(last.at)}</span>
          </div>
        ) : (
          <span className="text-xs text-zinc-500">Not called</span>
        )}
        {retry && <div className="mt-1 text-xs text-zinc-400">{retry}</div>}
      </div>

      <div className="col-start-2 md:col-start-auto">
        <ResultPill value={c.interested} />
      </div>

      <div className="col-start-3 row-start-1 flex items-center justify-end gap-1 md:col-start-auto md:row-start-auto">
        {c.last_call_has_transcript && last && (
          <Link
            href={`/candidates/${c.id}?call=${last.id}`}
            className="rounded-lg px-2 py-1 text-xs text-zinc-400 hover:bg-white/5 hover:text-white"
          >
            Transcript
          </Link>
        )}
        <button
          type="button"
          onClick={onCall}
          disabled={!c.eligibility.can_call}
          title={reason || (last?.terminal ? "Call again" : "Start a screening call")}
          aria-label={`${last?.terminal ? "Call again" : "Call"} ${c.name}${reason ? ` (${reason})` : ""}`}
          className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-200 transition hover:border-white/30 hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
        >
          {last?.terminal ? "Call again" : "Call"}
        </button>
      </div>
    </li>
  );
}

/** No list yet: a big friendly upload area with the three steps. */
function EmptyUpload({ href }: { href: string }) {
  const steps = ["Upload a list", "We call everyone", "See who's interested"];
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center">
      <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 text-zinc-300">
        <svg
          viewBox="0 0 24 24"
          className="h-6 w-6"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 15V4" />
          <path d="m7 9 5-5 5 5" />
          <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
        </svg>
      </span>
      <p className="font-display mt-4 text-lg font-semibold text-white">No candidates yet</p>
      <p className="mx-auto mt-1 max-w-2xl text-sm text-zinc-500">
        Upload a .csv or .xlsx with names and phone numbers.
        <br className="hidden sm:block" /> The call asks if they&apos;re open to a change, collects
        their details and checks the must-haves.
      </p>
      <ol className="mx-auto mt-6 flex max-w-lg flex-wrap items-center justify-center gap-2 text-xs text-zinc-400">
        {steps.map((step, i) => (
          <li key={step} className="flex items-center gap-2">
            <span className="flex items-center gap-2 rounded-full bg-white/5 px-3 py-1">
              <span className="font-display text-zinc-500">{i + 1}</span>
              {step}
            </span>
            {i < steps.length - 1 && <span className="text-zinc-700">→</span>}
          </li>
        ))}
      </ol>
      <Link href={href} className={`${buttonClass("primary")} mt-6`}>
        Upload a list
      </Link>
    </div>
  );
}
