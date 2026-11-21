"use client";

import Link from "next/link";
import { useState } from "react";

import { ConflictRow } from "@/components/screening-answers";
import { StartCallsDialog, type CallTarget } from "@/components/start-calls-dialog";
import { EmptyState, ErrorState, Skeleton } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button, Card } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { ATTENTION_LABELS, END_REASON_LABELS, shortDate, timeAgo } from "@/lib/labels";
import { resolveConflict } from "@/services/candidates";
import type { ActivityItem, AttentionItem, DashboardStats, QuickStart } from "@/types";

export type Range = "today" | "7d" | "all";
const RANGES: [Range, string][] = [
  ["today", "Today"],
  ["7d", "7 days"],
  ["all", "All time"],
];

type Metric = {
  key: keyof DashboardStats & string;
  label: string;
  dot?: string; // status colour, always next to the label
  tone?: string;
};
// One strip, three groups: who · calls · follow-up (design option B, 2026-11-19)
const GROUPS: Metric[][] = [
  [
    { key: "total_candidates", label: "Candidates" },
    { key: "screening_completed", label: "Screened" },
    { key: "interested_candidates", label: "Interested", tone: "text-[#5fd35f]" },
  ],
  [
    { key: "calls_completed", label: "Completed" },
    { key: "calls_in_progress", label: "On call", dot: "bg-[#5fd35f]" },
    { key: "calls_pending", label: "Pending", dot: "bg-[#93b4ff]" },
  ],
  [
    { key: "unanswered_calls", label: "Unanswered", dot: "bg-amber-300" },
    { key: "failed_calls", label: "Failed", dot: "bg-red-300" },
    { key: "scheduled_retries", label: "Retries" },
  ],
];

