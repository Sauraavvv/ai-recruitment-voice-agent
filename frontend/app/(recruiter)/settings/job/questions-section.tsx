"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { Button, Card, inputClass } from "@/components/ui";
import type { ScreeningQuestion } from "@/types";

export type QuestionMode = "default" | "custom";

export const TYPE_LABELS: Record<ScreeningQuestion["type"], string> = {
  string: "Text",
  number: "Number",
  boolean: "Yes / no",
};

/** A readable, unique key for a recruiter's own question ("q_" keeps it apart from standard keys). */
export function keyFor(prompt: string, used: Set<string>) {
  const slug =
    prompt
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 40)
      .replace(/_+$/g, "") || "question";
  const base = `q_${slug}`;
  let key = base;
  for (let n = 2; used.has(key); n++) key = `${base.slice(0, 45)}_${n}`;
  return key;
}

function ModeOption({
  checked,
  title,
  description,
  onSelect,
}: {
  checked: boolean;
  title: string;
  description: string;
  onSelect: () => void;
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition ${
        checked
          ? "border-[#2563eb] bg-[#2563eb]/10"
          : "border-[#34363d] bg-[#202226] hover:border-zinc-500"
      }`}
    >
      <input
        type="radio"
        name="question-mode"
        checked={checked}
        onChange={onSelect}
        className="mt-1 accent-[#2563eb]"
      />
      <span>
        <span className="block text-sm font-medium text-white">{title}</span>
        <span className="mt-0.5 block text-sm text-zinc-400">{description}</span>
      </span>
    </label>
  );
}

// The shared input style without its full width, for controls that sit in a row
const control = inputClass.replace("w-full ", "");

const iconButton =
  "flex h-8 w-8 items-center justify-center rounded-lg border border-[#34363d] bg-[#24262b] " +
  "text-zinc-300 transition hover:bg-[#2c2f35] disabled:cursor-not-allowed disabled:opacity-40";

export function QuestionsSection({
  mode,
  questions,
  defaults,
  onModeChange,
  onChange,
}: {
  mode: QuestionMode | null; // null: nothing chosen yet, only the two options show
  questions: ScreeningQuestion[];
  defaults: ScreeningQuestion[];
  onModeChange: (mode: QuestionMode) => void;
  onChange: (questions: ScreeningQuestion[]) => void;
}) {
  return (
    <Card
      title="Screening questions"
      description="What the AI agent asks every candidate for this job, in this order."
    >
      <div className={`grid gap-3 md:grid-cols-2 ${mode ? "mb-5" : ""}`}>
        <ModeOption
          checked={mode === "default"}
          title="Use default questions"
          description={`The ${defaults.length} questions set in Default Questions.`}
          onSelect={() => onModeChange("default")}
        />
        <ModeOption
          checked={mode === "custom"}
          title="Create new questions"
          description="Write your own questions, one by one, just for this job."
          onSelect={() => onModeChange("custom")}
        />
      </div>

      {mode === "default" && <DefaultPreview defaults={defaults} />}
      {mode === "custom" && <CustomBuilder questions={questions} onChange={onChange} />}
    </Card>
  );
}

function DefaultPreview({ defaults }: { defaults: ScreeningQuestion[] }) {
  return (
    <div>
      <ol className="divide-y divide-white/5 rounded-2xl bg-[#202226] px-4">
        {defaults.map((q, i) => (
          <li key={q.key} className="flex items-center gap-3 py-3 text-sm">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-zinc-300">
              {i + 1}
            </span>
            <span className="flex-1 text-zinc-200">{q.prompt}</span>
            <span className="text-xs text-zinc-500">
              {TYPE_LABELS[q.type]}
              {q.unit ? ` · ${q.unit}` : ""}
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-sm text-zinc-500">
        These come from{" "}
        <Link href="/default-questions" className="text-[#60a5fa] hover:underline">
          Default Questions
        </Link>
        .
      </p>
    </div>
  );
}

// Questions not yet saved carry a placeholder key; it's replaced by a readable one on save.
const DRAFT_PREFIX = "new_";

/** An empty question box, with a key unique among `questions`. */
export function blankQuestion(questions: ScreeningQuestion[]): ScreeningQuestion {
  let n = questions.length + 1;
  const used = new Set(questions.map((q) => q.key));
  while (used.has(`${DRAFT_PREFIX}${n}`)) n++;
  return { key: `${DRAFT_PREFIX}${n}`, prompt: "", required: true, type: "string", unit: null };
}

/** What to save from the builder: empty boxes dropped, placeholder keys made readable. */
export function finalizeCustom(questions: ScreeningQuestion[]): ScreeningQuestion[] {
  const kept = questions.map((q) => ({ ...q, prompt: q.prompt.trim() })).filter((q) => q.prompt);
  const used = new Set(kept.filter((q) => !q.key.startsWith(DRAFT_PREFIX)).map((q) => q.key));
  return kept.map((q) => {
    if (!q.key.startsWith(DRAFT_PREFIX)) return q;
    const key = keyFor(q.prompt, used);
    used.add(key);
    return { ...q, key };
  });
}

function CustomBuilder({
  questions,
  onChange,
}: {
  questions: ScreeningQuestion[];
  onChange: (questions: ScreeningQuestion[]) => void;
}) {
  const lastInput = useRef<HTMLInputElement>(null);
  // Set by "Add more"; the new box takes focus once it has rendered
  const focusNew = useRef(false);

  useEffect(() => {
    if (focusNew.current) {
      focusNew.current = false;
      lastInput.current?.focus();
    }
  }, [questions.length]);

  function update(index: number, changes: Partial<ScreeningQuestion>) {
    onChange(questions.map((q, i) => (i === index ? { ...q, ...changes } : q)));
  }

  function move(index: number, delta: number) {
    const next = [...questions];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item);
    onChange(next);
  }

  function addMore() {
    focusNew.current = true;
    onChange([...questions, blankQuestion(questions)]);
  }

  return (
    <div className="space-y-3">
      {questions.map((q, index) => (
        <div key={q.key} className="rounded-2xl border border-[#34363d] p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-white">Question {index + 1}</span>
            {questions.length > 1 && (
              <span className="flex gap-1">
                <button
                  type="button"
                  className={iconButton}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                  aria-label={`Move question ${index + 1} up`}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className={iconButton}
                  disabled={index === questions.length - 1}
                  onClick={() => move(index, 1)}
                  aria-label={`Move question ${index + 1} down`}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className={`${iconButton} text-red-300 hover:bg-red-500/20`}
                  onClick={() => onChange(questions.filter((_, i) => i !== index))}
                  aria-label={`Remove question ${index + 1}`}
                >
                  ✕
                </button>
              </span>
            )}
          </div>
          <input
            ref={index === questions.length - 1 ? lastInput : undefined}
            aria-label={`Question ${index + 1}`}
            value={q.prompt}
            maxLength={500}
            onChange={(e) => update(index, { prompt: e.target.value })}
            onKeyDown={(e) => {
              // Enter on the last box opens the next one
              if (e.key === "Enter") {
                e.preventDefault();
                if (index === questions.length - 1 && q.prompt.trim()) addMore();
              }
            }}
            placeholder="e.g. Are you comfortable working night shifts?"
            className={inputClass}
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              Answer
              <select
                value={q.type}
                onChange={(e) =>
                  update(index, { type: e.target.value as ScreeningQuestion["type"] })
                }
                className={control}
              >
                {Object.entries(TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={q.required}
                onChange={(e) => update(index, { required: e.target.checked })}
                className="accent-[#2563eb]"
              />
              Required
            </label>
          </div>
        </div>
      ))}
      <Button variant="secondary" onClick={addMore} disabled={questions.length >= 30}>
        + Add more
      </Button>
    </div>
  );
}
