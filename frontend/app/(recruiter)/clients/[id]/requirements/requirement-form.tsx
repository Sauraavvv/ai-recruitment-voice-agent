"use client";

import { type FormEvent, type KeyboardEvent, type ReactNode, useState } from "react";

import { Alert, Button } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { type DefaultQuestion, questionCount, repeatsDefault } from "@/lib/must-haves";
import { useLoad } from "@/lib/use-load";
import { defaultQuestions } from "@/services/jobs";
import type { Requirement, RequirementCreate, RequirementStatus } from "@/types";

import { Pills, Row, Section, line } from "../../form-layout";

export const REQUIREMENT_STATUS: Record<RequirementStatus, { label: string; tone: string }> = {
  open: { label: "Open", tone: "bg-green-500/10 text-green-300" },
  on_hold: { label: "On hold", tone: "bg-amber-500/10 text-amber-300" },
  filled: { label: "Filled", tone: "bg-blue-500/10 text-blue-300" },
  closed: { label: "Closed", tone: "bg-white/5 text-zinc-400" },
};

export const WORK_MODES: Record<string, string> = {
  "": "Not specified",
  onsite: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
};

const MAX_JD = 20000;
const MAX_SKILLS = 30;
const MAX_MUST_HAVES = 15;

/** "1–4.5 yrs", "3+ yrs", "up to 6 LPA" … or "" when neither end is set. */
export function range(
  min: number | null | undefined,
  max: number | null | undefined,
  unit: string,
) {
  if (min != null && max != null) return min === max ? `${min} ${unit}` : `${min}–${max} ${unit}`;
  if (min != null) return `${min}+ ${unit}`;
  if (max != null) return `up to ${max} ${unit}`;
  return "";
}

// The form keeps numbers as text while typing
type Draft = {
  title: string;
  location: string;
  work_mode: string;
  openings: string;
  experience_min: string;
  experience_max: string;
  ctc_min: string;
  ctc_max: string;
  notice_max_days: string;
  skills: string[];
  must_haves: string[];
  job_description: string;
  deadline: string;
  notes: string;
  status: RequirementStatus;
};

const str = (v: number | null | undefined) => (v == null ? "" : String(v));

function toDraft(r?: Requirement): Draft {
  return {
    title: r?.title ?? "",
    location: r?.location ?? "",
    work_mode: r?.work_mode ?? "",
    openings: String(r?.openings ?? 1),
    experience_min: str(r?.experience_min),
    experience_max: str(r?.experience_max),
    ctc_min: str(r?.ctc_min),
    ctc_max: str(r?.ctc_max),
    notice_max_days: str(r?.notice_max_days),
    skills: r?.skills ?? [],
    must_haves: r?.must_haves ?? [],
    job_description: r?.job_description ?? "",
    deadline: r?.deadline ?? "",
    notes: r?.notes ?? "",
    status: r?.status ?? "open",
  };
}

const num = (v: string) => (v.trim() === "" ? null : Number(v));

function toBody(d: Draft): RequirementCreate {
  return {
    title: d.title,
    location: d.location,
    work_mode: d.work_mode as RequirementCreate["work_mode"],
    openings: Number(d.openings) || 1,
    experience_min: num(d.experience_min),
    experience_max: num(d.experience_max),
    ctc_min: num(d.ctc_min),
    ctc_max: num(d.ctc_max),
    notice_max_days: num(d.notice_max_days),
    skills: d.skills,
    must_haves: d.must_haves,
    job_description: d.job_description,
    deadline: d.deadline || null,
    notes: d.notes,
    status: d.status,
  };
}

// A short number box that sits inline in a sentence ("from [1] to [4] years")
const small =
  "w-20 border-0 border-b border-white/10 bg-transparent px-1 py-2 text-center text-[15px] " +
  "text-white placeholder:text-zinc-700 outline-none transition focus:border-[#2563eb]";

/**
 * Add or edit a requirement: a sectioned form on the left, the requirement's card building
 * itself live on the right. `onSave` throws on failure; the error is shown above the form.
 */
