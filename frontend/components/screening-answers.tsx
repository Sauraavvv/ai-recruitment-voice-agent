"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { FIELD_LABELS, fieldLabel, fieldValue } from "@/lib/labels";
import { resolveConflict } from "@/services/candidates";
import type { Candidate, Conflict } from "@/types";

type Meta = {
  status?: string;
  raw_text?: string | null;
  value?: unknown;
  conflict?: unknown;
  conflict_resolution?: { choice?: string } | null;
};

const WIDE = new Set(["reason_for_change", "interview_availability"]);

/** A field's chip: conflict wins over the stored status; no record = missing. */
export function fieldStatus(meta: Meta | undefined, value: unknown): string {
  if (meta?.conflict && typeof meta.conflict === "object") return "conflict";
  if (meta?.status) return meta.status;
  return value === null || value === undefined ? "missing" : "answered";
}

/**
 * The screening answers with a status chip each (answered, confirmed, declined, unclear,
 * missing, conflict) and the candidate's own words on hover (phase-08 P8-T4).
 */
export function ScreeningAnswers({ candidate: c }: { candidate: Candidate }) {
  const meta = (c.screening_field_meta ?? {}) as Record<string, Meta>;
  // Short answers first, the two free-text ones (full width) last
  const standard = Object.keys(FIELD_LABELS).sort(
    (a, b) => Number(WIDE.has(a)) - Number(WIDE.has(b)),
  );
  const custom = Object.keys(meta).filter((k) => !standard.includes(k));
  const rows = [...standard, ...custom].map((key) => {
    const value = standard.includes(key) ? c[key as keyof Candidate] : meta[key]?.value;
    return { key, value, meta: meta[key], status: fieldStatus(meta[key], value) };
  });
  return (
    <dl className="grid gap-2 sm:grid-cols-2">
      {rows.map(({ key, value, meta: m, status }) => {
        const quote = m?.raw_text;
        return (
          <div
            key={key}
            className={`rounded-2xl bg-[#202226] p-3.5 ${WIDE.has(key) ? "sm:col-span-2" : ""}`}
            title={quote ? `Candidate said: “${quote}”` : undefined}
          >
            <dt className="flex items-center justify-between gap-2 text-xs text-zinc-500">
              <span>{fieldLabel(key)}</span>
              <StatusBadge kind="field" status={status} className="px-2 py-0.5 text-[11px]" />
            </dt>
            <dd className="mt-1 text-sm font-medium break-words text-white">
              {fieldValue(key, value)}
            </dd>
            {quote && <dd className="mt-1 truncate text-xs text-zinc-500 italic">“{quote}”</dd>}
          </div>
        );
      })}
    </dl>
  );
}

/** Open conflicts with one-click resolution (decided with the user for Phase 8). */
export function ConflictList({
  candidateId,
  conflicts,
  onResolved,
  onOpenTranscript,
}: {
  candidateId: string;
  conflicts: Conflict[];
  onResolved: () => void;
  onOpenTranscript?: (attemptId: string) => void;
}) {
  const notify = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  if (!conflicts.length) return null;

  async function choose(c: Conflict, choice: "keep" | "use") {
    setBusy(c.field);
    try {
      await resolveConflict(candidateId, c.field, choice);
      notify(
        "success",
        `${fieldLabel(c.field)}: ${choice === "keep" ? "kept" : "now"} ${fieldValue(
          c.field,
          choice === "keep" ? c.stored_value : c.other_value,
        )}`,
      );
      onResolved();
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <ul className="space-y-3">
      {conflicts.map((c) => (
        <ConflictRow
          key={c.field}
          conflict={c}
          busy={busy === c.field}
          onChoose={(choice) => choose(c, choice)}
          onOpenTranscript={onOpenTranscript}
        />
      ))}
    </ul>
  );
}

export function ConflictRow({
  conflict: c,
  busy,
  onChoose,
  onOpenTranscript,
  candidateName,
}: {
  conflict: Conflict;
  busy: boolean;
  onChoose: (choice: "keep" | "use") => void;
  onOpenTranscript?: (attemptId: string) => void;
  candidateName?: string;
}) {
  return (
    <li className="rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-4 text-sm">
      <div className="mb-2 font-medium text-white">
        {candidateName ? `${candidateName} · ` : ""}
        {fieldLabel(c.field)}: two different answers
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-xl bg-black/30 p-3">
          <div className="text-xs text-zinc-500">Stored</div>
          <div className="font-medium text-white">{fieldValue(c.field, c.stored_value)}</div>
          {c.stored_quote && (
            <div className="mt-1 text-xs text-zinc-400 italic">
              “{c.stored_quote}”{c.stored_seq != null ? ` (line ${c.stored_seq})` : ""}
            </div>
          )}
        </div>
        <div className="rounded-xl bg-black/30 p-3">
          <div className="text-xs text-zinc-500">Also said</div>
          <div className="font-medium text-white">{fieldValue(c.field, c.other_value)}</div>
          {c.other_quote && (
            <div className="mt-1 text-xs text-zinc-400 italic">
              “{c.other_quote}”{c.other_seq != null ? ` (line ${c.other_seq})` : ""}
            </div>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" disabled={busy} onClick={() => onChoose("keep")}>
          Keep {fieldValue(c.field, c.stored_value)}
        </Button>
        <Button disabled={busy} onClick={() => onChoose("use")}>
          Use {fieldValue(c.field, c.other_value)}
        </Button>
        {onOpenTranscript && c.call_attempt_id && (
          <Button variant="secondary" onClick={() => onOpenTranscript(c.call_attempt_id as string)}>
            Open transcript
          </Button>
        )}
      </div>
    </li>
  );
}
