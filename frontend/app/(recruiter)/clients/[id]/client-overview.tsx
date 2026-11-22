"use client";

import Link from "next/link";

import { EmptyState, ErrorState } from "@/components/states";
import { buttonClass } from "@/components/ui";
import { KpiBar } from "@/components/kpi-bar";
import { useLoad } from "@/lib/use-load";
import { listRequirements } from "@/services/requirements";
import type { RequirementListItem } from "@/types";

import { REQUIREMENT_STATUS, WORK_MODES, range } from "./requirements/requirement-form";

/** The left side of a client's page: its numbers, then its requirements (openings). */
export function ClientOverview({ clientId }: { clientId: string }) {
  const { data, error, reload } = useLoad(`requirements:${clientId}`, () =>
    listRequirements(clientId),
  );
  const add = `/clients/${clientId}/requirements/new`;

  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Skeleton />;

  const open = data.filter((r) => r.status === "open");
  const sum = (rows: RequirementListItem[], pick: (r: RequirementListItem) => number) =>
    rows.reduce((total, r) => total + pick(r), 0);

  // On wide screens this column is as tall as the client card beside it: the requirements
  // list grows (its last card stretches) so both bottoms line up.
  return (
    <div className="flex flex-col gap-8">
      <KpiBar
        items={[
          { label: "Open requirements", value: open.length },
          { label: "People needed", value: sum(open, (r) => r.openings) },
          { label: "Candidates", value: sum(data, (r) => r.candidates) },
          { label: "Interested", value: sum(data, (r) => r.interested), dot: "bg-green-400" },
          { label: "Filled", value: data.filter((r) => r.status === "filled").length },
        ]}
      />

      <section className="flex flex-1 flex-col">
        <div className="mb-4 flex items-center gap-4">
          <h2 className="font-display text-base font-semibold text-white">
            Requirements
            <span className="ml-2 rounded-full bg-white/5 px-2 py-0.5 text-xs font-normal text-zinc-400">
              {data.length}
            </span>
          </h2>
          <span className="h-px flex-1 bg-gradient-to-r from-white/10 to-transparent" />
          {data.length > 0 && (
            <Link href={add} className={buttonClass("secondary")}>
              + Add requirement
            </Link>
          )}
        </div>

        {data.length === 0 ? (
          <div className="flex flex-1 flex-col justify-center rounded-3xl bg-[#18191c] p-2">
            <EmptyState
              title="No requirements yet"
              action={{ href: add, label: "+ Add requirement" }}
            >
              Add an opening: the role, where, how many people, and who fits.
            </EmptyState>
          </div>
        ) : (
          <ul className="flex flex-1 flex-col gap-3">
            {data.map((r) => (
              <li key={r.id} className="last:flex-1">
                <RequirementRow clientId={clientId} r={r} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** "Due 31 Dec · 12 days left", or overdue. */
function deadlineText(deadline: string) {
  const due = new Date(`${deadline}T23:59:59`);
  const days = Math.ceil((due.getTime() - Date.now()) / 86_400_000);
  const date = due.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  if (days < 0) return { text: `Due ${date} · overdue`, late: true };
  if (days === 0) return { text: `Due today`, late: true };
  return { text: `Due ${date} · ${days} day${days === 1 ? "" : "s"} left`, late: days <= 3 };
}

/** One requirement: progress ring, role and details, the screening numbers, the deadline.
 * `clientName` shows the client above the title (in the list of all jobs). */
export function RequirementRow({
  clientId,
  clientName,
  href,
  r,
}: {
  clientId: string;
  clientName?: string;
  /** Where the row opens (default: the requirement under its client) */
  href?: string;
  r: RequirementListItem;
}) {
  const s = REQUIREMENT_STATUS[r.status];
  const details = [
    r.location,
    r.work_mode ? WORK_MODES[r.work_mode] : "",
    range(r.experience_min, r.experience_max, "yrs"),
    range(r.ctc_min, r.ctc_max, "LPA"),
  ].filter(Boolean);
  const due =
    r.deadline && (r.status === "open" || r.status === "on_hold") ? deadlineText(r.deadline) : null;

  return (
    <Link
      href={href ?? `/clients/${clientId}/requirements/${r.id}`}
      className={`group flex h-full items-center gap-5 rounded-3xl bg-[#18191c] p-5 ring-1 ring-white/5 transition hover:-translate-y-0.5 hover:bg-[#1c1e22] hover:shadow-[0_12px_32px_-16px_rgba(0,0,0,0.8)] focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:outline-none ${
        r.status === "closed" ? "opacity-60" : ""
      }`}
    >
      <ProgressRing done={r.interested} total={r.openings} />

      <div className="min-w-0 flex-1">
        {clientName && (
          <div className="mb-1 truncate text-[11px] tracking-wider text-zinc-500 uppercase">
            {clientName}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display truncate text-xl font-semibold tracking-tight text-white">
            {r.title}
          </span>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${s.tone}`}>
            {s.label}
          </span>
          {!r.job_description && (
            <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-xs text-zinc-400">
              No JD
            </span>
          )}
        </div>
        {details.length > 0 && (
          <div className="mt-1.5 truncate text-sm text-zinc-400">{details.join(" · ")}</div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zinc-500">
          <Step value={r.candidates} label={r.candidates === 1 ? "candidate" : "candidates"} />
          <span className="text-zinc-700">›</span>
          <Step value={r.called} label="called" />
          <span className="text-zinc-700">›</span>
          <Step value={r.interested} label="interested" />
          {r.created_by_name && (
            <>
              <span className="text-zinc-700">·</span>
              <span>
                Created by <span className="text-zinc-300">{r.created_by_name}</span>
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex shrink-0 flex-col items-end justify-between gap-6 self-stretch">
        {due ? (
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs ${
              due.late ? "bg-red-500/10 text-red-300" : "bg-white/5 text-zinc-400"
            }`}
          >
            {due.text}
          </span>
        ) : (
          <span />
        )}
        <span className="text-lg text-zinc-600 transition group-hover:translate-x-0.5 group-hover:text-zinc-200">
          →
        </span>
      </div>
    </Link>
  );
}

function Step({ value, label }: { value: number; label: string }) {
  return (
    <span>
      <span className="font-display text-base font-semibold text-white">{value}</span> {label}
    </span>
  );
}

/** A ring that fills as interested candidates reach the people needed: "0 / 3". */
function ProgressRing({ done, total }: { done: number; total: number }) {
  const size = 68;
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const share = Math.min(1, done / Math.max(total, 1));
  const full = share >= 1;
  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${done} of ${total} interested`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-white/[0.07]"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - share)}
          className={`transition-[stroke-dashoffset] duration-700 ${
            full ? "stroke-green-400" : "stroke-zinc-200"
          } ${share === 0 ? "opacity-0" : ""}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="font-display text-lg font-semibold text-white">{done}</span>
        <span className="mt-0.5 text-[10px] text-zinc-500">of {total}</span>
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-8" role="status" aria-label="Loading">
      <div className="h-[90px] animate-pulse rounded-3xl bg-[#18191c]" />
      {Array.from({ length: 2 }, (_, i) => (
        <div key={i} className="h-[120px] animate-pulse rounded-3xl bg-[#18191c]" />
      ))}
    </div>
  );
}
