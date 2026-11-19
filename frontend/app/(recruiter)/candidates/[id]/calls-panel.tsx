"use client";

import { useEffect, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, SkeletonRows } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button, Card } from "@/components/ui";
import { usePolling } from "@/hooks/use-polling";
import { errorMessage } from "@/lib/api";
import {
  ACTIVE_CALL_STATUSES,
  ATTEMPT_TYPE_LABELS,
  END_REASON_LABELS,
  LIVE_CALL_STATUSES,
  duration,
  formatDate,
} from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { cancelCall, hangupCall, listCalls, retryCall } from "@/services/calls";
import type { CallAttempt, Eligibility } from "@/types";

const CANCELLABLE = new Set(["pending", "queued", "retry_scheduled", "callback_requested"]);

/**
 * The candidate's calls. Refreshes every 3 s while a call is live (30 s otherwise, paused in a
 * hidden tab); when a call ends the screening answers changed too, so `onCallEnded` reloads them.
 */
export function useCalls(candidateId: string, onCallEnded: () => void) {
  const calls = useLoad(`calls:${candidateId}`, () => listCalls(candidateId));
  const live = calls.data?.some((c) => LIVE_CALL_STATUSES.has(c.call_status)) ?? false;
  const active = calls.data?.some((c) => ACTIVE_CALL_STATUSES.has(c.call_status)) ?? false;
  usePolling(calls.reload, active);

  const wasLive = useRef(false);
  useEffect(() => {
    if (wasLive.current && !live) onCallEnded();
    wasLive.current = live;
  }, [live, onCallEnded]);

  return { calls, live, active };
}

export type Calls = ReturnType<typeof useCalls>;

type Pending = { kind: "retry" | "cancel" | "hangup"; call: CallAttempt } | null;

/** Timeline of attempts with the recruiter's controls (phase-08 P8-T7, P8-T8). */
export function CallsPanel({
  calls: { calls },
  eligibility,
  onChanged,
  onShowTranscript,
}: {
  calls: Calls;
  eligibility: Eligibility | undefined;
  onChanged: () => void;
  onShowTranscript: (attemptId: string) => void;
}) {
  const notify = useToast();
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);
  const latest = calls.data?.[0];

  async function run() {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === "retry") {
        const result = await retryCall(pending.call.id);
        if (result.ok) notify("success", "Call queued. The phone will ring in a few seconds.");
        else notify("error", result.error?.message ?? "Can't call right now");
      } else if (pending.kind === "cancel") {
        await cancelCall(pending.call.id);
        notify("success", "Call cancelled.");
      } else {
        const result = await hangupCall(pending.call.id);
        notify(
          "success",
          result.ending
            ? "Ending the call: the AI is saying goodbye."
            : "The call is already ending.",
        );
      }
      calls.reload();
      onChanged();
      setPending(null);
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const retryBlocked = !eligibility?.can_call;
  return (
    <Card
      title="Call history"
      description={
        calls.data?.length
          ? `${calls.data.length} attempt${calls.data.length === 1 ? "" : "s"}, newest first.`
          : "The AI assistant calls the candidate and asks the job's screening questions."
      }
      action={
        latest &&
        !LIVE_CALL_STATUSES.has(latest.call_status) && (
          <Button
            variant="secondary"
            disabled={retryBlocked}
            title={retryBlocked ? (eligibility?.message ?? "Can't call right now") : undefined}
            onClick={() => setPending({ kind: "retry", call: latest })}
          >
            Retry call
          </Button>
        )
      }
    >
      {latest && retryBlocked && !LIVE_CALL_STATUSES.has(latest.call_status) && (
        <p className="-mt-2 mb-3 text-xs text-zinc-500">
          Retry unavailable: {eligibility?.message ?? "checking…"}
        </p>
      )}
      {calls.error && !calls.data && <ErrorState error={calls.error} onRetry={calls.reload} />}
      {!calls.data ? (
        !calls.error && <SkeletonRows rows={3} />
      ) : calls.data.length === 0 ? (
        <p className="text-sm text-zinc-500">No calls yet.</p>
      ) : (
        <ol className="-mr-2 max-h-[28rem] space-y-0 overflow-y-auto pr-2">
          {calls.data.map((call) => (
            <li key={call.id} className="relative border-l border-white/10 pb-4 pl-5 last:pb-0">
              <span
                className={`absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full ${
                  ACTIVE_CALL_STATUSES.has(call.call_status)
                    ? "animate-pulse bg-green-400"
                    : call.call_status === "completed"
                      ? "bg-[#0ca30c]"
                      : "bg-zinc-600"
                }`}
                aria-hidden
              />
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-white">#{call.attempt_number}</span>
                <StatusBadge kind="call" status={call.call_status} />
                <span className="text-xs text-zinc-500">
                  {ATTEMPT_TYPE_LABELS[call.attempt_type] ?? call.attempt_type}
                </span>
              </div>
              <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-zinc-400 sm:grid-cols-4">
                <div>
                  <dt className="sr-only">Started</dt>
                  <dd>{formatDate(call.start_time ?? call.created_at)}</dd>
                </div>
                <div>
                  <dt className="inline text-zinc-500">Length </dt>
                  <dd className="inline tabular-nums">{duration(call.duration_seconds)}</dd>
                </div>
                {call.end_reason && (
                  <div className="col-span-2">
                    <dt className="inline text-zinc-500">Ended: </dt>
                    <dd className="inline">
                      {END_REASON_LABELS[call.end_reason] ?? call.end_reason}
                    </dd>
                  </div>
                )}
                {call.next_retry_at && (
                  <div className="col-span-2">
                    <dt className="inline text-zinc-500">Next try: </dt>
                    <dd className="inline">{formatDate(call.next_retry_at)}</dd>
                  </div>
                )}
              </dl>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onShowTranscript(call.id)}
                  className="text-xs text-[#93b4ff] hover:underline"
                >
                  Transcript
                </button>
                {CANCELLABLE.has(call.call_status) && (
                  <button
                    type="button"
                    onClick={() => setPending({ kind: "cancel", call })}
                    className="text-xs text-red-300 hover:underline"
                  >
                    Cancel
                  </button>
                )}
                {call.call_status === "in_progress" && (
                  <button
                    type="button"
                    onClick={() => setPending({ kind: "hangup", call })}
                    className="text-xs text-red-300 hover:underline"
                  >
                    End call
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={
          pending?.kind === "retry"
            ? "Call again?"
            : pending?.kind === "cancel"
              ? "Cancel this call?"
              : "End this call now?"
        }
        confirmLabel={
          pending?.kind === "retry"
            ? "Call now"
            : pending?.kind === "cancel"
              ? "Cancel call"
              : "End call"
        }
        cancelLabel="Back"
        danger={pending?.kind !== "retry"}
        busy={busy}
        onConfirm={run}
        onClose={() => setPending(null)}
      >
        {pending?.kind === "retry" &&
          "A new screening call is queued and the phone rings in a few seconds."}
        {pending?.kind === "cancel" && "The call won't be placed. You can start a new one later."}
        {pending?.kind === "hangup" &&
          "The AI says a short goodbye and hangs up. Answers given so far are kept."}
      </ConfirmDialog>
    </Card>
  );
}
