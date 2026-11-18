"use client";

import { type FormEvent, useState } from "react";

import { Alert, Button, Field, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { activateJob, createJob, defaultQuestions, listJobs, updateJob } from "@/services/jobs";
import type { Job, ScreeningQuestion } from "@/types";

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

export function JobSettings() {
  const jobs = useLoad("jobs", listJobs);
  const defaults = useLoad("default-questions", defaultQuestions);
  const [selected, setSelected] = useState<string | null>(null);

  if (jobs.error) return <Alert>{errorMessage(jobs.error)}</Alert>;
  if (!jobs.data || !defaults.data) return <Muted>Loading…</Muted>;

  const active = jobs.data.find((j) => j.is_active);
  const selectedId = selected ?? active?.id ?? jobs.data[0]?.id ?? NEW;
  const job = jobs.data.find((j) => j.id === selectedId);

  return (
    <>
      <PageHeader title="Job settings">
        {jobs.data.length > 0 && (
          <select
            value={selectedId}
            onChange={(e) => setSelected(e.target.value)}
            className={inputClass}
            aria-label="Job to edit"
          >
            {jobs.data.map((j) => (
              <option key={j.id} value={j.id}>
                {j.job_title} — {j.company_name}
                {j.is_active ? " (active)" : ""}
              </option>
            ))}
            <option value={NEW}>+ New job</option>
          </select>
        )}
      </PageHeader>
      <Muted>
        The calling agent uses the active job&apos;s details and screening questions. Only one job
        is active at a time.
      </Muted>
      <JobForm
        key={`${selectedId}:${job?.updated_at ?? ""}`}
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
  const standardKeys = new Set(defaults.map((q) => q.key));

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
    const body = {
      ...draft,
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

  function updateQuestion(index: number, changes: Partial<ScreeningQuestion>) {
    const questions = draft.screening_questions.map((q, i) =>
      i === index ? { ...q, ...changes } : q,
    );
    set("screening_questions", questions);
  }

  function move(index: number, delta: number) {
    const questions = [...draft.screening_questions];
    const [item] = questions.splice(index, 1);
    questions.splice(index + delta, 0, item);
    set("screening_questions", questions);
  }

  function addQuestion() {
    const used = new Set(draft.screening_questions.map((q) => q.key));
    let n = 1;
    while (used.has(`custom_${n}`)) n++;
    set("screening_questions", [
      ...draft.screening_questions,
      { key: `custom_${n}`, prompt: "", required: false, type: "string", unit: null },
    ]);
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 max-w-3xl space-y-4">
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

      <div className="grid gap-4 sm:grid-cols-2">
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
        <Field label="Required experience" hint="e.g. 3–5 years">
          <input
            maxLength={100}
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

      <fieldset className="space-y-3">
        <legend className="mb-2 font-medium">Screening questions (asked in this order)</legend>
        {draft.screening_questions.map((q, index) => {
          const standard = standardKeys.has(q.key);
          return (
            <div key={index} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-zinc-500">{index + 1}.</span>
                {standard ? (
                  <code>{q.key}</code>
                ) : (
                  <input
                    aria-label="Question key"
                    value={q.key}
                    pattern="[a-z][a-z0-9_]{0,49}"
                    title="Lowercase letters, digits and underscores"
                    onChange={(e) => updateQuestion(index, { key: e.target.value })}
                    className={`${inputClass} max-w-40 font-mono text-xs`}
                  />
                )}
                <select
                  aria-label="Answer type"
                  value={q.type}
                  disabled={standard}
                  onChange={(e) =>
                    updateQuestion(index, { type: e.target.value as ScreeningQuestion["type"] })
                  }
                  className={`${inputClass} max-w-28 text-xs`}
                >
                  <option value="string">Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Yes / no</option>
                </select>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={q.required}
                    onChange={(e) => updateQuestion(index, { required: e.target.checked })}
                  />
                  Required
                </label>
                <span className="ml-auto flex gap-1">
                  <Button
                    variant="secondary"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    aria-label="Move up"
                  >
                    ↑
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={index === draft.screening_questions.length - 1}
                    onClick={() => move(index, 1)}
                    aria-label="Move down"
                  >
                    ↓
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() =>
                      set(
                        "screening_questions",
                        draft.screening_questions.filter((_, i) => i !== index),
                      )
                    }
                    aria-label="Remove question"
                  >
                    ✕
                  </Button>
                </span>
              </div>
              <input
                aria-label="Question"
                required
                maxLength={500}
                value={q.prompt}
                onChange={(e) => updateQuestion(index, { prompt: e.target.value })}
                className={inputClass}
                placeholder="Question the agent asks"
              />
            </div>
          );
        })}
        <Button variant="secondary" onClick={addQuestion}>
          Add custom question
        </Button>
      </fieldset>

      <Button type="submit" disabled={busy}>
        {busy ? "Saving…" : job ? "Save job" : "Create job"}
      </Button>
    </form>
  );
}
