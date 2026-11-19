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

/** The candidate's calls, newest first, and the button that starts a screening call. */
export function CallsPanel({
  candidateId,
  canCall,
  onCallEnded,
}: {
  candidateId: string;
  canCall: boolean;
  onCallEnded: () => void;
}) {
  const calls = useLoad(`calls:${candidateId}`, () => listCalls(candidateId));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const live = calls.data?.some((c) => LIVE_CALL_STATUSES.has(c.call_status)) ?? false;
  const { reload } = calls;

  // While a call is happening, refresh every few seconds; when it ends, the screening answers
  // on the candidate have changed too.
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

  async function onCall() {
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

  return (
    <Card
      title="Calls"
      description="The AI assistant calls the candidate and asks the job's screening questions."
      action={
        <Button onClick={onCall} disabled={!canCall || busy || live}>
          {live ? "Call in progress…" : busy ? "Starting…" : "Call now"}
        </Button>
      }
    >
      {message && (
        <div className="mb-4">
          <Alert kind={message.kind}>{message.text}</Alert>
        </div>
      )}
      {calls.error && <Alert>{errorMessage(calls.error)}</Alert>}
      {!calls.data ? (
        <Muted>Loading…</Muted>
      ) : calls.data.length === 0 ? (
        <Muted>No calls yet.</Muted>
      ) : (
        <ul className="divide-y divide-white/5">
          {calls.data.map((call) => {
            const isLive = LIVE_CALL_STATUSES.has(call.call_status);
            return (
              <li key={call.id} className="flex items-center gap-3 py-3 text-sm">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${isLive ? "animate-pulse bg-green-400" : "bg-zinc-600"}`}
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
