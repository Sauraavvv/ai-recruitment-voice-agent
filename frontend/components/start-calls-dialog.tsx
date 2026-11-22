"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Skeleton } from "@/components/states";
import { useToast } from "@/components/toast";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { startCalls } from "@/services/calls";
import { getSettings } from "@/services/settings";
import type { StartOptions } from "@/services/telephonic";
import type { SettingsPage, StartCallResult } from "@/types";

export const MAX_CALLS_PER_ACTION = 20;
const LIMIT_REACHED = "max_attempts_reached";
const ROUND_DONE = "telephonic_done";
// Reasons the recruiter may override for one candidate, with the checkbox text
const OVERRIDES: Record<string, string> = {
  [LIMIT_REACHED]: "Call anyway (one more attempt beyond the limit)",
  [ROUND_DONE]: "Call again (a second telephonic round)",
};

export type CallTarget = { id: string; name: string };
export type Starter = (ids: string[], options: StartOptions) => Promise<StartCallResult[]>;

const screeningStarter: Starter = (ids, o) => startCalls(ids, o.dryRun, o.overrideLimit);

type Check = { results: StartCallResult[]; settings: SettingsPage | null };

/**
 * Confirmation for every start, single or bulk (phase-08 P8-T3). Opening it asks the API who
 * could be called right now (a dry run, nothing queued) and shows who will be called and who
 * is skipped, with the reason; confirming queues the calls.
 */
export function StartCallsDialog({
  targets,
  onClose,
  onStarted,
  starter = screeningStarter,
  title = "Start screening calls?",
  note = "The AI assistant introduces itself as an AI and asks the job's screening questions.",
}: {
  targets: CallTarget[] | null; // null = closed
  onClose: () => void;
  onStarted?: (queued: number) => void;
  starter?: Starter; // screening calls by default; the telephonic round passes its own
  title?: string;
  note?: string;
}) {
  const notify = useToast();
  const [busy, setBusy] = useState(false);
  // Candidates whose attempts are used up and the recruiter chose to call anyway (phase-09)
  const [overrides, setOverrides] = useState<Set<string>>(new Set());
  const key = targets?.map((t) => t.id).join(",") ?? null;
  // A dry run each time the dialog opens: who could be called right now, and why not
  const loaded = useLoad<Check>(key && `start-check:${title}:${key}`, async () => {
    const [results, settings] = await Promise.all([
      starter((key as string).split(","), {
        dryRun: true,
        overrideLimit: false,
        callAgain: false,
      }),
      getSettings().catch(() => null),
    ]);
    return { results, settings };
  });
  const check = loaded.loading ? null : (loaded.data ?? null);
  const error = loaded.error;

  const names = new Map(targets?.map((t) => [t.id, t.name]));
  const ok = check?.results.filter((r) => r.ok) ?? [];
  const skipped = check?.results.filter((r) => !r.ok) ?? [];
  const forced = skipped.filter(
    (r) => (r.error?.code ?? "") in OVERRIDES && overrides.has(r.candidate_id),
  );
  const toCall = [...ok, ...forced];

  function toggleOverride(id: string) {
    setOverrides((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function close() {
    setOverrides(new Set());
    onClose();
  }

  async function confirm() {
    setBusy(true);
    try {
      const results = await starter(
        toCall.map((r) => r.candidate_id),
        {
          dryRun: false,
          overrideLimit: forced.some((r) => r.error?.code === LIMIT_REACHED),
          callAgain: forced.some((r) => r.error?.code === ROUND_DONE),
        },
      );
      const queued = results.filter((r) => r.ok).length;
      const refused = results.length - queued;
      notify(
        queued ? "success" : "error",
        queued
          ? `${queued} call${queued === 1 ? "" : "s"} queued${refused ? `, ${refused} skipped` : ""}.`
          : (results[0]?.error?.message ?? "No calls could be started"),
      );
      onStarted?.(queued);
      close();
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const general = check?.settings?.general;
  const plural = toCall.length === 1 ? "" : "s";
  return (
    <ConfirmDialog
      open={targets !== null}
      title={targets && targets.length === 1 ? `Call ${targets[0].name}?` : title}
      confirmLabel={toCall.length ? `Call ${toCall.length} candidate${plural}` : "Nobody to call"}
      confirmDisabled={!check || toCall.length === 0}
      busy={busy}
      onConfirm={confirm}
      onClose={close}
    >
      {error ? (
        <p className="text-red-300">{errorMessage(error)}</p>
      ) : !check ? (
        <div className="space-y-2">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : (
        <div className="space-y-4">
          {check.settings && general && (
            <dl className="grid grid-cols-2 gap-2 rounded-2xl bg-white/[0.03] p-3 text-xs">
              <div>
                <dt className="text-zinc-500">Calling hours</dt>
                <dd className="text-zinc-200">
                  {check.settings.calling_now ? "Open now" : "Closed now"} ·{" "}
                  {general.calling.start_hour}:00–{general.calling.end_hour}:00
                </dd>
              </div>
              <div>
                <dt className="text-zinc-500">At the same time</dt>
                <dd className="text-zinc-200">
                  {general.max_concurrent_calls} call
                  {general.max_concurrent_calls === 1 ? "" : "s"}, the rest wait in line
                </dd>
              </div>
            </dl>
          )}
          {ok.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-zinc-500 uppercase">
                Will be called ({ok.length})
              </div>
              <ul className="max-h-40 space-y-1 overflow-y-auto">
                {ok.map((r) => (
                  <li key={r.candidate_id} className="text-zinc-200">
                    {names.get(r.candidate_id) ?? r.candidate_id}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {skipped.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-zinc-500 uppercase">
                Skipped ({skipped.length})
              </div>
              <ul className="max-h-40 space-y-1 overflow-y-auto">
                {skipped.map((r) => (
                  <li key={r.candidate_id}>
                    <div className="flex justify-between gap-3">
                      <span className="truncate text-zinc-300">
                        {names.get(r.candidate_id) ?? r.candidate_id}
                      </span>
                      <span className="shrink-0 text-right text-amber-300">
                        {r.error?.message ?? "Can't be called"}
                      </span>
                    </div>
                    {(r.error?.code ?? "") in OVERRIDES && (
                      <label className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
                        <input
                          type="checkbox"
                          checked={overrides.has(r.candidate_id)}
                          onChange={() => toggleOverride(r.candidate_id)}
                          className="accent-[#1d4ed8]"
                        />
                        {OVERRIDES[r.error?.code ?? ""]}
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-zinc-500">{note}</p>
        </div>
      )}
    </ConfirmDialog>
  );
}
