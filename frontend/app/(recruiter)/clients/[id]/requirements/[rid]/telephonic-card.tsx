"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/states";
import { useToast } from "@/components/toast";
import { Alert, Button } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import {
  type QuestionLevel,
  approveQuestions,
  discardDraft,
  generateQuestions,
  getTelephonic,
  saveDraft,
} from "@/services/telephonic";
import type { Question, QuestionIn, QuestionSet } from "@/types";

type QType = Question["type"];
const TYPES: { value: QType; label: string }[] = [
  { value: "skill", label: "Skill" },
  { value: "experience", label: "Experience" },
  { value: "situational", label: "Situational" },
  { value: "logistics", label: "Logistics" },
];
const WEIGHTS: Record<number, string> = { 1: "Nice to have", 2: "Important", 3: "Critical" };
export const MIN_COUNT = 3;
export const MAX_COUNT = 12;
export const LEVELS: { value: QuestionLevel; label: string; hint: string }[] = [
  {
    value: "easy",
    label: "Easy",
    hint: "Like an HR screening call: what they've worked on, tools used, a recent project.",
  },
  {
    value: "medium",
    label: "Medium",
    hint: "Practical: how they did something the job needs, with a real example.",
  },
  {
    value: "hard",
    label: "Hard",
    hint: "Specialist: trade-offs, troubleshooting and design choices.",
  },
];
const MAX_QUESTIONS = 15;

// A question while editing; `key` keeps React rows stable before the server assigns an id
type Draft = QuestionIn & { key: string };

function toDraft(questions: Question[]): Draft[] {
  return questions.map((q) => ({ ...q, key: q.id }));
}

function blank(): Draft {
  return { key: crypto.randomUUID(), text: "", type: "skill", rubric: "", weight: 2 };
}

function shortDate(iso: string | null | undefined) {
  return iso
    ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : "";
}