export function RequirementForm({
  requirement,
  clientName,
  submitLabel,
  onSave,
}: {
  requirement?: Requirement;
  clientName?: string;
  submitLabel: string;
  onSave: (body: RequirementCreate) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(requirement));
  const [busy, setBusy] = useState(false);
  // The screening call asks these first, then one yes / no question per must-have
  const { data: defaults } = useLoad("default-questions", defaultQuestions);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const bind = (key: keyof Draft) => ({
    value: draft[key] as string,
    onChange: (e: { target: { value: string } }) => set(key, e.target.value as never),
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSave(toBody(draft));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const openings = Number(draft.openings) || 1;

  return (
    <form onSubmit={onSubmit} className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-9 rounded-3xl bg-[#18191c] p-6 sm:p-8">
        {error && <Alert>{error}</Alert>}

        <Section n="01" title="The role">
          <Row label="Role / title" required>
            <input
              required
              autoFocus={!requirement}
              maxLength={200}
              placeholder="Sales Executive"
              className={`${line} font-display text-lg`}
              {...bind("title")}
            />
          </Row>
          <Row label="Location">
            <input maxLength={200} placeholder="Pune" className={line} {...bind("location")} />
          </Row>
          <Row label="Work mode" as="div">
            <Pills
              label="Work mode"
              options={Object.entries(WORK_MODES).map(([value, label]) => ({ value, label }))}
              value={draft.work_mode}
              onChange={(v) => set("work_mode", v)}
            />
          </Row>
          <Row label="People needed" required as="div">
            <div className="flex items-center gap-2 py-1">
              <StepButton
                label="One less"
                disabled={openings <= 1}
                onClick={() => set("openings", String(Math.max(1, openings - 1)))}
              >
                −
              </StepButton>
              <input
                required
                type="number"
                min={1}
                max={1000}
                aria-label="People needed"
                className={`${small} w-16 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none`}
                {...bind("openings")}
              />
              <StepButton
                label="One more"
                disabled={openings >= 1000}
                onClick={() => set("openings", String(Math.min(1000, openings + 1)))}
              >
                +
              </StepButton>
              <span className="ml-2 text-xs text-zinc-500">
                {openings === 1 ? "person" : "people"}
              </span>
            </div>
          </Row>
        </Section>

        <Section n="02" title="Who fits" note="leave empty when it doesn't matter">
          <Row label="Experience" as="div">
            <InlineRange
              unit="years"
              step={0.5}
              max={50}
              from={bind("experience_min")}
              to={bind("experience_max")}
            />
          </Row>
          <Row label="CTC budget" as="div">
            <InlineRange
              unit="LPA"
              step={0.1}
              max={1000}
              from={bind("ctc_min")}
              to={bind("ctc_max")}
            />
          </Row>
          <Row label="Notice period" as="div">
            <div className="flex items-center gap-2 text-sm text-zinc-400">
              up to
              <input
                type="number"
                min={0}
                max={365}
                placeholder="—"
                aria-label="Notice period up to (days)"
                className={small}
                {...bind("notice_max_days")}
              />
              days
            </div>
          </Row>
          <Row label="Skills" as="div" hint="Press Enter or comma to add.">
            <ChipInput
              values={draft.skills}
              onChange={(v) => set("skills", v)}
              max={MAX_SKILLS}
              itemMax={60}
              placeholder="Field sales, Hindi, CRM…"
            />
          </Row>
          <Row
            label="Must-haves"
            as="div"
            hint="The screening call asks each one as a yes / no question."
          >
            <ListInput
              values={draft.must_haves}
              onChange={(v) => set("must_haves", v)}
              max={MAX_MUST_HAVES}
              itemMax={200}
              placeholder="Own two-wheeler"
              defaults={defaults}
            />
          </Row>
        </Section>

        <Section n="03" title="Job description" note="optional for screening calls">
          <div className="rounded-2xl border border-white/10 bg-black/20 focus-within:border-[#2563eb]">
            <textarea
              rows={10}
              maxLength={MAX_JD}
              placeholder="Paste the client's job description. The telephonic round makes its questions from this."
              className="block w-full resize-y rounded-2xl bg-transparent p-4 text-sm leading-relaxed text-zinc-200 outline-none placeholder:text-zinc-600"
              {...bind("job_description")}
            />
            <div className="flex justify-between border-t border-white/5 px-4 py-2 text-[11px] text-zinc-600">
              <span>Needed for the telephonic round</span>
              <span>
                {draft.job_description.length.toLocaleString("en-IN")} /{" "}
                {MAX_JD.toLocaleString("en-IN")}
              </span>
            </div>
          </div>
        </Section>

        <Section n="04" title="Tracking">
          <Row label="Status" as="div">
            <Pills
              label="Status"
              options={(Object.keys(REQUIREMENT_STATUS) as RequirementStatus[]).map((value) => ({
                value,
                label: REQUIREMENT_STATUS[value].label,
              }))}
              value={draft.status}
              onChange={(v) => set("status", v)}
            />
          </Row>
          <Row label="Deadline">
            <input type="date" className={`${line} [color-scheme:dark]`} {...bind("deadline")} />
          </Row>
          <Row label="Notes">
            <textarea
              rows={2}
              maxLength={5000}
              placeholder="Anything the team should know"
              className={`${line} resize-y`}
              {...bind("notes")}
            />
          </Row>
        </Section>

        <div className="flex justify-end">
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : submitLabel}
          </Button>
        </div>
      </div>

      <div className="lg:sticky lg:top-6 lg:self-start">
        <RequirementPreview draft={draft} clientName={clientName} />
        <p className="mt-3 text-center text-xs text-zinc-500">Live preview</p>
      </div>
    </form>
  );
}

function StepButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 text-zinc-300 transition hover:border-white/30 hover:text-white disabled:opacity-30"
    >
      {children}
    </button>
  );
}

