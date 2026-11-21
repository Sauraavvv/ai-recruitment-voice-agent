"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, type ReactNode, useCallback, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ConflictList, ScreeningAnswers } from "@/components/screening-answers";
import { StartCallsDialog } from "@/components/start-calls-dialog";
import { ErrorState, Skeleton } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { SummaryCard } from "@/components/summary-card";
import { useToast } from "@/components/toast";
import { TranscriptView } from "@/components/transcript-view";
import { Alert, Button, Card, Field, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { formatDate, initials, retryStatusText, timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { deleteCandidate, getCandidate, getOverview, updateCandidate } from "@/services/candidates";
import { listJobs } from "@/services/jobs";
import { syncCandidate } from "@/services/settings";
import type { Candidate, CandidateOverview, CandidateUpdate } from "@/types";

import { CallsPanel, useCalls } from "./calls-panel";

const TEXT_FIELDS = [
  { key: "name", label: "Name", required: true },
  { key: "phone", label: "Phone", required: true },
  { key: "applied_role", label: "Applied role", required: true },
  { key: "email", label: "Email" },
  { key: "current_company", label: "Current company" },
  { key: "current_location", label: "Current location" },
  { key: "source", label: "Source" },
  { key: "resume_url", label: "Resume URL" },
] as const;

type Message = { kind: "error" | "success"; text: string } | null;

export function CandidateDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const notify = useToast();
  const candidate = useLoad(`candidate:${id}`, () => getCandidate(id));
  const overview = useLoad(`overview:${id}`, () => getOverview(id));
  const jobs = useLoad("jobs", listJobs);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [calling, setCalling] = useState(false);
  const [confirm, setConfirm] = useState<"opt_out" | "delete" | null>(null);
  const requested = useSearchParams().get("call");
  const [picked, setPicked] = useState<string | null>(requested);
  const transcriptRef = useRef<HTMLDivElement>(null);

  const reloadCandidate = candidate.reload;
  const reloadOverview = overview.reload;
  const refreshAll = useCallback(() => {
    reloadCandidate();
    reloadOverview();
  }, [reloadCandidate, reloadOverview]);
  const calls = useCalls(id, refreshAll);
  const attempts = calls.calls.data ?? [];
  const selected = picked ?? attempts[0]?.id ?? null;

  function showTranscript(attemptId: string) {
    setPicked(attemptId);
    transcriptRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (candidate.error?.status === 404) {
    return (
      <>
        <BackLink />
        <PageHeader title="Candidate not found" />
      </>
    );
  }
  if (candidate.error && !candidate.data) {
    return <ErrorState error={candidate.error} onRetry={candidate.reload} />;
  }
  const c = candidate.data;
  if (!c) return <DetailSkeleton />;

  const job = jobs.data?.find((j) => j.id === c.job_id);
  const eligibility = overview.data?.eligibility;
  const latestLive = attempts.find((a) =>
    ["pending", "queued", "initiating", "ringing", "in_progress"].includes(a.call_status),
  );

  async function save(changes: CandidateUpdate, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      candidate.setData(await updateCandidate(id, changes));
      setMessage({ kind: "success", text: success });
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>, current: Candidate) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const changes: Record<string, unknown> = {};
    for (const { key } of TEXT_FIELDS) {
      const value = String(form.get(key) ?? "").trim();
      const next = value === "" ? null : value;
      if (next !== (current[key] ?? null)) changes[key] = next;
    }
    const notes = String(form.get("recruiter_notes") ?? "").trim() || null;
    if (notes !== current.recruiter_notes) changes.recruiter_notes = notes;
    const expRaw = String(form.get("total_experience") ?? "").trim();
    const exp = expRaw === "" ? null : Number(expRaw);
    if (exp !== current.total_experience) changes.total_experience = exp;
    const jobId = form.get("job_id"); // absent for a requirement's candidate
    if (jobId && jobId !== current.job_id) changes.job_id = String(jobId);

    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    if (await save(changes as CandidateUpdate, "Saved")) setEditing(false);
  }

  async function onOptOut() {
    if (await save({ opted_out: true }, "Marked as opted out")) {
      overview.reload();
      calls.calls.reload(); // scheduled calls were cancelled
    }
    setConfirm(null);
  }

  async function onDelete() {
    setBusy(true);
    try {
      await deleteCandidate(id);
      notify("success", `${c?.name} was deleted.`);
      router.push("/candidates");
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
      setBusy(false);
      setConfirm(null);
    }
  }

  async function onSyncNow() {
    try {
      await syncCandidate(id);
      notify("success", "Sheet sync queued.");
      setTimeout(overview.reload, 3000);
    } catch (err) {
      notify("error", errorMessage(err));
    }
  }

  return (
    <>
      <BackLink />

      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/10 text-base font-medium text-white">
            {initials(c.name)}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display truncate text-2xl font-semibold text-white">{c.name}</h1>
              <StatusBadge kind="screening" status={c.screening_status} />
              {c.opted_out && (
                <span className="rounded-full bg-red-500/15 px-2.5 py-1 text-xs text-red-300">
                  Opted out
                </span>
              )}
              {latestLive && <StatusBadge kind="call" status={latestLive.call_status} />}
            </div>
            <p className="mt-1 truncate text-sm text-zinc-500">
              {c.applied_role}
              {c.current_location ? ` · ${c.current_location}` : ""}
              {" · "}
              <span className="tabular-nums">{c.phone}</span>
            </p>
            {retryStatusText(overview.data?.retry_status) && (
              <p className="mt-1 text-xs text-[#93b4ff]">
                Next: {retryStatusText(overview.data?.retry_status)}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => setCalling(true)}
            disabled={!eligibility?.can_call}
            title={eligibility && !eligibility.can_call ? (eligibility.message ?? "") : undefined}
          >
            {latestLive ? "Call in progress…" : "Call now"}
          </Button>
          {!c.opted_out && (
            <Button variant="secondary" onClick={() => setConfirm("opt_out")} disabled={busy}>
              Mark opted out
            </Button>
          )}
          <Button variant="danger" onClick={() => setConfirm("delete")} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>
      {eligibility && !eligibility.can_call && !latestLive && (
        <p className="-mt-3 mb-4 text-right text-xs text-zinc-500">
          Can&apos;t call now: {eligibility.message}
        </p>
      )}

      {message && (
        <div className="mb-4">
          <Alert kind={message.kind}>{message.text}</Alert>
        </div>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-stretch">
        {/* Left column: Call history (last) stretches to the bottom of the right column */}
        <div className="flex flex-col gap-4">
          <Card
            title="Details"
            action={
              !editing && (
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  Edit
                </Button>
              )
            }
          >
            {editing ? (
              // key resets the form's default values after each save
              <form key={c.updated_at} onSubmit={(e) => onSubmit(e, c)} className="space-y-3">
                {TEXT_FIELDS.map((f) => (
                  <Field key={f.key} label={`${f.label}${"required" in f ? " *" : ""}`}>
                    <input
                      name={f.key}
                      defaultValue={c[f.key] ?? ""}
                      required={"required" in f}
                      className={inputClass}
                    />
                  </Field>
                ))}
                <Field label="Total experience (years)">
                  <input
                    name="total_experience"
                    type="number"
                    min={0}
                    max={60}
                    step={0.5}
                    defaultValue={c.total_experience ?? ""}
                    className={inputClass}
                  />
                </Field>
                {c.job_id && (
                  <Field label="Job">
                    <select name="job_id" defaultValue={c.job_id} className={inputClass}>
                      {jobs.data?.map((j) => (
                        <option key={j.id} value={j.id}>
                          {j.job_title} — {j.company_name}
                        </option>
                      )) ?? <option value={c.job_id}>Loading…</option>}
                    </select>
                  </Field>
                )}
                <Field label="Recruiter notes">
                  <textarea
                    name="recruiter_notes"
                    rows={3}
                    defaultValue={c.recruiter_notes ?? ""}
                    className={inputClass}
                  />
                </Field>
                <div className="flex gap-2 pt-1">
                  <Button type="submit" disabled={busy}>
                    {busy ? "Saving…" : "Save"}
                  </Button>
                  <Button variant="secondary" onClick={() => setEditing(false)} disabled={busy}>
                    Cancel
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <dl className="divide-y divide-white/5 text-sm">
                  <DetailRow
                    label="Phone"
                    value={<span className="tabular-nums">{c.phone}</span>}
                  />
                  <DetailRow label="Email" value={c.email} />
                  <DetailRow label="Applied role" value={c.applied_role} />
                  <DetailRow
                    label="Job"
                    value={job ? `${job.job_title} · ${job.company_name}` : null}
                  />
                  <DetailRow label="Company" value={c.current_company} />
                  <DetailRow label="Location" value={c.current_location} />
                  <DetailRow label="Experience" value={years(c.total_experience)} />
                  <DetailRow label="Source" value={c.source} />
                  <DetailRow
                    label="Resume"
                    value={
                      c.resume_url && (
                        <a
                          href={c.resume_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[#93b4ff] hover:underline"
                        >
                          Open
                        </a>
                      )
                    }
                  />
                </dl>
                {c.recruiter_notes && (
                  <div className="mt-4 rounded-xl bg-white/[0.03] p-3 text-sm">
                    <div className="mb-1 text-xs text-zinc-500">Recruiter notes</div>
                    <p className="whitespace-pre-line text-zinc-300">{c.recruiter_notes}</p>
                  </div>
                )}
              </>
            )}
          </Card>

          <Card title="Record">
            <dl className="divide-y divide-white/5 text-sm">
              <DetailRow
                label="Consent"
                value={
                  c.consent_source
                    ? `${c.consent_source === "manual" ? "Manual" : "At import"} · ${formatDate(c.consent_at)}`
                    : "Not recorded"
                }
              />
              <DetailRow label="Added" value={formatDate(c.created_at)} />
              <DetailRow label="Updated" value={formatDate(c.updated_at)} />
            </dl>
          </Card>

          <SheetSyncCard overview={overview.data} onSyncNow={onSyncNow} />

          <CallsPanel
            calls={calls}
            eligibility={eligibility}
            onChanged={refreshAll}
            onShowTranscript={showTranscript}
          />
        </div>

        <div className="space-y-4">
          {overview.error && !overview.data && (
            <ErrorState error={overview.error} onRetry={overview.reload} />
          )}
          {overview.data && overview.data.conflicts.length > 0 && (
            <Card
              title="Answers that disagree"
              description="The call's final check heard a different answer. Pick the right one; the sheet follows."
            >
              <ConflictList
                candidateId={id}
                conflicts={overview.data.conflicts}
                onResolved={refreshAll}
                onOpenTranscript={showTranscript}
              />
            </Card>
          )}

          {overview.data ? (
            <SummaryCard summary={overview.data.summary} />
          ) : (
            <Skeleton className="h-32" />
          )}

          <Card
            title="Screening answers"
            description="Filled in by the screening calls. Hover an answer to see the candidate's words."
          >
            <ScreeningAnswers candidate={c} />
          </Card>

          <div ref={transcriptRef} className="scroll-mt-6">
            <Card title="Transcript">
              <TranscriptView
                attempts={attempts}
                selected={selected}
                onSelect={setPicked}
                refreshKey={attempts.find((a) => a.id === selected)?.updated_at ?? undefined}
              />
            </Card>
          </div>
        </div>
      </div>

      <StartCallsDialog
        targets={calling ? [{ id: c.id, name: c.name }] : null}
        onClose={() => setCalling(false)}
        onStarted={() => {
          calls.calls.reload();
          overview.reload();
        }}
      />
      <ConfirmDialog
        open={confirm === "opt_out"}
        title="Mark as opted out?"
        confirmLabel="Mark opted out"
        danger
        busy={busy}
        onConfirm={onOptOut}
        onClose={() => setConfirm(null)}
      >
        {c.name} will never be called again, and scheduled calls are cancelled. This can&apos;t be
        undone.
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "delete"}
        title={`Delete ${c.name}?`}
        confirmLabel="Delete"
        danger
        busy={busy}
        onConfirm={onDelete}
        onClose={() => setConfirm(null)}
      >
        They are hidden from lists and never called. Their call history is kept.
      </ConfirmDialog>
    </>
  );
}

function SheetSyncCard({
  overview,
  onSyncNow,
}: {
  overview: CandidateOverview | undefined;
  onSyncNow: () => void;
}) {
  if (!overview) return null;
  const sync = overview.sheet_sync;
  const text = !overview.sheets_configured
    ? "Google Sheets isn't set up"
    : sync.status === "failed"
      ? "Sync failed"
      : sync.status === "pending"
        ? "Waiting to sync"
        : sync.synced_at
          ? `Synced ${timeAgo(sync.synced_at)}`
          : "Not synced yet";
  return (
    <Card
      title="Google Sheet"
      action={
        overview.sheets_configured && (
          <Button variant="secondary" onClick={onSyncNow}>
            Sync now
          </Button>
        )
      }
    >
      <p
        className={`text-sm ${sync.status === "failed" ? "text-red-300" : "text-zinc-300"}`}
        role="status"
      >
        {text}
      </p>
      {sync.error && <p className="mt-1 text-xs text-zinc-500">{sync.error}</p>}
      {sync.status === "failed" && sync.next_attempt_at && (
        <p className="mt-1 text-xs text-zinc-500">Retrying {timeAgo(sync.next_attempt_at)}</p>
      )}
    </Card>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading">
      <Skeleton className="h-12 w-1/3" />
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <div className="mb-4">
      <Link
        href="/candidates"
        className="inline-flex items-center gap-1.5 text-sm text-zinc-400 transition hover:text-white"
      >
        <span aria-hidden>←</span> Back to candidates
      </Link>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
      <dt className="shrink-0 text-zinc-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-zinc-200">{value || "—"}</dd>
    </div>
  );
}

const years = (v: number | null) => (v == null ? null : `${v} yrs`);
