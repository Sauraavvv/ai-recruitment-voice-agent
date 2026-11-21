"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import {
  Alert,
  Button,
  Card,
  Field,
  Muted,
  PageHeader,
  buttonClass,
  inputClass,
} from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { getClient } from "@/services/clients";
import { confirmImport, remapImport, uploadImport } from "@/services/imports";
import { listJobs } from "@/services/jobs";
import { getRequirement } from "@/services/requirements";
import type { ImportPreview, ImportRow } from "@/types";

const STATUS_LABELS: Record<ImportRow["status"], string> = {
  valid: "Valid",
  invalid: "Invalid",
  duplicate_in_file: "Duplicate in file",
  duplicate_existing: "Already exists",
};

const STATUS_STYLES: Record<ImportRow["status"], string> = {
  valid: "text-green-700 dark:text-green-400",
  invalid: "text-red-700 dark:text-red-400",
  duplicate_in_file: "text-amber-700 dark:text-amber-400",
  duplicate_existing: "text-amber-700 dark:text-amber-400",
};

/** ?requirement=<id>: the list is for that requirement (its screening calls), not for a job. */
function useRequirementTarget() {
  const requirementId = useSearchParams().get("requirement");
  const { data, error } = useLoad(
    requirementId ? `upload-target:${requirementId}` : null,
    async () => {
      const requirement = await getRequirement(requirementId as string);
      const client = await getClient(requirement.client_id);
      return { requirement, client };
    },
  );
  return { requirementId, target: data, error };
}

