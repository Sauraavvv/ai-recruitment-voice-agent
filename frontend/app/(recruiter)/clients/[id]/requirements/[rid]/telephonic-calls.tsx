"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { RoundAnswers } from "@/components/round-answers";
import {
  MAX_CALLS_PER_ACTION,
  StartCallsDialog,
  type CallTarget,
  type Starter,
} from "@/components/start-calls-dialog";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import { formatDate, initials, timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { startTelephonicCalls, telephonicRoster } from "@/services/telephonic";
import type { RoundRow, RoundStatus } from "@/types";

import { Tab } from "./screening-card";

export const ROUND_STATUS: Record<RoundStatus, { label: string; tone: string }> = {
  not_called: { label: "Not called", tone: "text-zinc-500" },
  queued: { label: "Queued", tone: "bg-white/5 text-zinc-300" },
  on_call: { label: "On call", tone: "bg-green-500/10 text-green-300" },
  retry_scheduled: { label: "Retry scheduled", tone: "bg-white/5 text-zinc-300" },
  callback: { label: "Callback", tone: "bg-blue-500/10 text-blue-300" },
  done: { label: "Done", tone: "bg-green-500/10 text-green-300" },
  incomplete: { label: "Incomplete", tone: "bg-amber-400/10 text-amber-300" },
  no_answer: { label: "No answer", tone: "bg-white/5 text-zinc-400" },
  declined: { label: "Declined", tone: "bg-red-500/10 text-red-300" },
  opted_out: { label: "Opted out", tone: "bg-red-500/10 text-red-300" },
  failed: { label: "Failed", tone: "bg-red-500/10 text-red-300" },
};

type Group = "not_called" | "active" | "done" | "attention";
const GROUP_OF: Record<RoundStatus, Group> = {
  not_called: "not_called",
  queued: "active",
  on_call: "active",
  retry_scheduled: "active",
  callback: "active",
  done: "done",
  incomplete: "attention",
  no_answer: "attention",
  declined: "attention",
  opted_out: "attention",
  failed: "attention",
};
const GROUPS: { key: Group; label: string; dot: string }[] = [
  { key: "not_called", label: "Not called", dot: "bg-zinc-600" },
  { key: "active", label: "Scheduled or on call", dot: "bg-blue-400" },
  { key: "done", label: "Done", dot: "bg-green-400" },
  { key: "attention", label: "Needs a look", dot: "bg-amber-400" },
];
// Reasons the call dialog lets the recruiter override, so the button stays enabled
const OVERRIDABLE = new Set(["telephonic_done", "max_attempts_reached"]);

export function canStart(row: RoundRow): boolean {
  return row.eligibility.can_call || OVERRIDABLE.has(row.eligibility.reason ?? "");
}

/** The telephonic round's calls on the requirement page: the interested candidates, where
 * each stands, call buttons, and each finished call's answers. */
export function TelephonicCalls({
  requirementId,
  refreshKey,
}: {
  requirementId: string;
  refreshKey: number; // bumped when the questions are approved
}) {
  const [targets, setTargets] = useState<CallTarget[] | null>(null);
  const [filter, setFilter] = useState<Group | "all">("all");
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, reload } = useLoad(`round-roster:${requirementId}:${refreshKey}`, () =>
    telephonicRoster(requirementId),
  );
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const live = rows.some((r) => r.status === "queued" || r.status === "on_call");
  usePolling(reload, live);

  const counts = useMemo(() => {
    const out: Record<Group | "all", number> = {
      all: rows.length,
      not_called: 0,
      active: 0,
      done: 0,
      attention: 0,
    };
    for (const r of rows) out[GROUP_OF[r.status]] += 1;
    return out;
  }, [rows]);
  const notCalled = rows.filter((r) => r.status === "not_called" && r.eligibility.can_call);
  const shown = filter === "all" ? rows : rows.filter((r) => GROUP_OF[r.status] === filter);
  const starter: Starter = (ids, options) => startTelephonicCalls(requirementId, ids, options);

  if (data && data.approved_version == null) return null; // nothing to ask yet

  return (
    <section className="rounded-3xl bg-[#18191c] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-semibold text-white">Telephonic calls</h2>
          <p className="text-sm text-zinc-500">
            Candidates who said they&apos;re interested.
            {data?.approved_version != null &&
              ` New calls ask the approved questions (v${data.approved_version}).`}
          </p>
        </div>
        {rows.length > 0 && (
          <Button
            disabled={notCalled.length === 0}
            title={notCalled.length === 0 ? "Nobody left who can be called now" : undefined}
            onClick={() =>
              setTargets(
                notCalled.slice(0, MAX_CALLS_PER_ACTION).map((r) => ({
                  id: r.candidate_id,
                  name: r.name,
                })),
              )
            }
          >
            Call not-called ({Math.min(notCalled.length, MAX_CALLS_PER_ACTION)})
          </Button>
        )}
      </div>

      <div className="mt-5">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data ? (
          <div className="h-32 animate-pulse rounded-2xl bg-white/[0.03]" aria-label="Loading" />
        ) : rows.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-white/10 px-6 py-8 text-center text-sm text-zinc-500">
            Nobody is interested yet. Candidates who say yes on the screening call show up here.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5 border-b border-white/5 pb-3">
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
            {shown.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-500">Nobody here.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {shown.map((r) => (
                  <RoundRowView
                    key={r.candidate_id}
                    row={r}
                    current={data.approved_version}
                    open={open === r.last_call?.id}
                    onToggle={() =>
                      setOpen(open === r.last_call?.id ? null : (r.last_call?.id ?? null))
                    }
                    onCall={() => setTargets([{ id: r.candidate_id, name: r.name }])}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <StartCallsDialog
        targets={targets}
        onClose={() => setTargets(null)}
        onStarted={() => reload()}
        starter={starter}
        title="Start telephonic round calls?"
        note="The AI assistant introduces itself as an AI and asks the approved questions, one at a time."
      />
    </section>
  );
}

export function RoundRowView({
  row: r,
  current,
  open,
  onToggle,
  onCall,
}: {
  row: RoundRow;
  current: number | null;
  open: boolean;
  onToggle: () => void;
  onCall: () => void;
}) {
  const status = ROUND_STATUS[r.status];
  const last = r.last_call;
  const older = last?.version != null && current != null && last.version !== current;
  const again = r.done_before || Boolean(last?.terminal);
  const reason = canStart(r) ? "" : (r.eligibility.message ?? "Can't be called now");
  const answers = Boolean(last && last.finalized && last.questions > 0);
  const when = last
    ? r.status === "retry_scheduled" || r.status === "callback"
      ? last.next_retry_at
        ? `at ${formatDate(last.next_retry_at)}`
        : ""
      : timeAgo(last.at)
    : "";

  return (
    <li className={`rounded-2xl transition ${open ? "bg-white/[0.04]" : "hover:bg-white/[0.03]"}`}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-3 py-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)_auto]">
        <div className="flex min-w-0 items-center gap-3">
          <span className="font-display flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/5 text-xs font-semibold text-zinc-200">
            {initials(r.name)}
          </span>
          <div className="min-w-0">
            <Link
              href={`/candidates/${r.candidate_id}`}
              className="block truncate font-medium text-white hover:underline"
            >
              {r.name}
            </Link>
            <div className="truncate text-xs text-zinc-500 tabular-nums">{r.phone}</div>
          </div>
        </div>

        <div className="col-start-1 flex min-w-0 flex-wrap items-center gap-2 md:col-start-auto">
          <span
            className={`rounded-md px-2 py-0.5 text-xs ${status.tone} ${
              r.status === "on_call" ? "animate-pulse" : ""
            }`}
          >
            {status.label}
          </span>
          {when && <span className="text-xs text-zinc-500">{when}</span>}
          {last?.version != null && (
            <span
              className={`rounded-md px-1.5 py-0.5 text-[11px] ${
                older ? "bg-amber-400/10 text-amber-300" : "text-zinc-500"
              }`}
              title={
                older
                  ? `Asked v${last.version}; the approved questions are now v${current}`
                  : undefined
              }
            >
              v{last.version}
              {older && " · older"}
            </span>
          )}
          {answers && last && (
            <span className="text-xs text-zinc-500">
              {last.answered}/{last.questions} answered
            </span>
          )}
        </div>

        <div className="col-start-2 row-start-1 flex items-center justify-end gap-1 md:col-start-auto md:row-start-auto">
          {answers && (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              className="rounded-lg px-2 py-1 text-xs text-zinc-300 hover:bg-white/5 hover:text-white"
            >
              {open ? "Hide answers" : "Answers"}
            </button>
          )}
          <button
            type="button"
            onClick={onCall}
            disabled={!canStart(r)}
            title={reason || (again ? "Call again" : "Start the telephonic round")}
            aria-label={`${again ? "Call again" : "Call"} ${r.name}${reason ? ` (${reason})` : ""}`}
            className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-200 transition hover:border-white/30 hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
          >
            {again ? "Call again" : "Call"}
          </button>
        </div>
      </div>
      {open && last && (
        <div className="px-3 pb-4 md:pl-[60px]">
          <RoundAnswers
            attemptId={last.id}
            transcriptHref={
              last.has_transcript ? `/candidates/${r.candidate_id}?call=${last.id}` : undefined
            }
          />
        </div>
      )}
    </li>
  );
}
