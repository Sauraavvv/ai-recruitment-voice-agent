"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useState } from "react";

import { Alert, Button, Card, Field, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import {
  SCREENING_STATUS_LABELS,
  SCREENING_STATUS_TONE,
  formatDate,
  initials,
  yesNo,
} from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { deleteCandidate, getCandidate, updateCandidate } from "@/services/candidates";
import { listJobs } from "@/services/jobs";
import type { Candidate, CandidateUpdate } from "@/types";

import { CallButton, CallsPanel, useCalls } from "./calls-panel";

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
  const candidate = useLoad(`candidate:${id}`, () => getCandidate(id));
  const jobs = useLoad("jobs", listJobs);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const calls = useCalls(id, candidate.reload);

  if (candidate.error?.status === 404) {
    return (
      <>
        <BackLink />
        <PageHeader title="Candidate not found" />
      </>
    );
  }
  if (candidate.error) return <Alert>{errorMessage(candidate.error)}</Alert>;
  const c = candidate.data;
  if (!c) return <Muted>Loading…</Muted>;

  const job = jobs.data?.find((j) => j.id === c.job_id);

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
    const jobId = String(form.get("job_id"));
    if (jobId && jobId !== current.job_id) changes.job_id = jobId;

    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    if (await save(changes as CandidateUpdate, "Saved")) setEditing(false);
  }

  async function onOptOut() {
    if (
      !window.confirm(
        "Mark this candidate as opted out? They will never be called. This can't be undone.",
      )
    ) {
      return;
    }
    await save({ opted_out: true }, "Marked as opted out");
  }

  async function onDelete() {
    if (!window.confirm(`Delete ${c?.name}? They will be hidden and never called.`)) return;
    setBusy(true);
    try {
      await deleteCandidate(id);
      router.push("/candidates");
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
      setBusy(false);
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
              <span
                className={`rounded-full px-2.5 py-1 text-xs whitespace-nowrap ${
                  SCREENING_STATUS_TONE[c.screening_status] ?? "bg-white/5 text-zinc-400"
                }`}
              >
                {SCREENING_STATUS_LABELS[c.screening_status]}
              </span>
              {c.opted_out && (
                <span className="rounded-full bg-red-500/15 px-2.5 py-1 text-xs text-red-300">
                  Opted out
                </span>
              )}
            </div>
            <p className="mt-1 truncate text-sm text-zinc-500">
              {c.applied_role}
              {c.current_location ? ` · ${c.current_location}` : ""}
              {" · "}
              <span className="tabular-nums">{c.phone}</span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CallButton calls={calls} canCall={!c.opted_out && !!c.consent_at} />
          {!c.opted_out && (
            <Button variant="secondary" onClick={onOptOut} disabled={busy}>
              Mark opted out
            </Button>
          )}
          <Button variant="danger" onClick={onDelete} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>

      {[message, calls.message].map(
        (m, i) =>
          m && (
            <div key={i} className="mb-4">
              <Alert kind={m.kind}>{m.text}</Alert>
            </div>
          ),
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-4">
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
                <Field label="Job">
                  <select name="job_id" defaultValue={c.job_id} className={inputClass}>
                    {jobs.data?.map((j) => (
                      <option key={j.id} value={j.id}>
                        {j.job_title} — {j.company_name}
                      </option>
                    )) ?? <option value={c.job_id}>Loading…</option>}
                  </select>
                </Field>
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
        </div>

        <div className="space-y-4">
          <Card title="Screening results" description="Filled in by the screening calls.">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat
                label="Interested"
                value={yesNo(c.interested)}
                tone={
                  c.interested === true
                    ? "text-[#5fd35f]"
                    : c.interested === false
                      ? "text-red-300"
                      : undefined
                }
              />
              <Stat label="Relevant experience" value={years(c.relevant_experience)} />
              <Stat label="Notice period" value={c.notice_period} />
              <Stat label="Current CTC" value={lpa(c.current_ctc)} />
              <Stat label="Expected CTC" value={lpa(c.expected_ctc)} />
              <Stat label="Interview availability" value={c.interview_availability} />
            </div>
            <div className="mt-3 rounded-2xl bg-[#202226] p-4">
              <div className="text-xs text-zinc-500">Reason for change</div>
              <p className="mt-1 text-sm text-zinc-200">{c.reason_for_change || "—"}</p>
            </div>
          </Card>

          <CallsPanel calls={calls} />
        </div>
      </div>
    </>
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

function Stat({ label, value, tone }: { label: string; value: string | null; tone?: string }) {
  return (
    <div className="rounded-2xl bg-[#202226] p-4">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`mt-1 text-sm font-medium break-words ${tone ?? "text-white"}`}>
        {value || "—"}
      </div>
    </div>
  );
}

const years = (v: number | null) => (v == null ? null : `${v} yrs`);
const lpa = (v: number | null) => (v == null ? null : `${v} LPA`);
