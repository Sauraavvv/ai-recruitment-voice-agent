"use client";

import { useState } from "react";

import { Alert, Button, Card, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { defaultQuestions, resetDefaultQuestions, updateDefaultQuestions } from "@/services/jobs";
import type { DefaultQuestionsResult, ScreeningQuestion } from "@/types";

import { TYPE_LABELS, keyFor } from "../settings/job/questions-section";

// The standard questions fill fixed candidate fields, so their answer type can't change
const STANDARD_KEYS = new Set([
  "interested",
  "current_location",
  "current_company",
  "total_experience",
  "relevant_experience",
  "notice_period",
  "current_ctc",
  "expected_ctc",
  "reason_for_change",
  "interview_availability",
]);

const MAX_QUESTIONS = 30;
const ADDING = "__new__";

type Message = { kind: "error" | "success"; text: string };
type QuestionType = ScreeningQuestion["type"];

// The shared input style without its full width, for controls that sit in a row
const control = inputClass.replace("w-full ", "");

function savedText(result: DefaultQuestionsResult, what: string) {
  const n = result.jobs_updated;
  if (!n) return `${what}. The next screening calls will ask it.`;
  return `${what}. Also updated in ${n} job${n === 1 ? " that uses" : "s that use"} the default questions.`;
}

export function DefaultQuestions() {
  const { data, error, setData } = useLoad("default-questions", defaultQuestions);
  // The key of the question being edited, ADDING for the new-question box, or null
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  async function run(action: () => Promise<DefaultQuestionsResult>, what: string) {
    setBusy(true);
    setMessage(null);
    try {
      const result = await action();
      setData(result.questions);
      setEditing(null);
      setMessage({ kind: "success", text: savedText(result, what) });
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  const save = (questions: ScreeningQuestion[], what: string) =>
    void run(() => updateDefaultQuestions(questions), what);

  function startEditing(key: string) {
    setMessage(null);
    setEditing(key);
  }

  function onDelete(index: number, questions: ScreeningQuestion[]) {
    if (questions.length === 1) {
      setMessage({ kind: "error", text: "Keep at least one default question." });
      return;
    }
    if (!window.confirm(`Delete "${questions[index].prompt}"?`)) return;
    save(
      questions.filter((_, i) => i !== index),
      "Question deleted",
    );
  }

  function onReset() {
    if (!window.confirm("Restore the original ten default questions? Your changes are lost."))
      return;
    void run(resetDefaultQuestions, "Original questions restored");
  }

  return (
    <>
      <PageHeader
        title="Default questions"
        subtitle="Your company's standard screening questions. Changes apply to every requirement's next screening calls; other companies keep their own."
      >
        <Button variant="secondary" onClick={onReset} disabled={busy || !data}>
          Restore original questions
        </Button>
      </PageHeader>
      {message && (
        <div className="mb-4">
          <Alert kind={message.kind}>{message.text}</Alert>
        </div>
      )}
      {error && <Alert>{errorMessage(error)}</Alert>}
      {!data && !error && <Muted>Loading…</Muted>}
      {data && (
        <Card
          title={`${data.length} question${data.length === 1 ? "" : "s"}`}
          description="Asked in this order on every screening call. Each requirement then adds its must-haves, as yes / no questions."
        >
          <ol className="divide-y divide-white/5 rounded-2xl bg-[#202226] px-4">
            {data.map((q, i) =>
              editing === q.key ? (
                <QuestionForm
                  key={q.key}
                  index={i}
                  question={q}
                  busy={busy}
                  onCancel={() => setEditing(null)}
                  onSave={(changes) =>
                    save(
                      data.map((other) => (other.key === q.key ? { ...q, ...changes } : other)),
                      `Question ${i + 1} saved`,
                    )
                  }
                />
              ) : (
                <li key={q.key} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-4">
                  <Position n={i + 1} />
                  <span className="min-w-60 flex-1 text-sm text-white">{q.prompt}</span>
                  {!q.required && (
                    <span className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-zinc-400">
                      Optional
                    </span>
                  )}
                  <span className="flex gap-2">
                    <Button
                      variant="secondary"
                      className="h-8 px-3"
                      disabled={busy || editing !== null}
                      onClick={() => startEditing(q.key)}
                      aria-label={`Edit question ${i + 1}`}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="danger"
                      className="h-8 px-3"
                      disabled={busy || editing !== null}
                      onClick={() => onDelete(i, data)}
                      aria-label={`Delete question ${i + 1}`}
                    >
                      Delete
                    </Button>
                  </span>
                </li>
              ),
            )}
            {editing === ADDING && (
              <QuestionForm
                index={data.length}
                busy={busy}
                onCancel={() => setEditing(null)}
                onSave={(changes) => {
                  const used = new Set(data.map((q) => q.key));
                  const added: ScreeningQuestion = {
                    key: keyFor(changes.prompt, used),
                    unit: null,
                    ...changes,
                  };
                  save([...data, added], "Question added");
                }}
              />
            )}
          </ol>
          {editing !== ADDING && (
            <div className="mt-4">
              <Button
                variant="secondary"
                onClick={() => startEditing(ADDING)}
                disabled={busy || editing !== null || data.length >= MAX_QUESTIONS}
              >
                + Add new question
              </Button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}

function Position({ n }: { n: number }) {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-zinc-300">
      {n}
    </span>
  );
}

/** Editing an existing question, or writing a new one when `question` is absent. */
function QuestionForm({
  index,
  question,
  busy,
  onCancel,
  onSave,
}: {
  index: number;
  question?: ScreeningQuestion;
  busy: boolean;
  onCancel: () => void;
  onSave: (changes: { prompt: string; required: boolean; type: QuestionType }) => void;
}) {
  const [prompt, setPrompt] = useState(question?.prompt ?? "");
  const [required, setRequired] = useState(question?.required ?? true);
  const [type, setType] = useState<QuestionType>(question?.type ?? "string");
  const trimmed = prompt.trim();
  const changed =
    !question ||
    trimmed !== question.prompt ||
    required !== question.required ||
    type !== question.type;
  // A standard question's answer fills a fixed candidate field, so its type stays
  const typeLocked = question !== undefined && STANDARD_KEYS.has(question.key);

  return (
    <li className="py-4">
      <form
        className="flex flex-wrap items-center gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (trimmed && changed) onSave({ prompt: trimmed, required, type });
        }}
      >
        <Position n={index + 1} />
        <input
          autoFocus
          value={prompt}
          maxLength={500}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onCancel()}
          aria-label={`Question ${index + 1}`}
          placeholder="e.g. Are you comfortable working night shifts?"
          className={`${inputClass} min-w-60 flex-1 basis-80`}
        />
        {!typeLocked && (
          <label className="flex items-center gap-2 text-sm text-zinc-300">
            Answer
            <select
              value={type}
              onChange={(e) => setType(e.target.value as QuestionType)}
              className={control}
            >
              {Object.entries(TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex items-center gap-1.5 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={required}
            onChange={(e) => setRequired(e.target.checked)}
            className="accent-[#2563eb]"
          />
          Required
        </label>
        <Button type="submit" className="h-8 px-3" disabled={busy || !trimmed || !changed}>
          {busy ? "Saving…" : question ? "Save" : "Add"}
        </Button>
        <Button variant="secondary" className="h-8 px-3" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </form>
    </li>
  );
}
