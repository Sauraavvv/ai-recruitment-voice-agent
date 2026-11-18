"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Alert, Button, buttonClass, Field, PageHeader, inputClass } from "@/components/ui";
import { ApiError, errorMessage } from "@/lib/api";
import { createCandidate } from "@/services/candidates";
import type { CandidateCreate } from "@/types";

function optional(form: FormData, name: string) {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

export function NewCandidateForm() {
  const router = useRouter();
  const [error, setError] = useState<{ message: string; existingId?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const experience = optional(form, "total_experience");
    const body: CandidateCreate = {
      name: String(form.get("name")),
      phone: String(form.get("phone")),
      applied_role: String(form.get("applied_role")),
      email: optional(form, "email"),
      total_experience: experience === null ? null : Number(experience),
      current_company: optional(form, "current_company"),
      current_location: optional(form, "current_location"),
      source: optional(form, "source"),
      recruiter_notes: optional(form, "recruiter_notes"),
      consent_attested: form.get("consent") === "on",
    };
    setBusy(true);
    setError(null);
    try {
      const candidate = await createCandidate(body);
      router.push(`/candidates/${candidate.id}`);
    } catch (err) {
      const details = err instanceof ApiError ? (err.details as Record<string, unknown>) : null;
      setError({
        message: errorMessage(err),
        existingId:
          err instanceof ApiError && err.code === "duplicate_phone" && !details?.deleted
            ? String(details?.existing_candidate_id)
            : undefined,
      });
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Add candidate" />
      <form onSubmit={onSubmit} className="max-w-xl space-y-4">
        {error && (
          <Alert>
            {error.message}
            {error.existingId && (
              <>
                {" "}
                <Link href={`/candidates/${error.existingId}`} className="underline">
                  Open existing candidate
                </Link>
              </>
            )}
          </Alert>
        )}
        <Field label="Name *">
          <input name="name" required maxLength={200} className={inputClass} />
        </Field>
        <Field label="Phone *" hint="Indian numbers can be entered without +91">
          <input name="phone" required type="tel" className={inputClass} />
        </Field>
        <Field label="Applied role *">
          <input name="applied_role" required maxLength={200} className={inputClass} />
        </Field>
        <Field label="Email">
          <input name="email" type="email" className={inputClass} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Total experience (years)">
            <input
              name="total_experience"
              type="number"
              min={0}
              max={60}
              step={0.5}
              className={inputClass}
            />
          </Field>
          <Field label="Current company">
            <input name="current_company" className={inputClass} />
          </Field>
          <Field label="Current location">
            <input name="current_location" className={inputClass} />
          </Field>
        </div>
        <Field label="Source">
          <input name="source" className={inputClass} />
        </Field>
        <Field label="Recruiter notes">
          <textarea name="recruiter_notes" rows={3} maxLength={2000} className={inputClass} />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input name="consent" type="checkbox" required className="mt-1" />
          This candidate has agreed to be contacted by phone about this role.
        </label>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Add candidate"}
          </Button>
          <Link href="/candidates" className={buttonClass("secondary")}>
            Cancel
          </Link>
        </div>
      </form>
    </>
  );
}
