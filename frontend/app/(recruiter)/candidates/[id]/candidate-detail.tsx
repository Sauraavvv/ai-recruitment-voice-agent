"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Alert, Button, Field, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { SCREENING_STATUS_LABELS, formatDate, yesNo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { deleteCandidate, getCandidate, updateCandidate } from "@/services/candidates";
import { listJobs } from "@/services/jobs";
import type { Candidate, CandidateUpdate } from "@/types";

import { CallsPanel } from "./calls-panel";

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

export function CandidateDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const candidate = useLoad(`candidate:${id}`, () => getCandidate(id));
  const jobs = useLoad("jobs", listJobs);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (candidate.error?.status === 404) {
    return (
      <>
        <PageHeader title="Candidate not found" />
        <Link href="/candidates" className="underline">
          Back to candidates
        </Link>
      </>
    );
  }
  if (candidate.error) return <Alert>{errorMessage(candidate.error)}</Alert>;
  const c = candidate.data;
  if (!c) return <Muted>Loading…</Muted>;

  async function save(changes: CandidateUpdate, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      candidate.setData(await updateCandidate(id, changes));
      setMessage({ kind: "success", text: success });
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>, current: Candidate) {
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
      setMessage({ kind: "success", text: "No changes to save" });
      return;
    }
    void save(changes as CandidateUpdate, "Saved");
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
      <PageHeader title={c.name}>
        {!c.opted_out && (
          <Button variant="secondary" onClick={onOptOut} disabled={busy}>
            Mark opted out
          </Button>
        )}
        <Button variant="danger" onClick={onDelete} disabled={busy}>
          Delete
        </Button>
      </PageHeader>

      {message && (
        <div className="mb-4">
          <Alert kind={message.kind}>{message.text}</Alert>
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 font-medium">Profile</h2>
          {/* key resets the form's default values after each save */}
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
                {jobs.data?.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.job_title} — {job.company_name}
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
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </section>

        <section className="space-y-6">
          <CallsPanel
            candidateId={c.id}
            canCall={!c.opted_out && !!c.consent_at}
            onCallEnded={candidate.reload}
          />
          <div>
            <h2 className="mb-3 font-medium">Screening</h2>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <Row label="Screening status" value={SCREENING_STATUS_LABELS[c.screening_status]} />
              <Row label="Opted out" value={yesNo(c.opted_out)} />
              <Row label="Interested" value={yesNo(c.interested)} />
              <Row label="Relevant experience" value={years(c.relevant_experience)} />
              <Row label="Current CTC" value={lpa(c.current_ctc)} />
              <Row label="Expected CTC" value={lpa(c.expected_ctc)} />
              <Row label="Notice period" value={c.notice_period} />
              <Row label="Reason for change" value={c.reason_for_change} />
              <Row label="Interview availability" value={c.interview_availability} />
            </dl>
            <p className="mt-2 text-xs text-zinc-500">
              Filled in by screening calls. Transcripts and summaries arrive with the dashboard.
            </p>
          </div>
          <div>
            <h2 className="mb-3 font-medium">Record</h2>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <Row
                label="Consent"
                value={
                  c.consent_source
                    ? `${c.consent_source === "manual" ? "Recorded manually" : "Attested at import"} · ${formatDate(c.consent_at)}`
                    : "Not recorded"
                }
              />
              <Row label="Added" value={formatDate(c.created_at)} />
              <Row label="Last updated" value={formatDate(c.updated_at)} />
            </dl>
          </div>
        </section>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <>
      <dt className="text-zinc-500">{label}</dt>
      <dd>{value || "—"}</dd>
    </>
  );
}

const years = (v: number | null) => (v == null ? null : `${v} yrs`);
const lpa = (v: number | null) => (v == null ? null : `${v} LPA`);