type Bound = { value: string; onChange: (e: { target: { value: string } }) => void };

/** "from [ ] to [ ] years" in one line. */
function InlineRange({
  unit,
  step,
  max,
  from,
  to,
}: {
  unit: string;
  step: number;
  max: number;
  from: Bound;
  to: Bound;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-zinc-400">
      from
      <input
        type="number"
        min={0}
        max={max}
        step={step}
        placeholder="—"
        aria-label={`From (${unit})`}
        className={small}
        {...from}
      />
      to
      <input
        type="number"
        min={0}
        max={max}
        step={step}
        placeholder="—"
        aria-label={`To (${unit})`}
        className={small}
        {...to}
      />
      {unit}
    </div>
  );
}

/** Add a cleaned value unless it's empty or already there (ignoring case). */
function addTo(values: string[], raw: string, max: number, itemMax: number) {
  const value = raw.trim().replace(/\s+/g, " ").slice(0, itemMax);
  if (!value || values.length >= max) return values;
  if (values.some((v) => v.toLowerCase() === value.toLowerCase())) return values;
  return [...values, value];
}

/** Skills as removable chips; Enter or comma adds the typed one. */
function ChipInput({
  values,
  onChange,
  max,
  itemMax,
  placeholder,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  max: number;
  itemMax: number;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const commit = () => {
    onChange(addTo(values, text, max, itemMax));
    setText("");
  };
  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !text && values.length) {
      onChange(values.slice(0, -1));
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-white/10 py-1.5 focus-within:border-[#2563eb]">
      {values.map((v) => (
        <span
          key={v}
          className="flex items-center gap-1 rounded-full bg-white/[0.06] py-0.5 pr-1 pl-2.5 text-xs text-zinc-200"
        >
          {v}
          <button
            type="button"
            aria-label={`Remove ${v}`}
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="flex h-4 w-4 items-center justify-center rounded-full text-zinc-500 hover:bg-white/10 hover:text-white"
          >
            ×
          </button>
        </span>
      ))}
      {values.length < max && (
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          onBlur={commit}
          maxLength={itemMax}
          aria-label="Add a skill"
          placeholder={values.length ? "Add more…" : placeholder}
          className="min-w-[8rem] flex-1 bg-transparent px-1 py-1 text-[15px] text-white outline-none placeholder:text-zinc-600"
        />
      )}
    </div>
  );
}

/** Must-haves as a checklist: each line removable, a box at the end to add one. */
function ListInput({
  values,
  onChange,
  max,
  itemMax,
  placeholder,
  defaults,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  max: number;
  itemMax: number;
  placeholder: string;
  defaults?: DefaultQuestion[];
}) {
  const [text, setText] = useState("");
  const commit = () => {
    onChange(addTo(values, text, max, itemMax));
    setText("");
  };
  return (
    <div className="space-y-1.5 pt-1.5">
      {values.map((v, i) => {
        const repeat = defaults ? repeatsDefault(v, defaults) : null;
        return (
          <div
            key={v}
            className="group flex items-center gap-3 rounded-xl bg-white/[0.03] px-3 py-2 text-sm text-zinc-200"
          >
            <span className="font-display text-[11px] text-zinc-500">{i + 1}</span>
            <span className="min-w-0 flex-1">
              {v}
              {repeat && (
                <span className="block text-xs text-amber-300">
                  The call already asks question {repeat.number} ({repeat.prompt.replace(/\?$/, "")}
                  ). Make it more specific or remove it.
                </span>
              )}
            </span>
            <button
              type="button"
              aria-label={`Remove ${v}`}
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="text-zinc-600 opacity-0 transition group-hover:opacity-100 hover:text-red-300 focus-visible:opacity-100"
            >
              ×
            </button>
          </div>
        );
      })}
      {values.length < max && (
        <div className="flex items-center gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commit();
              }
            }}
            maxLength={itemMax}
            aria-label="Add a must-have"
            placeholder={values.length ? "Add another…" : placeholder}
            className={line}
          />
          <Button variant="secondary" onClick={commit} disabled={!text.trim()}>
            Add
          </Button>
        </div>
      )}
      <div className="flex flex-wrap justify-between gap-2 text-[11px] text-zinc-600">
        <span>
          {values.length} / {max}
        </span>
        {defaults && <span>Screening call: {questionCount(defaults.length, values.length)}</span>}
      </div>
    </div>
  );
}

