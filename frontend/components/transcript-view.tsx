"use client";

import { useEffect, useRef } from "react";

import { ErrorState, SkeletonRows } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { END_REASON_LABELS, duration, formatDate } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { getTranscript } from "@/services/calls";
import type { CallAttempt } from "@/types";

const time = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "";

/**
 * Chat-style transcript of one call, with an attempt selector (phase-08 P8-T5). Lines the
 * candidate interrupted are marked, with what they heard before cutting in.
 */
export function TranscriptView({
  attempts,
  selected,
  onSelect,
  refreshKey,
}: {
  attempts: CallAttempt[];
  selected: string | null;
  onSelect: (id: string) => void;
  refreshKey?: string; // changes while a call is live → reload
}) {
  const transcript = useLoad(selected ? `transcript:${selected}:${refreshKey ?? ""}` : null, () =>
    getTranscript(selected as string),
  );
  const listRef = useRef<HTMLOListElement>(null);
  const t = transcript.data?.call_attempt_id === selected ? transcript.data : undefined;
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [t?.entries.length]);

  return (
    <div>
      {attempts.length > 0 && (
        <label className="mb-4 flex flex-wrap items-center gap-2 text-sm text-zinc-400">
          <span>Call</span>
          <select
            aria-label="Choose call"
            value={selected ?? ""}
            onChange={(e) => onSelect(e.target.value)}
            className="rounded-lg border border-[#34363d] bg-[#24262b] px-2 py-1.5 text-sm text-white"
          >
            {attempts.map((a) => (
              <option key={a.id} value={a.id}>
                #{a.attempt_number} · {formatDate(a.start_time ?? a.created_at)}
              </option>
            ))}
          </select>
          {t && (
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge kind="call" status={t.call_status} />
              {t.end_reason && (
                <span className="text-xs">{END_REASON_LABELS[t.end_reason] ?? t.end_reason}</span>
              )}
              {t.duration_seconds != null && (
                <span className="text-xs tabular-nums">{duration(t.duration_seconds)}</span>
              )}
            </span>
          )}
        </label>
      )}

      {!selected ? (
        <p className="text-sm text-zinc-500">No calls yet.</p>
      ) : transcript.error && !t ? (
        <ErrorState error={transcript.error} onRetry={transcript.reload} />
      ) : !t ? (
        <SkeletonRows rows={4} />
      ) : t.entries.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No conversation on this call
          {t.call_status === "completed" ? "." : " (it wasn't answered, or hasn't started)."}
        </p>
      ) : (
        <ol ref={listRef} className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
          {t.entries.map((line, i) => {
            const agent = line.speaker === "assistant";
            return (
              <li
                key={`${line.seq ?? "x"}-${i}`}
                className={`flex ${agent ? "justify-start" : "justify-end"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                    agent
                      ? "rounded-tl-md bg-white/5 text-zinc-200"
                      : "rounded-tr-md bg-[#1d4ed8]/25 text-white"
                  }`}
                >
                  <div className="mb-0.5 flex gap-2 text-[11px] text-zinc-500">
                    <span>{agent ? "HireCall AI" : "Candidate"}</span>
                    {line.timestamp && <span className="tabular-nums">{time(line.timestamp)}</span>}
                    {line.seq != null && <span className="tabular-nums">line {line.seq}</span>}
                  </div>
                  {line.text}
                  {line.interrupted && (
                    <div className="mt-1 text-[11px] text-amber-300">
                      Interrupted
                      {line.heard_text ? ` — heard: “${line.heard_text}”` : ""}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
