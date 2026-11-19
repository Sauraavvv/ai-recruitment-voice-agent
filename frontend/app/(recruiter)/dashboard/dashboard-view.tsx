"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Card } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { getDashboardSummary } from "@/services/dashboard";
import type { DashboardSummary } from "@/types";

import { CallsByDayChart, type BarRow, HorizontalBars, STATUS } from "./charts";

const REFRESH_MS = 15_000;

const percent = (rate: number | null | undefined) =>
  rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;

function duration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

function timeAgo(iso: string, now: number) {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-3xl bg-[#18191c] p-5">
      <div className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{label}</div>
      <div className="font-display mt-2 text-3xl font-semibold text-white tabular-nums">
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

const LIVE_LABELS: Record<string, string> = {
  queued: "Queued",
  initiating: "Dialing",
  ringing: "Ringing",
  in_progress: "On call",
};

function LiveCalls({ data, now }: { data: DashboardSummary; now: number }) {
  if (data.live_calls.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center text-center text-sm text-zinc-500">
        <span className="mb-2 h-2 w-2 rounded-full bg-zinc-600" />
        No calls right now
      </div>
    );
  }
  return (
    <ul className="divide-y divide-white/5">
      {data.live_calls.map((call) => {
        const onCall = call.call_status === "in_progress";
        const secs = Math.max(0, Math.round((now - new Date(call.started_at).getTime()) / 1000));
        return (
          <li key={call.call_attempt_id} className="flex items-center gap-3 py-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm font-medium text-white">
              {initials(call.candidate_name)}
            </span>
            <div className="min-w-0 flex-1">
              <Link
                href={`/candidates/${call.candidate_id}`}
                className="block truncate text-sm font-medium text-white hover:underline"
              >
                {call.candidate_name}
              </Link>
              <div className="truncate text-xs text-zinc-500">{call.applied_role}</div>
            </div>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                onCall ? "bg-[#0ca30c]/15 text-[#5fd35f]" : "bg-white/5 text-zinc-300"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${onCall ? "animate-pulse" : ""}`}
                style={{ background: onCall ? STATUS.good : STATUS.neutral }}
              />
              {LIVE_LABELS[call.call_status] ?? call.call_status}
              {onCall && <span className="tabular-nums">{duration(secs)}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Transcript({ data, now }: { data: DashboardSummary; now: number }) {
  const conv = data.latest_conversation;
  if (!conv) {
    return (
      <p className="py-10 text-center text-sm text-zinc-500">No calls with a transcript yet.</p>
    );
  }
  return <TranscriptLines conv={conv} now={now} />;
}

function TranscriptLines({
  conv,
  now,
}: {
  conv: NonNullable<DashboardSummary["latest_conversation"]>;
  now: number;
}) {
  const listRef = useRef<HTMLUListElement>(null);
  // Show the end of the conversation first (newest lines)
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [conv.call_attempt_id]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-2 text-xs text-zinc-500">
        <Link
          href={`/candidates/${conv.candidate_id}`}
          className="text-sm font-medium text-white hover:underline"
        >
          {conv.candidate_name}
        </Link>
        <span>
          {timeAgo(conv.ended_at, now)} · {duration(conv.duration_seconds)} · {conv.turns} lines
        </span>
      </div>
      <ul ref={listRef} className="max-h-72 space-y-2 overflow-y-auto pr-1">
        {conv.transcript.map((line, i) => {
          const agent = line.speaker === "assistant" || line.speaker === "agent";
          return (
            <li key={i} className={`flex ${agent ? "justify-start" : "justify-end"}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                  agent
                    ? "rounded-tl-md bg-white/5 text-zinc-200"
                    : "rounded-tr-md bg-[#1d4ed8]/25 text-white"
                }`}
              >
                <div className="mb-0.5 text-[11px] text-zinc-500">
                  {agent ? "HireCall AI" : "Candidate"}
                </div>
                {line.text}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function outcomeRows(outcomes: Record<string, number>): BarRow[] {
  const live = ["queued", "initiating", "ringing", "in_progress"].reduce(
    (sum, key) => sum + (outcomes[key] ?? 0),
    0,
  );
  const rows: BarRow[] = [
    { key: "completed", label: "Completed", value: outcomes.completed ?? 0, color: STATUS.good },
    { key: "no_answer", label: "No answer", value: outcomes.no_answer ?? 0, color: STATUS.warning },
    { key: "busy", label: "Busy", value: outcomes.busy ?? 0, color: STATUS.serious },
    { key: "failed", label: "Failed", value: outcomes.failed ?? 0, color: STATUS.critical },
    { key: "cancelled", label: "Cancelled", value: outcomes.cancelled ?? 0, color: STATUS.neutral },
    { key: "live", label: "In progress", value: live, color: STATUS.live },
  ];
  return rows.filter(
    (row) => row.value > 0 || ["completed", "no_answer", "failed"].includes(row.key),
  );
}

export function DashboardView() {
  const { data, error, reload } = useLoad("dashboard-summary", getDashboardSummary);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const refresh = setInterval(reload, REFRESH_MS);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(refresh);
      clearInterval(tick);
    };
  }, [reload]);

  if (!data) {
    return (
      <div className="rounded-3xl bg-[#18191c] p-6 text-sm text-zinc-500">
        {error ? `Couldn't load the dashboard: ${errorMessage(error)}` : "Loading…"}
      </div>
    );
  }

  const k = data.kpis;
  const f = data.funnel;
  const outcomes = outcomeRows(data.outcomes);
  const outcomeTotal = outcomes.reduce((sum, row) => sum + row.value, 0);
  const funnel: BarRow[] = [
    { key: "candidates", label: "Candidates", value: f.candidates, color: "#3987e5" },
    { key: "called", label: "Called", value: f.called, color: "#3987e5" },
    { key: "connected", label: "Connected", value: f.connected, color: "#3987e5" },
    { key: "screened", label: "Screened", value: f.screened, color: "#3987e5" },
    { key: "interested", label: "Interested", value: f.interested, color: "#3987e5" },
  ].map((row, i, all) => ({
    ...row,
    note:
      i > 0 && all[i - 1].value
        ? `${Math.round((row.value / all[i - 1].value) * 100)}%`
        : undefined,
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="Candidates"
          value={String(k.candidates_total)}
          hint={`${k.opted_out} opted out`}
        />
        <Kpi label="Screened" value={String(k.screened)} hint="screening completed" />
        <Kpi
          label="Interested"
          value={percent(k.interested_rate)}
          hint={`${k.interested} of ${k.screened} screened`}
        />
        <Kpi label="Calls placed" value={String(k.calls_total)} hint={`${k.calls_today} today`} />
        <Kpi
          label="Connect rate"
          value={percent(k.connect_rate)}
          hint={`${k.calls_connected} answered`}
        />
        <Kpi label="Avg call" value={duration(k.avg_call_seconds)} hint="answered calls" />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card
          title="Active AI calls"
          action={
            <span className="text-xs text-zinc-500 tabular-nums">
              {data.live_calls.length} live
            </span>
          }
        >
          <LiveCalls data={data} now={now} />
        </Card>
        <Card title="Latest call transcript" className="xl:col-span-2">
          <Transcript data={data} now={now} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Calls · last 14 days" className="xl:col-span-2">
          <CallsByDayChart days={data.calls_by_day} />
        </Card>
        <Card
          title="Call outcomes"
          action={<span className="text-xs text-zinc-500">all time</span>}
        >
          {outcomeTotal ? (
            <HorizontalBars rows={outcomes} total={outcomeTotal} />
          ) : (
            <p className="text-sm text-zinc-500">No calls yet.</p>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card
          title="Screening funnel"
          action={<span className="text-xs text-zinc-500">people, % of previous step</span>}
        >
          <HorizontalBars rows={funnel} />
        </Card>
        <Card
          title="Interview availability"
          action={<span className="text-xs text-zinc-500">interested candidates</span>}
        >
          {data.interview_availability.length ? (
            <ul className="divide-y divide-white/5">
              {data.interview_availability.map((row) => (
                <li key={row.candidate_id} className="flex items-start gap-3 py-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-medium text-white">
                    {initials(row.candidate_name)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/candidates/${row.candidate_id}`}
                      className="block truncate text-sm font-medium text-white hover:underline"
                    >
                      {row.candidate_name}
                    </Link>
                    <div className="text-sm text-zinc-300">{row.availability}</div>
                  </div>
                  {row.notice_period && (
                    <span className="shrink-0 rounded-full bg-white/5 px-2.5 py-1 text-xs text-zinc-400">
                      Notice {row.notice_period}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">No interested candidates with a time yet.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