/** Today / 7 days / All time, shown beside the dashboard's title. */
export function RangeToggle({ range, onRange }: { range: Range; onRange: (range: Range) => void }) {
  return (
    <div className="flex gap-1 rounded-xl bg-[#18191c] p-1" role="group" aria-label="Range">
      {RANGES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => onRange(value)}
          aria-pressed={range === value}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
            range === value ? "bg-[#2a2c31] text-white" : "text-zinc-400 hover:text-white"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The statistics bar. The range switch (beside the title) already says which period the
 * call outcome numbers cover, so the tiles don't repeat it. */
export function StatTiles({ stats }: { stats: DashboardStats | undefined }) {
  return (
    <section aria-label="Statistics">
      {!stats ? (
        <Skeleton className="h-[104px] rounded-3xl" />
      ) : (
        <div className="grid grid-cols-1 rounded-3xl bg-[#18191c] py-5 md:grid-cols-3">
          {GROUPS.map((group, g) => (
            <div
              key={g}
              className={`grid grid-cols-3 ${
                g > 0
                  ? "mt-5 border-t border-white/15 pt-5 md:mt-0 md:border-t-0 md:border-l md:pt-0"
                  : ""
              }`}
            >
              {group.map((m, i) => (
                <div
                  key={m.key}
                  title={stats.definitions[m.key]}
                  className={`min-w-0 px-4 xl:px-5 ${i > 0 ? "border-l border-white/[0.06]" : ""}`}
                >
                  <div className="flex items-center gap-1.5 truncate text-xs text-zinc-400">
                    {m.dot && <span className={`h-[7px] w-[7px] shrink-0 rounded-full ${m.dot}`} />}
                    {m.label}
                  </div>
                  <div
                    data-testid="stat-value"
                    className={`font-display mt-2 text-[28px] leading-none font-semibold tabular-nums ${
                      m.tone ?? "text-white"
                    }`}
                  >
                    {String(stats[m.key])}
                  </div>
                  <span className="sr-only">{stats.definitions[m.key]}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function CallingProgress({
  stats,
  quick,
  onStarted,
}: {
  stats: DashboardStats | undefined;
  quick: QuickStart | undefined;
  onStarted: () => void;
}) {
  const [targets, setTargets] = useState<CallTarget[] | null>(null);
  const bars = stats
    ? [
        { label: "On the call", value: stats.calls_in_progress, color: "bg-[#0ca30c]" },
        { label: "Queued", value: stats.calls_pending, color: "bg-[#3987e5]" },
        { label: "Scheduled", value: stats.scheduled_retries, color: "bg-zinc-500" },
      ]
    : [];
  return (
    <Card title="Calling progress" description="Right now, across all candidates.">
      {!stats ? (
        <Skeleton className="h-24" />
      ) : (
        <ul className="space-y-2">
          {bars.map((b) => (
            <li key={b.label} className="flex items-center gap-3 text-sm">
              <span className={`h-2.5 w-2.5 rounded-full ${b.color}`} aria-hidden />
              <span className="flex-1 text-zinc-300">{b.label}</span>
              <span className="font-display text-lg font-semibold text-white tabular-nums">
                {b.value}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-5 border-t border-white/5 pt-4">
        {!quick ? (
          <Skeleton className="h-10" />
        ) : quick.total > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-zinc-300">
              <span className="font-semibold text-white">{quick.total}</span> candidate
              {quick.total === 1 ? "" : "s"} not called yet
            </p>
            <Button
              onClick={() =>
                setTargets(quick.candidates.map((c) => ({ id: c.candidate_id, name: c.name })))
              }
            >
              Call {Math.min(quick.total, quick.limit)} now
            </Button>
          </div>
        ) : (
          <p className="text-sm text-zinc-500">
            {quick.blocked_message
              ? `Can't call right now: ${quick.blocked_message}.`
              : "Everyone has been called."}{" "}
            {quick.blocked_reason === "calling_paused" && (
              <Link href="/settings" className="text-[#93b4ff] hover:underline">
                Resume calling
              </Link>
            )}
          </p>
        )}
        {quick && (
          <p className="mt-2 text-xs text-zinc-500">
            {quick.calling_now ? "Calling hours are open" : "Outside calling hours, or paused"} ·{" "}
            {quick.live_calls}/{quick.max_concurrent_calls} line
            {quick.max_concurrent_calls === 1 ? "" : "s"} in use
          </p>
        )}
      </div>
      <StartCallsDialog targets={targets} onClose={() => setTargets(null)} onStarted={onStarted} />
    </Card>
  );
}

export function AttentionList({
  items,
  error,
  onRetry,
  onChanged,
}: {
  items: AttentionItem[] | undefined;
  error: unknown;
  onRetry: () => void;
  onChanged: () => void;
}) {
  const notify = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function choose(item: AttentionItem, choice: "keep" | "use") {
    if (!item.conflict) return;
    const key = `${item.candidate_id}:${item.conflict.field}`;
    setBusy(key);
    try {
      await resolveConflict(item.candidate_id, item.conflict.field, choice);
      notify("success", `${item.candidate_name}: answer saved.`);
      onChanged();
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title="Needs attention"
      className="flex flex-col xl:absolute xl:inset-0"
      action={items && <span className="text-xs text-zinc-500 tabular-nums">{items.length}</span>}
    >
      {error && !items ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : !items ? (
        <Skeleton className="h-32" />
      ) : items.length === 0 ? (
        <EmptyState title="Nothing needs attention">
          Callbacks, failed calls, answers that disagree and sheet problems show up here.
        </EmptyState>
      ) : (
        <ul className="-mr-2 max-h-[30rem] min-h-0 flex-1 space-y-2 overflow-y-auto pr-2 xl:max-h-none">
          {items.map((item, i) =>
            item.reason === "data_conflict" && item.conflict ? (
              <ConflictRow
                key={`${item.candidate_id}-${item.conflict.field}`}
                conflict={item.conflict}
                candidateName={item.candidate_name}
                busy={busy === `${item.candidate_id}:${item.conflict.field}`}
                onChoose={(choice) => choose(item, choice)}
              />
            ) : (
              <li key={`${item.candidate_id}-${item.reason}-${i}`}>
                <Link
                  href={`/candidates/${item.candidate_id}${item.call_attempt_id ? `?call=${item.call_attempt_id}` : ""}`}
                  className="flex items-start gap-3 rounded-2xl bg-[#202226] p-3 text-sm transition hover:bg-[#25272c]"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-white">{item.candidate_name}</span>
                    {item.detail && (
                      <span className="block truncate text-xs text-zinc-500">
                        {attentionDetail(item.detail)}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block text-xs font-medium text-amber-200">
                      {ATTENTION_LABELS[item.reason] ?? item.reason}
                    </span>
                    <span className="block text-[11px] text-zinc-500">{timeAgo(item.at)}</span>
                  </span>
                </Link>
              </li>
            ),
          )}
        </ul>
      )}
    </Card>
  );
}

export function ActivityList({
  items,
  error,
  onRetry,
}: {
  items: ActivityItem[] | undefined;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <Card title="Recent activity">
      {error && !items ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : !items ? (
        <Skeleton className="h-32" />
      ) : items.length === 0 ? (
        <EmptyState
          title="No calls yet"
          action={{ href: "/candidates", label: "Go to candidates" }}
        >
          Start screening calls from the candidate list.
        </EmptyState>
      ) : (
        <ul className="-mr-2 max-h-[30rem] divide-y divide-white/5 overflow-y-auto pr-2">
          {items.map((a) => (
            <li key={a.call_attempt_id} className="flex items-center gap-3 py-2.5 text-sm">
              <span className="min-w-0 flex-1">
                <Link
                  href={`/candidates/${a.candidate_id}?call=${a.call_attempt_id}`}
                  className="block truncate font-medium text-white hover:underline"
                >
                  {a.candidate_name}
                </Link>
                <span className="text-xs text-zinc-500">
                  Call #{a.attempt_number}
                  {a.end_reason ? ` · ${END_REASON_LABELS[a.end_reason] ?? a.end_reason}` : ""}
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1">
                <StatusBadge kind="call" status={a.call_status} />
                <span className="text-[11px] text-zinc-500">{timeAgo(a.at)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** A due time arrives as an ISO date (callback due): show it as "20 Nov, 17:00". */
function attentionDetail(detail: string) {
  if (/^\d{4}-\d{2}-\d{2}T/.test(detail)) return shortDate(detail);
  return END_REASON_LABELS[detail] ?? detail;
}