export function UploadFlow() {
  const forRequirement = useRequirementTarget();
  const requirementId = forRequirement.requirementId;
  const back = forRequirement.target
    ? `/clients/${forRequirement.target.client.id}/requirements/${forRequirement.target.requirement.id}`
    : "/candidates";
  const jobs = useLoad(requirementId ? null : "jobs", listJobs);
  const activeJob = jobs.data?.find((j) => j.is_active);
  const [jobId, setJobId] = useState<string>("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<ImportPreview>) {
    setBusy(true);
    setError(null);
    try {
      setPreview(await action());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose a .csv or .xlsx file");
      return;
    }
    setConsent(false);
    void run(() =>
      uploadImport(
        file,
        requirementId ? { requirementId } : { jobId: jobId || activeJob?.id || null },
      ),
    );
  }

  function onMappingChange(field: string, value: string) {
    if (!preview) return;
    const mapping = { ...preview.column_mapping, [field]: value === "" ? null : Number(value) };
    void run(() => remapImport(preview.id, mapping));
  }

  const done = preview?.status === "confirmed";
  const report = preview?.report;

  return (
    <>
      <PageHeader
        title="Upload candidates"
        subtitle={
          forRequirement.target
            ? `For ${forRequirement.target.requirement.title} at ${forRequirement.target.client.name}. Check the preview, then confirm.`
            : "Import a .csv or .xlsx file, check the preview, then confirm."
        }
      >
        {forRequirement.target && (
          <Link href={back} className={buttonClass("secondary")}>
            Back to requirement
          </Link>
        )}
      </PageHeader>
      {forRequirement.error && (
        <div className="mb-4">
          <Alert>This requirement can&apos;t be opened. {errorMessage(forRequirement.error)}</Alert>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {!preview && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card
            title="Upload a file"
            description={
              requirementId
                ? "Candidates are added to this requirement for screening calls."
                : "Candidates are added to the selected job."
            }
            className="lg:col-span-3"
          >
            <div className="space-y-4">
              {!requirementId && jobs.data?.length === 0 && (
                <Alert>
                  No job is configured yet.{" "}
                  <Link href="/settings/job" className="underline">
                    Create the job first
                  </Link>
                  .
                </Alert>
              )}

              <form onSubmit={onUpload} className="space-y-4">
                {forRequirement.target ? (
                  <Field label="Requirement">
                    <div className="rounded-lg border border-[#34363d] bg-[#202226] px-3 py-2 text-sm text-zinc-200">
                      {forRequirement.target.requirement.title} ·{" "}
                      {forRequirement.target.client.name}
                    </div>
                  </Field>
                ) : (
                  <Field label="Job">
                    <select
                      value={jobId || activeJob?.id || ""}
                      onChange={(e) => setJobId(e.target.value)}
                      className={inputClass}
                    >
                      {jobs.data?.map((job) => (
                        <option key={job.id} value={job.id}>
                          {job.job_title} — {job.company_name}
                          {job.is_active ? " (active)" : ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                )}
                <Field label="File">
                  <input
                    name="file"
                    type="file"
                    accept=".csv,.xlsx"
                    required
                    className="block w-full cursor-pointer rounded-xl border border-dashed border-[#34363d] bg-[#202226] p-5 text-sm text-zinc-400 file:mr-4 file:rounded-lg file:border-0 file:bg-[#2c2f35] file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-zinc-100 hover:border-zinc-500"
                  />
                </Field>
                <Button
                  type="submit"
                  disabled={busy || (requirementId ? !forRequirement.target : !jobs.data?.length)}
                >
                  {busy ? "Reading file…" : "Upload and preview"}
                </Button>
              </form>
            </div>
          </Card>
          <Card title="File format" className="lg:col-span-2">
            <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-300 marker:text-zinc-600">
              <li>.csv or .xlsx (save older .xls files as .xlsx), up to 5 MB and 1,000 rows.</li>
              <li>
                The first row holds column names. Required: <b>Candidate name</b>,{" "}
                <b>Phone number</b>
                {requirementId ? (
                  <> (the job role is the requirement&apos;s)</>
                ) : (
                  <>
                    , <b>Job role</b>
                  </>
                )}
                . Optional: email, total experience, current company, current location, resume URL,
                source, recruiter notes.
              </li>
              <li>
                Format the phone column as <b>Text</b> in Excel so long numbers aren&apos;t turned
                into scientific notation.
              </li>
              <li>Numbers already in the system are reported as duplicates and left unchanged.</li>
            </ul>
            <a
              href="/candidate-template.csv"
              download
              className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-[#60a5fa] hover:underline"
            >
              Download the template (.csv)
            </a>
          </Card>
        </div>
      )}

      {preview && report && (
        <Card>
          <section className="space-y-6">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <span>
                <b>{preview.filename}</b>
              </span>
              <span>Rows: {report.total_rows}</span>
              <span className="text-green-700 dark:text-green-400">
                Valid: {report.valid_candidates}
              </span>
              <span className="text-amber-700 dark:text-amber-400">
                Duplicates: {report.duplicate_candidates} ({report.duplicates_in_file} in file,{" "}
                {report.duplicates_existing} existing)
              </span>
              <span className="text-red-700 dark:text-red-400">
                Invalid: {report.invalid_candidates}
              </span>
              {done && <span className="font-medium">Imported: {report.imported_candidates}</span>}
            </div>

            {done ? (
              <Alert kind="success">
                Imported {report.imported_candidates} candidate
                {report.imported_candidates === 1 ? "" : "s"}.
                {report.imported_candidates < report.valid_candidates &&
                  " Some rows were added by someone else in the meantime and were skipped as duplicates."}{" "}
                <Link href={back} className="underline">
                  {requirementId ? "Back to the requirement" : "View candidates"}
                </Link>
              </Alert>
            ) : (
              <MappingEditor preview={preview} disabled={busy} onChange={onMappingChange} />
            )}

            {done ? (
              report.errors.length > 0 && <ErrorList errors={report.errors} />
            ) : (
              <PreviewTable rows={preview.rows} />
            )}

            {!done && (
              <div className="space-y-3 border-t border-white/10 pt-4">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                    className="mt-1"
                  />
                  These candidates have agreed to be contacted by phone about this role.
                </label>
                <div className="flex gap-2">
                  <Button
                    disabled={busy || !consent || report.valid_candidates === 0}
                    onClick={() => void run(() => confirmImport(preview.id))}
                  >
                    Import {report.valid_candidates} valid candidate
                    {report.valid_candidates === 1 ? "" : "s"}
                  </Button>
                  <Button variant="secondary" onClick={() => setPreview(null)} disabled={busy}>
                    Start over
                  </Button>
                </div>
                <Muted>
                  Invalid and duplicate rows are skipped. Nothing is saved until you import.
                </Muted>
              </div>
            )}

            {done && (
              <div className="flex gap-2">
                <Link href={back} className={buttonClass("primary")}>
                  {requirementId ? "Back to the requirement" : "View candidates"}
                </Link>
                <Button variant="secondary" onClick={() => setPreview(null)}>
                  Upload another file
                </Button>
              </div>
            )}
          </section>
        </Card>
      )}
    </>
  );
}

function MappingEditor({
  preview,
  disabled,
  onChange,
}: {
  preview: ImportPreview;
  disabled: boolean;
  onChange: (field: string, value: string) => void;
}) {
  return (
    <details open className="rounded-2xl bg-[#202226] p-4">
      <summary className="cursor-pointer text-sm font-medium text-white">Column mapping</summary>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {preview.fields.map((field) => (
          <Field key={field.key} label={`${field.label}${field.required ? " *" : ""}`}>
            <select
              value={preview.column_mapping[field.key] ?? ""}
              onChange={(e) => onChange(field.key, e.target.value)}
              disabled={disabled}
              className={inputClass}
            >
              <option value="">— not mapped —</option>
              {preview.headers.map((header, index) => (
                <option key={index} value={index}>
                  {header || `Column ${index + 1}`}
                </option>
              ))}
            </select>
          </Field>
        ))}
      </div>
      {preview.unmapped_columns.length > 0 && (
        <p className="mt-3 text-xs text-zinc-500">
          Ignored columns: {preview.unmapped_columns.join(", ")}
        </p>
      )}
    </details>
  );
}

function PreviewTable({ rows }: { rows: ImportRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-white/10 text-xs text-zinc-500 uppercase">
          <tr>
            <th className="py-2 pr-3">Row</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Phone</th>
            <th className="py-2 pr-3">Job role</th>
            <th className="py-2 pr-3">Email</th>
            <th className="py-2 pr-3">Exp.</th>
            <th className="py-2 pr-3">Problems</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.row} className="border-b border-white/5 align-top text-zinc-200">
              <td className="py-2 pr-3">{row.row}</td>
              <td className={`py-2 pr-3 whitespace-nowrap ${STATUS_STYLES[row.status]}`}>
                {STATUS_LABELS[row.status]}
              </td>
              <td className="py-2 pr-3">{String(row.values.name ?? "")}</td>
              <td className="py-2 pr-3 font-mono">{String(row.values.phone ?? "")}</td>
              <td className="py-2 pr-3">{String(row.values.applied_role ?? "")}</td>
              <td className="py-2 pr-3">{String(row.values.email ?? "")}</td>
              <td className="py-2 pr-3">{String(row.values.total_experience ?? "")}</td>
              <td className="py-2 pr-3 text-xs">
                {row.errors.map((e) => (
                  <div key={e.field + e.code} className="text-red-700 dark:text-red-400">
                    {e.field}: {e.message}
                    {row.existing_candidate_id && e.code === "duplicate_existing" && (
                      <>
                        {" "}
                        <Link
                          href={`/candidates/${row.existing_candidate_id}`}
                          className="underline"
                        >
                          view
                        </Link>
                      </>
                    )}
                  </div>
                ))}
                {row.warnings.map((w) => (
                  <div key={w.field + w.code} className="text-amber-700 dark:text-amber-400">
                    {w.field}: {w.message}
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorList({ errors }: { errors: ImportPreview["report"]["errors"] }) {
  return (
    <div>
      <h2 className="mb-2 text-sm font-medium">Skipped rows</h2>
      <ul className="space-y-1 text-sm">
        {errors.map((e, i) => (
          <li key={i}>
            Row {e.row} · {e.field}: {e.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