/** The requirement's card, filled in as the form is typed. */
function RequirementPreview({ draft, clientName }: { draft: Draft; clientName?: string }) {
  const s = REQUIREMENT_STATUS[draft.status];
  const openings = Number(draft.openings) || 1;
  const exp = range(num(draft.experience_min), num(draft.experience_max), "yrs");
  const ctc = range(num(draft.ctc_min), num(draft.ctc_max), "LPA");
  const place = [draft.location, draft.work_mode ? WORK_MODES[draft.work_mode] : ""]
    .filter(Boolean)
    .join(" · ");
  const deadline = draft.deadline
    ? new Date(`${draft.deadline}T00:00:00`).toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "";
  const blank = <span className="text-zinc-600">—</span>;

  return (
    <div className="rounded-3xl bg-[#18191c] p-6 ring-1 ring-white/5">
      {clientName && (
        <div className="mb-1 truncate text-[11px] tracking-wider text-zinc-500 uppercase">
          {clientName}
        </div>
      )}
      <div className="flex items-start justify-between gap-3">
        <div className="font-display min-w-0 text-lg leading-snug font-semibold break-words text-white">
          {draft.title || <span className="text-zinc-600">Role / title</span>}
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${s.tone}`}>
          {s.label}
        </span>
      </div>
      <div className="mt-1 text-sm text-zinc-400">{place || blank}</div>

      <div className="mt-5 flex items-end gap-2">
        <span className="font-display text-4xl leading-none font-semibold text-white">
          {openings}
        </span>
        <span className="pb-1 text-xs text-zinc-500">
          {openings === 1 ? "person needed" : "people needed"}
        </span>
      </div>

      <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-white/5 pt-4 text-sm">
        <Fact label="Experience">{exp || blank}</Fact>
        <Fact label="CTC">{ctc || blank}</Fact>
        <Fact label="Notice">
          {draft.notice_max_days ? `≤ ${draft.notice_max_days} days` : blank}
        </Fact>
      </dl>

      {draft.skills.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-1.5">
          {draft.skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full bg-white/5 px-2.5 py-0.5 text-[11px] text-zinc-300"
            >
              {skill}
            </span>
          ))}
        </div>
      )}

      {draft.must_haves.length > 0 && (
        <ul className="mt-5 space-y-1.5 border-t border-dashed border-white/10 pt-4 text-sm">
          {draft.must_haves.map((m) => (
            <li key={m} className="flex gap-2 text-zinc-300">
              <span className="text-zinc-500">✓</span>
              <span className="min-w-0 break-words">{m}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex flex-wrap gap-1.5 border-t border-white/5 pt-4 text-[11px]">
        <span
          className={`rounded-full px-2.5 py-0.5 ${
            draft.job_description.trim() ? "bg-white/5 text-zinc-300" : "bg-white/5 text-zinc-500"
          }`}
        >
          {draft.job_description.trim() ? "JD added" : "No JD yet"}
        </span>
        {deadline && (
          <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-zinc-300">
            Due {deadline}
          </span>
        )}
      </div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-zinc-500">{label}</dt>
      <dd className="truncate text-zinc-200">{children}</dd>
    </div>
  );
}

/** A saved requirement's card (the same card as the form's live preview). */
export function RequirementCard({
  requirement,
  clientName,
}: {
  requirement: Requirement;
  clientName?: string;
}) {
  return <RequirementPreview draft={toDraft(requirement)} clientName={clientName} />;
}
