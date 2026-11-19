"use client";

import { type FormEvent, useState } from "react";

import { Alert, Button, Card, Field, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { activateJob, createJob, defaultQuestions, listJobs, updateJob } from "@/services/jobs";
import type { Job, ScreeningQuestion } from "@/types";

import {
  blankQuestion,
  finalizeCustom,
  type QuestionMode,
  QuestionsSection,
} from "./questions-section";

const MAX_LONG_TEXT = 4000;
const NEW = "new";

type Draft = {
  job_title: string;
  company_name: string;
  job_description: string;
  location: string;
  required_experience: string;
  skills: string;
  agent_instructions: string;
  screening_questions: ScreeningQuestion[];
};

function toDraft(job: Job | undefined, defaults: ScreeningQuestion[]): Draft {
  return {
    job_title: job?.job_title ?? "",
    company_name: job?.company_name ?? "",
    job_description: job?.job_description ?? "",
    location: job?.location ?? "",
    required_experience: job?.required_experience ?? "",
    skills: job?.skills.join(", ") ?? "",
    agent_instructions: job?.agent_instructions ?? "",
    screening_questions: job?.screening_questions ?? defaults,
  };
}

const SUBTITLE =
  "The calling agent uses the active job's details and questions. Only one job is active at a time.";

export function JobSettings() {
  const jobs = useLoad("jobs", listJobs);
  const defaults = useLoad("default-questions", defaultQuestions);
  // null: the overview (existing jobs + create new); otherwise a job id or NEW
  const [selected, setSelected] = useState<string | null>(null);

  if (jobs.error) return <Alert>{errorMessage(jobs.error)}</Alert>;
  if (!jobs.data || !defaults.data) return <Muted>Loading…</Muted>;

  if (selected === null) {
    return (
      <>
        <PageHeader title="Job settings" subtitle={SUBTITLE} />
        <JobOverview jobs={jobs.data} onOpen={setSelected} />
      </>
    );
  }

  const job = jobs.data.find((j) => j.id === selected);

  return (
    <>
      <div className="mb-4">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className="inline-flex items-center gap-1.5 text-sm text-zinc-400 transition hover:text-white"
        >
          <span aria-hidden>←</span> Back to jobs
        </button>
      </div>
      <PageHeader
        title={
          job ? (
            <>
              {job.job_title}{" "}
              <span className="font-sans text-sm font-normal text-zinc-500">
                at {job.company_name}
              </span>
            </>
          ) : (
            "New job"
          )
        }
        subtitle={job ? undefined : "Fill in the details the agent will use on calls."}
      >
        {job && (
          <>
            <Button variant="secondary" onClick={() => setSelected(NEW)}>
              + Create new job
            </Button>
            {/* Shown but switched off until deleting jobs is supported */}
            <Button variant="danger" disabled title="Deleting jobs isn't available yet">
              Delete this job
            </Button>
          </>
        )}
      </PageHeader>
      <JobForm
        key={`${selected}:${job?.updated_at ?? ""}`}
        job={job}
        defaults={defaults.data}
        onSaved={(saved) => {
          setSelected(saved.id);
          jobs.reload();
        }}
      />
    </>
  );
}

const companyInitials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

function JobOverview({ jobs, onOpen }: { jobs: Job[]; onOpen: (id: string) => void }) {
  // Active job first, then by company
  const sorted = [...jobs].sort(
    (a, b) =>
      Number(b.is_active) - Number(a.is_active) ||
      a.company_name.localeCompare(b.company_name) ||
      a.job_title.localeCompare(b.job_title),
  );
  const companies = new Set(jobs.map((j) => j.company_name)).size;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card
        title="Existing jobs"
        description={
          jobs.length
            ? `${jobs.length} job${jobs.length === 1 ? "" : "s"} across ${companies} compan${companies === 1 ? "y" : "ies"}. Choose one to view or edit it.`
            : "No jobs yet."
        }
        className="lg:col-span-2"
      >
        {jobs.length ? (
          <ul className="space-y-2">
            {sorted.map((j) => (
              <li key={j.id}>
                <button
                  type="button"
                  onClick={() => onOpen(j.id)}
                  className="group flex w-full items-center gap-3 rounded-2xl border border-[#34363d] bg-[#202226] p-4 text-left transition hover:border-zinc-500 hover:bg-[#24262b]"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-sm font-medium text-white">
                    {companyInitials(j.company_name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-white">
                      {j.company_name}
                    </span>
                    <span className="block truncate text-sm text-zinc-400">
                      {j.job_title}
                      {j.location ? ` · ${j.location}` : ""}
                    </span>
                  </span>
                  <span className="hidden text-xs text-zinc-500 sm:inline">
                    {j.screening_questions.length} questions
                  </span>
                  {j.is_active ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#0ca30c]/15 px-2.5 py-1 text-xs font-medium text-[#5fd35f]">
                      <span className="h-1.5 w-1.5 rounded-full bg-[#0ca30c]" />
                      Active
                    </span>
                  ) : (
                    <span className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-zinc-400">
                      Inactive
                    </span>
                  )}
                  <span
                    aria-hidden
                    className="text-zinc-500 transition group-hover:translate-x-0.5 group-hover:text-white"
                  >
                    →
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <Muted>Create your first job to start screening candidates.</Muted>
        )}
      </Card>

      <button
        type="button"
        onClick={() => onOpen(NEW)}
        className="group flex min-h-48 flex-col items-center justify-center rounded-3xl border border-dashed border-[#34363d] bg-[#18191c] p-6 text-center transition hover:border-[#2563eb] hover:bg-[#2563eb]/5"
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#1d4ed8] text-2xl text-white transition group-hover:bg-[#2563eb]">
          +
        </span>
        <span className="font-display mt-4 text-base font-semibold text-white">Create new job</span>
        <span className="mt-1 text-sm text-zinc-500">
          Add a role with its details and screening questions.
        </span>
      </button>
    </div>
  );
}

function JobForm({
  job,
  defaults,
  onSaved,
}: {
  job: Job | undefined;
  defaults: ScreeningQuestion[];
  onSaved: (job: Job) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(job, defaults));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft({ ...draft, [key]: value });
  // Nothing is chosen until the recruiter picks an option; until then the questions aren't shown
  // and an existing job keeps the questions it has.
  const [mode, setMode] = useState<QuestionMode | null>(null);
  // "Create new questions" starts from this job's own questions (none if it uses the defaults),
  // and what's written there survives a look at the defaults and back.
  // Default questions never appear here: only questions written for this job.
  const [customDraft, setCustomDraft] = useState<ScreeningQuestion[]>(() => {
    const standard = new Set(defaults.map((q) => q.key));
    return (job?.screening_questions ?? []).filter((q) => !standard.has(q.key));
  });

  function changeMode(next: QuestionMode) {
    if (next === mode) return;
    if (mode === "custom") setCustomDraft(draft.screening_questions);
    set(
      "screening_questions",
      next === "default" ? defaults : customDraft.length ? customDraft : [blankQuestion([])],
    );
    setMode(next);
  }

  async function run(action: () => Promise<Job>, success: string) {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await action();
      setMessage({ kind: "success", text: success });
      onSaved(saved);
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (mode === null && !job) {
      setMessage({
        kind: "error",
        text: "Choose the screening questions: default questions or new ones.",
      });
      return;
    }
    const questions =
      mode === "default"
        ? defaults
        : mode === "custom"
          ? finalizeCustom(draft.screening_questions)
          : draft.screening_questions;
    if (questions.length === 0) {
      setMessage({ kind: "error", text: "Add at least one screening question before saving." });
      return;
    }
    const body = {
      ...draft,
      screening_questions: questions,
      skills: draft.skills
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    void run(
      () => (job ? updateJob(job.id, body) : createJob(body)),
      job ? "Saved" : "Job created",
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {job && !job.is_active && (
        <Alert kind="info">
          This job is not active.{" "}
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => void run(() => activateJob(job.id), "This job is now active")}
          >
            Make active
          </Button>
        </Alert>
      )}

      <Card title="Job details" description="Shown to candidates by the agent on the call.">
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Field label="Job title *">
              <input
                required
                maxLength={200}
                value={draft.job_title}
                onChange={(e) => set("job_title", e.target.value)}
                className={inputClass}
              />
            </Field>
            <Field label="Company name *">
              <input
                required
                maxLength={200}
                value={draft.company_name}
                onChange={(e) => set("company_name", e.target.value)}
                className={inputClass}
              />
            </Field>
            <Field label="Location">
              <input
                maxLength={200}
                value={draft.location}
                onChange={(e) => set("location", e.target.value)}
                className={inputClass}
              />
            </Field>
            <Field label="Required experience">
              <input
                maxLength={100}
                placeholder="e.g. 3–5 years"
                value={draft.required_experience}
                onChange={(e) => set("required_experience", e.target.value)}
                className={inputClass}
              />
            </Field>
          </div>
          <Field label="Skills" hint="Comma-separated">
            <input
              value={draft.skills}
              onChange={(e) => set("skills", e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
      </Card>

      <Card
        title="What the agent knows"
        description="The agent answers candidates' questions only from this."
      >
        <div className="space-y-4">
          <Field
            label="Job description"
            hint={`${draft.job_description.length}/${MAX_LONG_TEXT}. The agent only answers questions from what's written here.`}
          >
            <textarea
              rows={6}
              maxLength={MAX_LONG_TEXT}
              value={draft.job_description}
              onChange={(e) => set("job_description", e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field
            label="Agent instructions"
            hint={`${draft.agent_instructions.length}/${MAX_LONG_TEXT}. Extra guidance for the calling agent.`}
          >
            <textarea
              rows={4}
              maxLength={MAX_LONG_TEXT}
              value={draft.agent_instructions}
              onChange={(e) => set("agent_instructions", e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
      </Card>

      <QuestionsSection
        mode={mode}
        questions={draft.screening_questions}
        defaults={defaults}
        onModeChange={changeMode}
        onChange={(questions) => set("screening_questions", questions)}
      />

      <div className="flex justify-end">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : job ? "Save job" : "Create job"}
        </Button>
      </div>
    </form>
  );
}
