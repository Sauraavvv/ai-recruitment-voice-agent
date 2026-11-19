"use client";

import { useEffect, useRef, useState } from "react";

import { Alert, Button, Card, Muted } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import {
  CALL_STATUS_LABELS,
  END_REASON_LABELS,
  LIVE_CALL_STATUSES,
  formatDate,
} from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { listCalls, startCall } from "@/services/calls";

const POLL_MS = 3000;

const DOT_TONE: Record<string, string> = {
  completed: "bg-[#0ca30c]",
  no_answer: "bg-amber-400",
  busy: "bg-amber-400",
  failed: "bg-red-400",
};

type Message = { kind: "error" | "success"; text: string } | null;

/**
 * The candidate's calls and the action that starts one. While a call is happening the list
 * refreshes every few seconds; when it ends, the screening answers on the candidate have changed
 * too, so onCallEnded reloads them.
 */
export function useCalls(candidateId: string, onCallEnded: () => void) {
  const calls = useLoad(`calls:${candidateId}`, () => listCalls(candidateId));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const live = calls.data?.some((c) => LIVE_CALL_STATUSES.has(c.call_status)) ?? false;
  const { reload } = calls;

  const wasLive = useRef(false);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [live, reload]);
  useEffect(() => {
    if (wasLive.current && !live) onCallEnded();
    wasLive.current = live;
  }, [live, onCallEnded]);

  async function start() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await startCall(candidateId);
      if (result.ok) {
        setMessage({ kind: "success", text: "Call queued. The phone will ring in a few seconds." });
      } else {
        setMessage({ kind: "error", text: result.error?.message ?? "Could not start the call" });
      }
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return { calls, live, busy, message, start };
}

export type Calls = ReturnType<typeof useCalls>;

export function CallButton({ calls, canCall }: { calls: Calls; canCall: boolean }) {
  const { live, busy, start } = calls;
  return (
    <Button
      onClick={start}
      disabled={!canCall || busy || live}
      title={canCall ? undefined : "Opted out, or no consent recorded"}
    >
      {live ? "Call in progress…" : busy ? "Starting…" : "Call now"}
    </Button>
  );
}

/** The candidate's calls, newest first. */
export function CallsPanel({ calls: { calls } }: { calls: Calls }) {
  return (
    <Card
      title="Calls"
      description={
        calls.data?.length
          ? `${calls.data.length} attempt${calls.data.length === 1 ? "" : "s"}, newest first.`
          : "The AI assistant calls the candidate and asks the job's screening questions."
      }
    >
      {calls.error && <Alert>{errorMessage(calls.error)}</Alert>}
      {!calls.data ? (
        <Muted>Loading…</Muted>
      ) : calls.data.length === 0 ? (
        <Muted>No calls yet.</Muted>
      ) : (
        <ul className="-mr-2 max-h-[26rem] divide-y divide-white/5 overflow-y-auto pr-2">
          {calls.data.map((call) => {
            const isLive = LIVE_CALL_STATUSES.has(call.call_status);
            return (
              <li key={call.id} className="flex items-center gap-3 py-3 text-sm">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${isLive ? "animate-pulse bg-green-400" : (DOT_TONE[call.call_status] ?? "bg-zinc-600")}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-white">
                    {CALL_STATUS_LABELS[call.call_status] ?? call.call_status}
                    {call.end_reason && (
                      <span className="font-normal text-zinc-400">
                        {" · "}
                        {END_REASON_LABELS[call.end_reason] ?? call.end_reason}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-zinc-500">
                    Attempt {call.attempt_number} · {formatDate(call.start_time ?? call.created_at)}
                  </div>
                </div>
                {call.duration_seconds != null && (
                  <span className="text-xs text-zinc-400 tabular-nums">
                    {Math.floor(call.duration_seconds / 60)}:
                    {String(call.duration_seconds % 60).padStart(2, "0")}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