/** Telephonic round questions: made from the JD by AI (or written by hand), edited, approved. */
export function TelephonicCard({
  requirementId,
  editHref,
  onApproved,
}: {
  requirementId: string;
  editHref: string;
  onApproved?: () => void; // the calls list below shows the new version
}) {
  const notify = useToast();
  const { data, error, reload } = useLoad(`telephonic:${requirementId}`, () =>
    getTelephonic(requirementId),
  );
  // The questions being edited (null = not editing)
  const [editing, setEditing] = useState<Draft[] | null>(null);
  const [busy, setBusy] = useState<"generate" | "save" | "approve" | "discard" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [count, setCount] = useState(8);
  const [focus, setFocus] = useState("");
  const [level, setLevel] = useState<QuestionLevel>("easy");
  const [confirm, setConfirm] = useState<"regenerate" | "discard" | null>(null);

  const draft = data?.draft ?? null;
  const approved = data?.approved ?? null;
  // A server draft is always shown in the editor
  const rows = editing ?? (draft ? toDraft(draft.questions) : null);
  const dirty = editing !== null;

  async function run(kind: NonNullable<typeof busy>, action: () => Promise<void>) {
    setBusy(kind);
    setProblem(null);
    try {
      await action();
    } catch (err) {
      setProblem(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const generate = () =>
    run("generate", async () => {
      await generateQuestions(requirementId, count, focus, level);
      setEditing(null);
      reload();
      notify("success", "Questions ready. Check them, then approve.");
    });

  const persist = async (list: Draft[]): Promise<QuestionSet> => {
    const body: QuestionIn[] = list.map((q) => ({
      id: q.id ?? null,
      text: q.text,
      type: q.type,
      rubric: q.rubric,
      weight: q.weight,
    }));
    return saveDraft(requirementId, body);
  };

  const save = () =>
    run("save", async () => {
      if (!rows) return;
      await persist(rows);
      setEditing(null);
      reload();
      notify("success", "Draft saved");
    });

  const approve = () =>
    run("approve", async () => {
      if (rows && (dirty || !draft)) await persist(rows);
      const set = await approveQuestions(requirementId);
      setEditing(null);
      reload();
      notify("success", `Questions approved (version ${set.version})`);
      onApproved?.();
    });

  const discard = () =>
    run("discard", async () => {
      if (draft) await discardDraft(requirementId);
      setEditing(null);
      reload();
    });

  const change = (list: Draft[]) => setEditing(list);
  const incomplete = rows?.some((q) => q.text.trim().length < 5) ?? false;

  return (
    <section className="rounded-3xl bg-[#18191c] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/5 text-zinc-300">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
              <path d="M15 3a6 6 0 0 1 6 6" />
              <path d="M15 7a2 2 0 0 1 2 2" />
            </svg>
          </span>
          <div>
            <h2 className="font-display text-lg font-semibold text-white">Telephonic round</h2>
            <p className="text-sm text-zinc-500">
              Questions made from the JD, asked on a second call and scored.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {approved && (
            <span className="rounded-full bg-green-500/10 px-2.5 py-1 font-medium text-green-300">
              Approved · v{approved.version} · {shortDate(approved.approved_at)}
              {approved.level && ` · ${levelLabel(approved.level)} level`}
            </span>
          )}
          {(draft || editing) && (
            <span className="rounded-full bg-amber-400/10 px-2.5 py-1 font-medium text-amber-300">
              {draft ? `Draft · v${draft.version}` : "New draft"}
              {draft?.level && ` · ${levelLabel(draft.level)} level`}
              {dirty && " · unsaved"}
            </span>
          )}
        </div>
      </div>

      <div className="mt-6">
        {error && !data ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data ? (
          <div
            className="h-40 animate-pulse rounded-2xl bg-white/[0.03]"
            role="status"
            aria-label="Loading"
          />
        ) : !data.has_jd ? (
          <Empty title="Add the job description first">
            The questions are made from the JD.{" "}
            <Link href={editHref} className="text-zinc-200 underline-offset-2 hover:underline">
              Edit job details
            </Link>
          </Empty>
        ) : busy === "generate" ? (
          <Generating />
        ) : (
          <div className="space-y-4">
            {problem && <Alert>{problem}</Alert>}
            {data.jd_changed && !draft && !editing && (
              <Alert kind="info">
                The JD changed after these questions were approved. Regenerate to match it.
              </Alert>
            )}

            {rows ? (
              <>
                <Editor rows={rows} onChange={change} />
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-4">
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      disabled={busy !== null}
                      onClick={() => setConfirm("discard")}
                    >
                      {draft ? "Discard draft" : "Cancel"}
                    </Button>
                    {data.ai_ready && (
                      <Button
                        variant="secondary"
                        disabled={busy !== null}
                        onClick={() => setConfirm("regenerate")}
                      >
                        ✦ Regenerate
                      </Button>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {incomplete && (
                      <span className="text-xs text-zinc-500">Every question needs some text</span>
                    )}
                    <Button
                      variant="secondary"
                      disabled={busy !== null || incomplete || !dirty}
                      onClick={() => void save()}
                    >
                      {busy === "save" ? "Saving…" : "Save draft"}
                    </Button>
                    <Button disabled={busy !== null || incomplete} onClick={() => void approve()}>
                      {busy === "approve" ? "Approving…" : "Approve questions"}
                    </Button>
                  </div>
                </div>
              </>
            ) : approved ? (
              <>
                <ReadOnly questions={approved.questions} />
                <div className="flex flex-wrap justify-end gap-2 border-t border-white/5 pt-4">
                  {data.ai_ready && (
                    <Button variant="secondary" onClick={() => setConfirm("regenerate")}>
                      ✦ Regenerate
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() => setEditing(toDraft(approved.questions))}
                  >
                    Edit questions
                  </Button>
                </div>
              </>
            ) : (
              <Start
                aiReady={data.ai_ready}
                options={
                  <GenerateOptions
                    count={count}
                    level={level}
                    focus={focus}
                    onCount={setCount}
                    onLevel={setLevel}
                    onFocus={setFocus}
                    centered
                  />
                }
                onGenerate={() => void generate()}
                onManual={() => setEditing([blank()])}
              />
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirm === "regenerate"}
        title="Write new questions?"
        confirmLabel="Regenerate"
        onConfirm={() => {
          setConfirm(null);
          void generate();
        }}
        onClose={() => setConfirm(null)}
      >
        <p>The AI writes {count} new questions from the JD. They replace the current draft.</p>
        <div className="mt-4">
          <GenerateOptions
            count={count}
            level={level}
            focus={focus}
            onCount={setCount}
            onLevel={setLevel}
            onFocus={setFocus}
          />
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm === "discard"}
        title={draft ? "Discard this draft?" : "Discard these questions?"}
        confirmLabel="Discard"
        danger
        onConfirm={() => {
          setConfirm(null);
          void discard();
        }}
        onClose={() => setConfirm(null)}
      >
        {approved
          ? `The approved questions (version ${approved.version}) stay as they are.`
          : "Nothing is approved yet, so there will be no questions."}
      </ConfirmDialog>
    </section>
  );
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center">
      <p className="font-display text-lg font-semibold text-white">{title}</p>
      <p className="mt-1 text-sm text-zinc-500">{children}</p>
    </div>
  );
}

function Generating() {
  return (
    <div
      className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-white/10 px-6 py-12 text-center"
      role="status"
    >
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-zinc-200" />
      <div>
        <p className="font-medium text-white">Writing questions from the JD…</p>
        <p className="mt-1 text-sm text-zinc-500">This can take up to a minute.</p>
      </div>
    </div>
  );
}

export function levelLabel(level: string): string {
  return LEVELS.find((l) => l.value === level)?.label ?? level;
}

/** What the AI writes: how many questions (a slider), how hard, and what to focus on. */
export function GenerateOptions({
  count,
  level,
  focus,
  onCount,
  onLevel,
  onFocus,
  centered = false,
}: {
  count: number;
  level: QuestionLevel;
  focus: string;
  onCount: (n: number) => void;
  onLevel: (l: QuestionLevel) => void;
  onFocus: (v: string) => void;
  centered?: boolean;
}) {
  const hint = LEVELS.find((l) => l.value === level)?.hint;
  return (
    <div className={`w-full max-w-md space-y-4 text-left ${centered ? "mx-auto" : ""}`}>
      <label className="block text-xs">
        <span className="flex items-baseline justify-between">
          <span className="text-zinc-500">Questions</span>
          <span className="font-display text-sm font-semibold text-white tabular-nums">
            {count}
          </span>
        </span>
        <input
          type="range"
          min={MIN_COUNT}
          max={MAX_COUNT}
          step={1}
          value={count}
          onChange={(e) => onCount(Number(e.target.value))}
          aria-label="How many questions"
          className="mt-2 w-full cursor-pointer accent-[#2563eb]"
        />
        <span className="flex justify-between text-[11px] text-zinc-600 tabular-nums">
          <span>{MIN_COUNT}</span>
          <span>{MAX_COUNT}</span>
        </span>
      </label>

      <div className="text-xs">
        <span className="text-zinc-500">Level</span>
        <div role="radiogroup" aria-label="How hard" className="mt-2 grid grid-cols-3 gap-1.5">
          {LEVELS.map((l) => (
            <button
              key={l.value}
              type="button"
              role="radio"
              aria-checked={level === l.value}
              onClick={() => onLevel(l.value)}
              className={`rounded-lg border px-3 py-1.5 transition ${
                level === l.value
                  ? "border-[#2563eb] bg-[#2563eb]/15 text-white"
                  : "border-white/10 text-zinc-400 hover:border-white/25 hover:text-zinc-200"
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
        {hint && <p className="mt-1.5 text-zinc-500">{hint}</p>}
      </div>

      <input
        value={focus}
        onChange={(e) => onFocus(e.target.value)}
        maxLength={300}
        placeholder="Anything to focus on? e.g. B2B sales, Excel (optional)"
        aria-label="What to focus on"
        className="w-full border-0 border-b border-white/10 bg-transparent px-0 py-2 text-sm text-white outline-none placeholder:text-zinc-600 focus:border-[#2563eb]"
      />
    </div>
  );
}

function Start({
  aiReady,
  options,
  onGenerate,
  onManual,
}: {
  aiReady: boolean;
  options: ReactNode;
  onGenerate: () => void;
  onManual: () => void;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 px-6 py-10">
      <div className="mx-auto max-w-xl text-center">
        <p className="font-display text-lg font-semibold text-white">No questions yet</p>
        <p className="mt-1 text-sm text-zinc-500">
          The AI reads the JD and writes questions with what a good answer covers. You check them,
          change anything, then approve.
        </p>
        <div className="mt-6 flex flex-col items-center gap-4">
          {options}
          <div className="flex flex-wrap justify-center gap-2">
            <Button
              disabled={!aiReady}
              title={aiReady ? undefined : "The question-writing AI isn't set up yet"}
              onClick={onGenerate}
            >
              ✦ Generate with AI
            </Button>
            <Button variant="secondary" onClick={onManual}>
              Write my own
            </Button>
          </div>
          {!aiReady && (
            <p className="text-xs text-zinc-500">
              The AI isn&apos;t set up yet. You can still write the questions yourself.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function TypeChip({ type }: { type: QType }) {
  return (
    <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-zinc-300">
      {TYPES.find((t) => t.value === type)?.label ?? type}
    </span>
  );
}

function WeightDots({ weight }: { weight: number }) {
  return (
    <span className="flex items-center gap-1" title={WEIGHTS[weight]} aria-label={WEIGHTS[weight]}>
      {[1, 2, 3].map((n) => (
        <span
          key={n}
          className={`h-1.5 w-1.5 rounded-full ${n <= weight ? "bg-zinc-200" : "bg-white/10"}`}
        />
      ))}
    </span>
  );
}

function ReadOnly({ questions }: { questions: Question[] }) {
  return (
    <ol className="space-y-2">
      {questions.map((q, i) => (
        <li key={q.id} className="rounded-2xl bg-white/[0.03] p-4">
          <div className="flex gap-3">
            <span className="font-display w-5 shrink-0 text-sm text-zinc-500">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[15px] text-white">{q.text}</p>
              {q.rubric && <p className="mt-1.5 text-sm text-zinc-500">✓ {q.rubric}</p>}
              <div className="mt-2.5 flex items-center gap-3">
                <TypeChip type={q.type} />
                <WeightDots weight={q.weight} />
                <span className="text-[11px] text-zinc-500">{WEIGHTS[q.weight]}</span>
              </div>
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

// Grows with its text (field-sizing), so a one-line question takes one line
const area =
  "block w-full resize-none border-0 border-b border-transparent bg-transparent px-0 py-0.5 " +
  "outline-none transition [field-sizing:content] placeholder:text-zinc-600 focus:border-[#2563eb]";

function Editor({ rows, onChange }: { rows: Draft[]; onChange: (rows: Draft[]) => void }) {
  const update = (i: number, patch: Partial<Draft>) =>
    onChange(rows.map((q, n) => (n === i ? { ...q, ...patch } : q)));
  const move = (i: number, by: number) => {
    const next = [...rows];
    const [item] = next.splice(i, 1);
    next.splice(i + by, 0, item);
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <ol className="space-y-2">
        {rows.map((q, i) => (
          <li
            key={q.key}
            className="group rounded-2xl bg-white/[0.03] px-4 py-3 ring-1 ring-transparent focus-within:ring-white/10"
          >
            <div className="flex gap-3">
              <span className="font-display w-5 shrink-0 pt-0.5 text-sm text-zinc-500">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <textarea
                  rows={1}
                  maxLength={400}
                  value={q.text}
                  onChange={(e) => update(i, { text: e.target.value })}
                  placeholder="The question the agent asks"
                  aria-label={`Question ${i + 1}`}
                  className={`${area} text-[15px] text-white`}
                />
                <textarea
                  rows={1}
                  maxLength={800}
                  value={q.rubric ?? ""}
                  onChange={(e) => update(i, { rubric: e.target.value })}
                  placeholder="What a good answer covers"
                  aria-label={`What a good answer to question ${i + 1} covers`}
                  className={`${area} text-sm text-zinc-400`}
                />
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1.5">
                  <div role="radiogroup" aria-label="Type" className="flex flex-wrap gap-1">
                    {TYPES.map((t) => (
                      <button
                        key={t.value}
                        type="button"
                        role="radio"
                        aria-checked={q.type === t.value}
                        onClick={() => update(i, { type: t.value })}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] transition ${
                          q.type === t.value
                            ? "bg-white/10 text-white"
                            : "text-zinc-500 hover:text-zinc-200"
                        }`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                  <div role="radiogroup" aria-label="Weight" className="flex items-center gap-1">
                    {[1, 2, 3].map((w) => (
                      <button
                        key={w}
                        type="button"
                        role="radio"
                        aria-checked={q.weight === w}
                        title={WEIGHTS[w]}
                        onClick={() => update(i, { weight: w })}
                        className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                          q.weight === w
                            ? "bg-white/10 text-white"
                            : "text-zinc-500 hover:text-zinc-200"
                        }`}
                      >
                        {WEIGHTS[w]}
                      </button>
                    ))}
                  </div>
                  <div className="ml-auto flex items-center gap-0.5 opacity-50 transition group-focus-within:opacity-100 group-hover:opacity-100">
                    <IconButton label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </IconButton>
                    <IconButton
                      label="Move down"
                      disabled={i === rows.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      ↓
                    </IconButton>
                    <IconButton
                      label="Remove question"
                      disabled={rows.length === 1}
                      onClick={() => onChange(rows.filter((_, n) => n !== i))}
                      danger
                    >
                      ✕
                    </IconButton>
                  </div>
                </div>
              </div>
            </div>
          </li>
        ))}
      </ol>
      {rows.length < MAX_QUESTIONS && (
        <button
          type="button"
          onClick={() => onChange([...rows, blank()])}
          className="w-full rounded-2xl border border-dashed border-white/10 py-3 text-sm text-zinc-500 transition hover:border-white/25 hover:text-zinc-200"
        >
          + Add question
        </button>
      )}
      <p className="text-right text-[11px] text-zinc-600">
        {rows.length} / {MAX_QUESTIONS} questions
      </p>
    </div>
  );
}

function IconButton({
  label,
  disabled,
  danger,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-7 w-7 items-center justify-center rounded-lg text-xs transition disabled:opacity-20 ${
        danger
          ? "text-zinc-500 hover:bg-red-500/10 hover:text-red-300"
          : "text-zinc-500 hover:bg-white/5 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}
