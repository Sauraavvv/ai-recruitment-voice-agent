"use client";

import Link from "next/link";
import { type DragEvent, useRef, useState } from "react";

import { Alert, Button, Field, inputClass } from "@/components/ui";
import { useModal } from "@/hooks/use-modal";
import { errorMessage } from "@/lib/api";
import { confirmImport, remapImport, uploadImport } from "@/services/imports";
import type { ImportPreview, ImportRow } from "@/types";

const STATUS_LABELS: Record<ImportRow["status"], string> = {
  valid: "Valid",
  invalid: "Invalid",
  duplicate_in_file: "Duplicate in file",
  duplicate_existing: "Already exists",
};

const STATUS_STYLES: Record<ImportRow["status"], string> = {
  valid: "text-green-400",
  invalid: "text-red-400",
  duplicate_in_file: "text-amber-400",
  duplicate_existing: "text-amber-400",
};

const ACCEPTED = /\.(csv|xlsx)$/i;

/** Upload a candidate list to a job, in a floating window over the job's page (blurred behind):
 * choose a file → check the preview → import. `onImported` refreshes the list behind it. */
export function UploadListDialog({
  open,
  requirementId,
  jobLabel,
  onClose,
  onImported,
}: {
  open: boolean;
  requirementId: string;
  jobLabel: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  function reset() {
    setPreview(null);
    setConsent(false);
    setError(null);
    setDragging(false);
    if (input.current) input.current.value = "";
  }

  function close() {
    if (busy) return;
    reset();
    onClose();
  }

  async function run(action: () => Promise<ImportPreview>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setPreview(next);
      if (next.status === "confirmed") onImported();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function pick(file: File | undefined) {
    if (!file) return;
    if (!ACCEPTED.test(file.name)) {
      setError("Choose a .csv or .xlsx file");
      return;
    }
    setConsent(false);
    void run(() => uploadImport(file, { requirementId }));
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files[0]);
  }

  function onMappingChange(field: string, value: string) {
    if (!preview) return;
    const mapping = { ...preview.column_mapping, [field]: value === "" ? null : Number(value) };
    void run(() => remapImport(preview.id, mapping));
  }

  const ref = useModal(open, close);
  const report = preview?.report;
  const done = preview?.status === "confirmed";
  // Every row is already in the system or can't be used: nothing to import from this file
  const nothingNew = Boolean(report && !done && report.valid_candidates === 0);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === ref.current) close(); // a click on the blurred background
      }}
      aria-labelledby="upload-title"
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(60rem,calc(100vw-2rem))] overflow-hidden rounded-3xl border border-white/10 bg-[#18191c] p-0 text-white shadow-2xl backdrop:bg-black/50 backdrop:backdrop-blur-md"
    >
      {open && (
        <div className="flex max-h-[calc(100dvh-2rem)] flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-white/5 px-6 py-5">
            <div className="min-w-0">
              <h2 id="upload-title" className="font-display text-lg font-semibold">
                Upload a list
              </h2>
              <p className="truncate text-sm text-zinc-500">For {jobLabel}</p>
            </div>
            <button
              type="button"
              onClick={close}
              disabled={busy}
              aria-label="Close upload"
              className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-white/5 hover:text-white disabled:opacity-40"
            >
              <svg
                viewBox="0 0 24 24"
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.8}
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </header>

          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
            {error && <Alert>{error}</Alert>}

            {!preview && (
              <>
                <label
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-12 text-center transition ${
                    dragging
                      ? "border-[#2563eb] bg-[#2563eb]/10"
                      : "border-white/15 bg-white/[0.02] hover:border-white/30"
                  } ${busy ? "pointer-events-none opacity-60" : ""}`}
                >
                  <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 text-zinc-300">
                    <svg
                      viewBox="0 0 24 24"
                      className="h-6 w-6"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={1.8}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M12 15V4" />
                      <path d="m7 9 5-5 5 5" />
                      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
                    </svg>
                  </span>
                  <span className="font-display mt-4 font-semibold text-white">
                    {busy ? "Reading the file…" : "Drop a .csv or .xlsx here, or click to choose"}
                  </span>
                  <span className="mt-1 text-sm text-zinc-500">
                    Up to 5 MB and 1,000 rows. Nothing is saved until you import.
                  </span>
                  <input
                    ref={input}
                    type="file"
                    accept=".csv,.xlsx"
                    aria-label="List file"
                    className="sr-only"
                    onChange={(e) => pick(e.target.files?.[0])}
                  />
                </label>
                <ul className="list-disc space-y-1.5 pl-5 text-sm text-zinc-400 marker:text-zinc-600">
                  <li>
                    First row: column names. Required:{" "}
                    <b className="text-zinc-200">Candidate name</b> and{" "}
                    <b className="text-zinc-200">Phone number</b>. Optional: email, total
                    experience, current company, current location, resume URL, source, notes.
                  </li>
                  <li>
                    Format the phone column as <b className="text-zinc-200">Text</b> in Excel so
                    long numbers stay whole. Numbers already in the system are skipped as
                    duplicates.
                  </li>
                  <li>
                    <a
                      href="/candidate-template.csv"
                      download
                      className="font-medium text-[#60a5fa] hover:underline"
                    >
                      Download the template (.csv)
                    </a>
                  </li>
                </ul>
              </>
            )}

            {preview && report && (
              <>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Count label="Rows" value={report.total_rows} />
                  <Count label="Valid" value={report.valid_candidates} tone="text-green-300" />
                  <Count
                    label="Duplicates"
                    value={report.duplicate_candidates}
                    tone="text-amber-300"
                  />
                  <Count label="Invalid" value={report.invalid_candidates} tone="text-red-300" />
                  {done && (
                    <Count label="Imported" value={report.imported_candidates} tone="text-white" />
                  )}
                  <span className="self-center truncate text-zinc-500">{preview.filename}</span>
                </div>

                {done ? (
                  <>
                    <Alert kind="success">
                      Imported {report.imported_candidates} candidate
                      {report.imported_candidates === 1 ? "" : "s"}. They&apos;re in the list now.
                      {report.imported_candidates < report.valid_candidates &&
                        " Some rows were added by someone else meanwhile and were skipped."}
                    </Alert>
                    {report.errors.length > 0 && <ErrorList errors={report.errors} />}
                  </>
                ) : (
                  <>
                    {nothingNew && (
                      <Alert kind="info">
                        Nothing new to import:{" "}
                        {report.invalid_candidates === 0
                          ? report.total_rows === 1
                            ? "this candidate is already in the system."
                            : "everyone in this file is already in the system."
                          : "every row is already in the system or has a problem (see below)."}{" "}
                        Fix the file, or choose another one.
                      </Alert>
                    )}
                    <MappingEditor preview={preview} disabled={busy} onChange={onMappingChange} />
                    <PreviewTable rows={preview.rows} />
                  </>
                )}
              </>
            )}
          </div>

          {preview && report && (
            <footer className="space-y-3 border-t border-white/5 px-6 py-4">
              {done ? (
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" onClick={reset}>
                    Upload another file
                  </Button>
                  <Button onClick={close}>Done</Button>
                </div>
              ) : nothingNew ? (
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" onClick={close} disabled={busy}>
                    Close
                  </Button>
                  <Button onClick={reset} disabled={busy}>
                    Choose another file
                  </Button>
                </div>
              ) : (
                <>
                  <label className="flex items-start gap-2 text-sm text-zinc-300">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                      className="mt-1"
                    />
                    These candidates have agreed to be contacted by phone about this role.
                  </label>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-zinc-500">
                      Invalid and duplicate rows are skipped.
                    </span>
                    <div className="flex gap-2">
                      <Button variant="secondary" onClick={reset} disabled={busy}>
                        Choose another file
                      </Button>
                      <Button
                        disabled={busy || !consent || report.valid_candidates === 0}
                        onClick={() => void run(() => confirmImport(preview.id))}
                      >
                        {busy
                          ? "Working…"
                          : `Import ${report.valid_candidates} valid candidate${
                              report.valid_candidates === 1 ? "" : "s"
                            }`}
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </footer>
          )}
        </div>
      )}
    </dialog>
  );
}

function Count({
  label,
  value,
  tone = "text-zinc-200",
}: {
  label: string;
  value: number;
  tone?: string;
}) {
  return (
    <span className="rounded-full bg-white/5 px-3 py-1 text-zinc-400">
      {label} <b className={`tabular-nums ${tone}`}>{value}</b>
    </span>
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
  const unmappedRequired = preview.fields.some(
    (f) => f.required && preview.column_mapping[f.key] == null,
  );
  return (
    <details open={unmappedRequired} className="rounded-2xl bg-[#202226] px-4 py-3">
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
    <div className="overflow-x-auto rounded-2xl border border-white/5">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-white/10 text-xs text-zinc-500 uppercase">
          <tr>
            <th className="px-3 py-2">Row</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Phone</th>
            <th className="px-3 py-2">Email</th>
            <th className="px-3 py-2">Exp.</th>
            <th className="px-3 py-2">Problems</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.row} className="border-b border-white/5 align-top text-zinc-200">
              <td className="px-3 py-2 text-zinc-500">{row.row}</td>
              <td className={`px-3 py-2 whitespace-nowrap ${STATUS_STYLES[row.status]}`}>
                {STATUS_LABELS[row.status]}
              </td>
              <td className="px-3 py-2">{String(row.values.name ?? "")}</td>
              <td className="px-3 py-2 font-mono">{String(row.values.phone ?? "")}</td>
              <td className="px-3 py-2">{String(row.values.email ?? "")}</td>
              <td className="px-3 py-2">{String(row.values.total_experience ?? "")}</td>
              <td className="px-3 py-2 text-xs">
                {row.errors.map((e) => (
                  <div
                    key={e.field + e.code}
                    className={e.code.startsWith("duplicate") ? "text-amber-400" : "text-red-400"}
                  >
                    {e.field}: {e.message}
                    {row.existing_candidate_id && e.code === "duplicate_existing" && (
                      <>
                        {" "}
                        <Link
                          href={`/candidates/${row.existing_candidate_id}`}
                          target="_blank"
                          rel="noopener"
                          className="underline"
                        >
                          view
                        </Link>
                      </>
                    )}
                  </div>
                ))}
                {row.warnings.map((w) => (
                  <div key={w.field + w.code} className="text-amber-400">
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
      <h3 className="mb-2 text-sm font-medium">Skipped rows</h3>
      <ul className="space-y-1 text-sm text-zinc-400">
        {errors.map((e, i) => (
          <li key={i}>
            Row {e.row} · {e.field}: {e.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
