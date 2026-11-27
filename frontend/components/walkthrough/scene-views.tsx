/**
 * The walkthrough's screens, drawn with the same classes as the real app (cards, buttons,
 * status pills, transcript bubbles), so the tour looks like CallZest itself.
 */
import type { ReactNode } from "react";

import { typed, type SceneId } from "./scenes";

/* Building blocks copied from the app's look */

export function Show({ when, children, className = "" }: { when: boolean; children: ReactNode; className?: string }) {
  return (
    <div
      className={`transition-[opacity,translate] duration-500 ease-out ${
        when ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-1.5 opacity-0"
      } ${className}`}
    >
      {children}
    </div>
  );
}

const BUTTON = {
  primary: "bg-[#1d4ed8] text-white",
  secondary: "border border-[#34363d] bg-[#24262b] text-zinc-200",
  danger: "border border-red-500/30 bg-red-500/10 text-red-300",
};

function Btn({
  target,
  children,
  variant = "primary",
  pressed = false,
  small = false,
  className = "",
}: {
  target?: string;
  children: ReactNode;
  variant?: keyof typeof BUTTON;
  pressed?: boolean;
  small?: boolean;
  className?: string;
}) {
  return (
    <span
      data-target={target}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap transition-transform duration-150 ${
        small ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm"
      } ${BUTTON[variant]} ${pressed ? "scale-95" : ""} ${className}`}
    >
      {children}
    </span>
  );
}

const TONE = {
  neutral: "bg-white/5 text-zinc-400",
  muted: "bg-white/5 text-zinc-500",
  green: "bg-[#0ca30c]/15 text-[#5fd35f]",
  blue: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  amber: "bg-amber-500/15 text-amber-300",
  red: "bg-red-500/15 text-red-300",
};

function Pill({ tone, live = false, children }: { tone: keyof typeof TONE; live?: boolean; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs whitespace-nowrap ${TONE[tone]}`}>
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {children}
    </span>
  );
}

function Card({ title, description, icon, action, children, className = "" }: {
  title?: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-3xl bg-[#18191c] p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            {icon && (
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/5 text-zinc-300">
                <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  {icon}
                </svg>
              </span>
            )}
            <div>
              {title && <h2 className="font-display text-base font-semibold text-white">{title}</h2>}
              {description && <p className="mt-0.5 text-sm text-zinc-500">{description}</p>}
            </div>
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

function Header({ back, title, badge, subtitle, actions, avatar }: {
  back: string;
  title: string;
  badge?: ReactNode;
  subtitle: string;
  actions?: ReactNode;
  avatar?: string;
}) {
  return (
    <div className="mb-4">
      <p className="mb-2 text-sm text-zinc-500">← {back}</p>
      <div className="flex items-end justify-between gap-3">
        <div className="flex items-center gap-3">
          {avatar && (
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#24262b] text-sm font-medium text-zinc-200">{avatar}</span>
          )}
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="font-display text-2xl font-semibold text-white">{title}</h1>
              {badge}
            </div>
            <p className="mt-0.5 text-sm text-zinc-500">{subtitle}</p>
          </div>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

function Check({ className = "h-3 w-3" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

function Box({ on, target }: { on: boolean; target?: string }) {
  return (
    <span
      data-target={target}
      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors duration-200 ${
        on ? "border-[#1d4ed8] bg-[#1d4ed8] text-white" : "border-zinc-500 bg-white"
      }`}
    >
      {on && <Check className="h-2.5 w-2.5" />}
    </span>
  );
}

function Dialog({ open, width = 480, children }: { open: boolean; width?: number; children: ReactNode }) {
  return (
    <div className={`absolute inset-0 z-10 flex items-center justify-center bg-black/60 transition-opacity duration-300 ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}>
      <div
        style={{ width }}
        className={`overflow-hidden rounded-3xl border border-white/10 bg-[#18191c] shadow-2xl shadow-black/70 transition-transform duration-300 ${open ? "scale-100" : "scale-95"}`}
      >
        {children}
      </div>
    </div>
  );
}

function Toast({ show, children }: { show: boolean; children: ReactNode }) {
  return (
    <div
      className={`absolute right-4 bottom-4 z-20 flex items-center gap-2.5 rounded-xl border border-[#0ca30c]/30 bg-[#18191c] px-4 py-3 text-sm text-zinc-100 shadow-xl shadow-black/60 transition-[opacity,translate] duration-300 ${
        show ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
      }`}
    >
      <span className="text-[#5fd35f]">
        <Check className="h-3.5 w-3.5" />
      </span>
      {children}
    </div>
  );
}

const pressedAt = (e: number, click: number) => e >= click && e < click + 220;

const PHONE_ICON = <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />;
const ROUND_ICON = (
  <>
    {PHONE_ICON}
    <path d="M15 3a6 6 0 0 1 6 6M15 7a2 2 0 0 1 2 2" />
  </>
);

/* Scene 1: add a job (the real form: numbered sections and a live preview) */

function FormRow({ label, required, children, target }: { label: string; required?: boolean; children: ReactNode; target?: string }) {
  return (
    <div className="grid grid-cols-[150px_1fr] items-center gap-4 py-2">
      <span className="text-xs font-medium tracking-wide text-zinc-500 uppercase">
        {label}
        {required && <span className="text-[#6b8cff]"> *</span>}
      </span>
      <div data-target={target}>{children}</div>
    </div>
  );
}

function Underline({ value, placeholder, caret }: { value: string; placeholder: string; caret?: boolean }) {
  return (
    <div className="flex h-9 items-center border-b border-[#2a2c31] text-sm">
      {value ? <span className="text-white">{value}</span> : <span className="text-zinc-600">{placeholder}</span>}
      {caret && <span className="cz-caret ml-px inline-block h-4 w-[1.5px] bg-zinc-200" />}
    </div>
  );
}

function SectionLine({ n, title, note }: { n: string; title: string; note?: string }) {
  return (
    <div className="mb-1 flex items-center gap-2.5">
      <span className="text-xs text-[#6b8cff] tabular-nums">{n}</span>
      <span className="text-sm font-semibold text-white">{title}</span>
      {note && <span className="text-xs text-zinc-600">{note}</span>}
      <span className="h-px flex-1 bg-[#2a2c31]" />
    </div>
  );
}

function JobScene({ e }: { e: number }) {
  const client = e >= 900 ? "Acme Hiring" : "";
  const title = typed("Backend Developer", e, 1500, 50);
  const hybrid = e >= 3300;
  const exp = e >= 3900;
  const ctc = e >= 4400;
  const notice = e >= 4800;
  const saved = e >= 6000;
  const modes = ["Not specified", "On-site", "Hybrid", "Remote"];
  return (
    <div className="relative h-full">
      <Header back="All jobs" title="Add job" subtitle="Choose the client it's for." />
      <div className="grid grid-cols-[1fr_270px] gap-4">
        <section className="rounded-3xl bg-[#18191c] px-6 py-5">
          <SectionLine n="01" title="The role" />
          <FormRow label="Client" required target="client">
            <div className="flex h-9 items-center justify-between border-b border-[#2a2c31] text-sm">
              <span className={client ? "text-white" : "text-zinc-300"}>{client || "Choose a client…"}</span>
              <span className="text-zinc-400">⌄</span>
            </div>
          </FormRow>
          <FormRow label="Role / title" required target="title">
            <Underline value={title} placeholder="Sales Executive" caret={e >= 1300 && e < 2700} />
          </FormRow>
          <FormRow label="Location">
            <Underline value={e >= 2500 ? "Pune" : ""} placeholder="Pune" />
          </FormRow>
          <FormRow label="Work mode">
            <div className="flex gap-2">
              {modes.map((m) => {
                const on = hybrid ? m === "Hybrid" : m === "Not specified";
                return (
                  <span
                    key={m}
                    data-target={m === "Hybrid" ? "mode-hybrid" : undefined}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors duration-200 ${
                      on ? "border-[#1d4ed8] bg-[#1d4ed8]/15 text-white" : "border-[#34363d] text-zinc-300"
                    } ${m === "Hybrid" && pressedAt(e, 3250) ? "scale-95" : ""}`}
                  >
                    {m}
                  </span>
                );
              })}
            </div>
          </FormRow>
          <div className="mt-4">
            <SectionLine n="02" title="Who fits" note="leave empty when it doesn't matter" />
          </div>
          <FormRow label="Experience" target="exp">
            <Range from={exp ? "3" : ""} to={exp ? "6" : ""} unit="years" />
          </FormRow>
          <FormRow label="CTC budget">
            <Range from={ctc ? "8" : ""} to={ctc ? "14" : ""} unit="LPA" />
          </FormRow>
          <FormRow label="Notice period">
            <div className="flex items-center gap-3 text-sm text-zinc-400">
              up to <span className="w-16 border-b border-[#2a2c31] py-1.5 text-center text-white">{notice ? "30" : "—"}</span> days
            </div>
          </FormRow>
          <div className="mt-3 flex items-center justify-between border-t border-[#2a2c31] pt-4">
            <span className="text-xs text-zinc-500">Screening call: 10 default + 0 must-haves = 10 questions</span>
            <Btn target="save" pressed={pressedAt(e, 5900)}>
              Add job →
            </Btn>
          </div>
        </section>

        <div>
          <section className="rounded-3xl bg-[#18191c] p-5">
            <p className="text-[11px] font-medium tracking-wider text-zinc-500 uppercase">{client || " "}</p>
            <div className="mt-1 flex items-start justify-between gap-2">
              <p className={`font-display text-lg font-semibold ${title ? "text-white" : "text-zinc-500"}`}>{title || "Role / title"}</p>
              <Pill tone="green">Open</Pill>
            </div>
            <p className="text-sm text-zinc-400">{e >= 2500 ? `Pune${hybrid ? " · Hybrid" : ""}` : "—"}</p>
            <p className="mt-4 flex items-baseline gap-2">
              <span className="font-display text-4xl font-semibold">1</span>
              <span className="text-xs text-zinc-500">person needed</span>
            </p>
            <div className="mt-4 grid grid-cols-3 gap-2 border-t border-[#2a2c31] pt-3 text-xs">
              {[
                ["Experience", exp ? "3–6 yrs" : "—"],
                ["CTC", ctc ? "8–14 LPA" : "—"],
                ["Notice", notice ? "≤ 30 days" : "—"],
              ].map(([k, v]) => (
                <div key={k}>
                  <p className="text-zinc-500">{k}</p>
                  <p className="mt-0.5 text-sm text-white">{v}</p>
                </div>
              ))}
            </div>
            <span className="mt-4 inline-block rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-zinc-400">No JD yet</span>
          </section>
          <p className="mt-2 text-center text-xs text-zinc-500">Live preview</p>
        </div>
      </div>
      <Toast show={saved && e < 7500}>Job added · Backend Developer</Toast>
    </div>
  );
}

function Range({ from, to, unit }: { from: string; to: string; unit: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-zinc-400">
      from <span className="w-16 border-b border-[#2a2c31] py-1.5 text-center text-white">{from || "—"}</span>
      to <span className="w-16 border-b border-[#2a2c31] py-1.5 text-center text-white">{to || "—"}</span>
      {unit}
    </div>
  );
}

/* The job page, shared by the upload, calls and round scenes */

const PEOPLE = [
  ["Priya Nair", "+919820100001"],
  ["Rahul Verma", "+919967400002"],
  ["Ananya Iyer", "+919004000003"],
  ["Karan Mehta", "+919833000004"],
  ["Sneha Rao", "+919822000005"],
];
const initials = (n: string) => n.split(" ").map((p) => p[0]).join("");

function JobSide() {
  return (
    <section className="rounded-3xl bg-[#18191c] p-5">
      <p className="text-[11px] font-medium tracking-wider text-zinc-500 uppercase">Acme Hiring</p>
      <div className="mt-1 flex items-start justify-between gap-2">
        <p className="font-display text-lg font-semibold">Backend Developer</p>
        <Pill tone="green">Open</Pill>
      </div>
      <p className="text-sm text-zinc-400">Pune · Hybrid</p>
      <p className="mt-4 flex items-baseline gap-2">
        <span className="font-display text-4xl font-semibold">3</span>
        <span className="text-xs text-zinc-500">people needed</span>
      </p>
      <div className="mt-4 grid grid-cols-3 gap-2 border-t border-[#2a2c31] pt-3 text-xs">
        {[
          ["Experience", "3–6 yrs"],
          ["CTC", "8–14 LPA"],
          ["Notice", "≤ 30 days"],
        ].map(([k, v]) => (
          <div key={k}>
            <p className="text-zinc-500">{k}</p>
            <p className="mt-0.5 text-sm text-white">{v}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {["Python", "FastAPI", "PostgreSQL"].map((s) => (
          <span key={s} className="rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-zinc-300">
            {s}
          </span>
        ))}
      </div>
    </section>
  );
}

function JobHeader() {
  return (
    <Header
      back="All jobs"
      title="Backend Developer"
      badge={<Pill tone="green">Open</Pill>}
      subtitle="Acme Hiring · Pune · Hybrid · 3 openings"
      actions={<Btn variant="secondary">Edit job details</Btn>}
    />
  );
}

function Roster({ count, status }: { count: number; status: (i: number) => ReactNode }) {
  return (
    <div>
      <div className="grid grid-cols-[24px_1fr_130px_70px_60px] items-center gap-3 border-b border-[#2a2c31] px-1 pb-2 text-[11px] tracking-wide text-zinc-500 uppercase">
        <Box on={false} />
        <span>Candidate</span>
        <span>Call</span>
        <span>Result</span>
        <span />
      </div>
      {PEOPLE.slice(0, count).map(([name, phone], i) => (
        <div key={name} className="cz-rise grid grid-cols-[24px_1fr_130px_70px_60px] items-center gap-3 border-b border-white/5 px-1 py-2.5 last:border-0">
          <Box on={false} />
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#24262b] text-xs font-medium text-zinc-300">{initials(name)}</span>
            <div>
              <p className="text-sm font-medium text-white">{name}</p>
              <p className="text-xs text-zinc-500">{phone}</p>
            </div>
          </div>
          <span data-target={`status-${i}`}>{status(i)}</span>
          <span className="text-zinc-600">—</span>
          <Btn variant="secondary" small>
            Call
          </Btn>
        </div>
      ))}
    </div>
  );
}

function ScreeningCard({ e, count, calls, status, uploadClick, callClick }: {
  e: number;
  count: number;
  calls: number;
  status: (i: number) => ReactNode;
  uploadClick?: number;
  callClick?: number;
}) {
  return (
    <Card
      title="Screening calls"
      description="Upload a list, call it, and see who's interested."
      icon={PHONE_ICON}
      action={
        <div className="flex gap-2">
          <Btn target="upload" variant="secondary" pressed={uploadClick !== undefined && pressedAt(e, uploadClick)}>
            Upload list
          </Btn>
          <Btn target="call-all" pressed={callClick !== undefined && pressedAt(e, callClick)} className={calls ? "" : "opacity-50"}>
            Call not-called ({calls})
          </Btn>
        </div>
      }
    >
      <div className="mb-4 flex items-center justify-between rounded-2xl bg-white/[0.03] px-4 py-2.5 text-sm">
        <span>
          The call asks <b className="font-semibold">10 questions</b>
          <span className="ml-2 text-zinc-500">10 default + 0 must-haves</span>
        </span>
        <span className="text-xs text-zinc-300">See questions</span>
      </div>
      {count === 0 ? (
        <div className="flex h-[250px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 text-center">
          <p className="font-display font-semibold text-white">No candidates yet</p>
          <p className="mt-1 text-sm text-zinc-500">Upload a list to call it.</p>
        </div>
      ) : (
        <>
          <p className="mb-3 flex items-baseline gap-2">
            <span className="font-display text-3xl font-semibold">{count}</span>
            <span className="text-sm text-zinc-500">candidates</span>
          </p>
          <Roster count={count} status={status} />
        </>
      )}
    </Card>
  );
}

const notCalled = () => <span className="text-xs text-zinc-500">Not called</span>;

/* Scene 2: upload a list */

const ROWS: [number, string, string, "valid" | "dup" | "invalid", string][] = [
  [2, "Priya Nair", "9820100001", "valid", ""],
  [3, "Rahul Verma", "9967400002", "valid", ""],
  [4, "Ananya Iyer", "9004000003", "valid", ""],
  [5, "Rahul Verma", "9967400002", "dup", "phone: also on row 3"],
  [6, "Karan Mehta", "9833000004", "valid", ""],
  [7, "Sneha Rao", "9822000005", "valid", ""],
];

function UploadScene({ e }: { e: number }) {
  const open = e >= 950 && e < 6450;
  const dropped = e >= 2050;
  const consent = e >= 5350;
  const imported = e >= 6450;
  return (
    <div className="relative h-full">
      <JobHeader />
      <div className="grid grid-cols-[1fr_250px] gap-4">
        <ScreeningCard e={e} count={imported ? 5 : 0} calls={imported ? 5 : 0} status={notCalled} uploadClick={850} />
        <JobSide />
      </div>

      <Dialog open={open} width={640}>
        <header className="flex items-start justify-between border-b border-white/5 px-6 py-4">
          <div>
            <h2 className="font-display text-lg font-semibold">Upload a list</h2>
            <p className="text-sm text-zinc-500">For Backend Developer · Acme Hiring</p>
          </div>
          <span className="text-zinc-500">✕</span>
        </header>
        <div className="space-y-3 px-6 py-4">
          {!dropped ? (
            <div data-target="drop" className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/15 bg-white/[0.02] px-6 py-10 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5 text-zinc-300">
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 15V4M7 9l5-5 5 5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
                </svg>
              </span>
              <span className="font-display mt-4 font-semibold text-white">Drop a .csv or .xlsx here, or click to choose</span>
              <span className="mt-1 text-sm text-zinc-500">Up to 5 MB and 1,000 rows. Nothing is saved until you import.</span>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2 text-xs">
                {[
                  ["Rows", 6, "text-zinc-200"],
                  ["Valid", 5, "text-green-300"],
                  ["Duplicates", 1, "text-amber-300"],
                  ["Invalid", 0, "text-red-300"],
                ].map(([k, v, tone]) => (
                  <span key={k as string} className="rounded-full bg-white/5 px-3 py-1 text-zinc-400">
                    {k} <b className={`tabular-nums ${tone}`}>{v}</b>
                  </span>
                ))}
                <span className="ml-auto self-center text-zinc-500">candidates.xlsx</span>
              </div>
              <div className="overflow-hidden rounded-2xl border border-white/5">
                <div className="grid grid-cols-[44px_110px_1fr_110px_1fr] border-b border-white/10 px-3 py-2 text-[11px] text-zinc-500 uppercase">
                  <span>Row</span>
                  <span>Status</span>
                  <span>Name</span>
                  <span>Phone</span>
                  <span>Problems</span>
                </div>
                {ROWS.map(([row, name, phone, st, problem], i) => (
                  <Show key={row} when={e >= 2400 + i * 220}>
                    <div className="grid grid-cols-[44px_110px_1fr_110px_1fr] border-b border-white/5 px-3 py-2 text-sm text-zinc-200 last:border-0">
                      <span className="text-zinc-500">{row}</span>
                      <span className={st === "valid" ? "text-green-400" : st === "dup" ? "text-amber-400" : "text-red-400"}>
                        {st === "valid" ? "Valid" : st === "dup" ? "Duplicate in file" : "Invalid"}
                      </span>
                      <span>{name}</span>
                      <span className="font-mono text-xs leading-5">{phone}</span>
                      <span className="text-xs leading-5 text-amber-400">{problem}</span>
                    </div>
                  </Show>
                ))}
              </div>
            </>
          )}
        </div>
        <footer className="space-y-3 border-t border-white/5 px-6 py-4">
          <label className="flex items-center gap-2.5 text-sm text-zinc-300">
            <Box on={consent} target="consent" />
            These candidates have agreed to be contacted by phone about this role.
          </label>
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-500">Invalid and duplicate rows are skipped.</span>
            <div className="flex gap-2">
              <Btn variant="secondary">Choose another file</Btn>
              <Btn target="import" pressed={pressedAt(e, 6300)} className={consent ? "" : "opacity-50"}>
                Import 5 valid candidates
              </Btn>
            </div>
          </div>
        </footer>
      </Dialog>
      <Toast show={imported && e < 8300}>5 candidates imported</Toast>
    </div>
  );
}

/* Scene 3: start the calls */

function CallsScene({ e }: { e: number }) {
  const queued = e >= 3300;
  const status = (i: number): ReactNode => {
    if (!queued) return notCalled();
    if (i === 0) {
      if (e >= 5000) return <Pill tone="green" live>On call</Pill>;
      if (e >= 4300) return <Pill tone="blue" live>Ringing</Pill>;
      if (e >= 3800) return <Pill tone="blue" live>Dialling</Pill>;
    }
    if (i === 1 && e >= 6400) return <Pill tone="blue" live>Dialling</Pill>;
    return <Pill tone="blue">Queued</Pill>;
  };
  return (
    <div className="relative h-full">
      <JobHeader />
      <div className="grid grid-cols-[1fr_250px] gap-4">
        <ScreeningCard e={e} count={5} calls={queued ? 0 : 5} status={status} callClick={850} />
        <JobSide />
      </div>

      <Dialog open={e >= 950 && e < 3300} width={440}>
        <div className="p-6">
          <h2 className="font-display text-lg font-semibold">Call 5 candidates?</h2>
          <div className="mt-4 space-y-4 text-sm">
            <dl className="grid grid-cols-2 gap-2 rounded-2xl bg-white/[0.03] p-3 text-xs">
              <div>
                <dt className="text-zinc-500">Calling hours</dt>
                <dd className="text-zinc-200">Open now · 10:00–19:00</dd>
              </div>
              <div>
                <dt className="text-zinc-500">At the same time</dt>
                <dd className="text-zinc-200">1 call, the rest wait in line</dd>
              </div>
            </dl>
            <div>
              <p className="mb-1.5 text-xs font-medium text-zinc-500 uppercase">Will be called (5)</p>
              <ul className="space-y-1 text-zinc-200">
                {PEOPLE.map(([n]) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Btn variant="secondary">Cancel</Btn>
            <Btn target="confirm" pressed={pressedAt(e, 3200)}>
              Call 5 candidates
            </Btn>
          </div>
        </div>
      </Dialog>
      <Toast show={queued && e < 5800}>5 calls queued.</Toast>
    </div>
  );
}

/* Scenes 4 and 5: the candidate page */

const LINES: { at: number; ai: boolean; text: string; time: string }[] = [
  { at: 300, ai: true, time: "10:41:02", text: "Hi Priya, this is CallZest, an AI assistant calling about the Backend Developer role at Acme Hiring. Is now a good time?" },
  { at: 1500, ai: false, time: "10:41:09", text: "Yes, go ahead." },
  { at: 2400, ai: true, time: "10:41:11", text: "Great. Are you interested in this role?" },
  { at: 3300, ai: false, time: "10:41:15", text: "Yes, I am. I'm looking for a backend role in Pune." },
  { at: 4400, ai: true, time: "10:41:19", text: "And what is your notice period?" },
  { at: 5300, ai: false, time: "10:41:23", text: "Thirty days. I can join early next month." },
  { at: 6300, ai: true, time: "10:41:26", text: "Thanks. What is your current CTC?" },
];

function Tile({ label, value, state, quote, target, hover = false }: {
  label: string;
  value: string;
  state: "missing" | "answered" | "confirmed";
  quote?: string;
  target?: string;
  hover?: boolean;
}) {
  const tone = state === "confirmed" ? "green" : state === "answered" ? "blue" : "muted";
  return (
    <div data-target={target} className={`relative rounded-2xl p-3.5 transition-colors duration-500 ${hover ? "bg-[#26282d]" : "bg-[#202226]"}`}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs text-zinc-400">{label}</span>
        <Pill tone={tone}>{state === "missing" ? "Missing" : state === "answered" ? "Answered" : "Confirmed"}</Pill>
      </div>
      <p className={`mt-1 text-sm font-medium ${state === "missing" ? "text-zinc-500" : "text-white"}`}>{state === "missing" ? "—" : value}</p>
      {quote && state !== "missing" && <p className="mt-1 truncate text-xs text-zinc-500 italic">“{quote}”</p>}
      {hover && quote && (
        <div className="cz-rise absolute top-full left-3 z-10 mt-1.5 w-64 rounded-xl border border-white/10 bg-[#0e0f11] px-3 py-2 text-xs text-zinc-300 shadow-xl shadow-black/60">
          The candidate said: <span className="italic">“{quote}”</span> <span className="text-zinc-500">(line 8)</span>
        </div>
      )}
    </div>
  );
}

function CandidateHeader({ badge, actions }: { badge: ReactNode; actions: ReactNode }) {
  return <Header back="Back to candidates" avatar="PN" title="Priya Nair" badge={badge} subtitle="Backend Developer · +919820100001" actions={actions} />;
}

function LiveScene({ e }: { e: number }) {
  const secs = 58 + Math.floor(e / 1000);
  const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const answers: [string, string, number, string][] = [
    ["Interested", "Yes", 3800, "Yes, I am"],
    ["Notice period", "30 days", 5800, "Thirty days"],
    ["Current CTC", "", Infinity, ""],
  ];
  return (
    <div className="relative h-full">
      <CandidateHeader
        badge={<Pill tone="blue">In progress</Pill>}
        actions={
          <>
            <Btn className="opacity-50">Call now</Btn>
            <Btn variant="secondary">Mark opted out</Btn>
          </>
        }
      />
      <div className="grid grid-cols-[300px_1fr] gap-4">
        <div className="space-y-4">
          <Card title="Call history">
            <div className="rounded-2xl bg-white/[0.03] p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-200">#1 · Screening</span>
                <Pill tone="green" live>
                  On call
                </Pill>
              </div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-zinc-500 tabular-nums">Today, 10:41 · {clock}</span>
                <Btn target="end-call" variant="danger" small>
                  End call
                </Btn>
              </div>
            </div>
          </Card>
          <section data-target="answers" className="rounded-3xl bg-[#18191c] p-5">
            <h2 className="font-display mb-3 text-base font-semibold">Screening answers</h2>
            <div className="space-y-2">
              {answers.map(([label, value, at, quote]) => (
                <Tile key={label} label={label} value={value} quote={quote} state={e >= at ? "answered" : "missing"} />
              ))}
            </div>
          </section>
        </div>
        <section data-target="transcript" className="flex h-[476px] flex-col rounded-3xl bg-[#18191c] p-5">
          <div className="mb-4 flex items-center gap-2 text-sm text-zinc-400">
            <h2 className="font-display mr-2 text-base font-semibold text-white">Transcript</h2>
            <span className="rounded-lg border border-[#34363d] bg-[#24262b] px-2 py-1 text-xs text-white">#1 · Today, 10:41</span>
            <Pill tone="green" live>
              On call
            </Pill>
            <span className="text-xs tabular-nums">{clock}</span>
          </div>
          <ol className="flex flex-1 flex-col justify-end gap-2 overflow-hidden">
            {LINES.filter((l) => e >= l.at).map((l, i) => (
              <li key={l.at} className={`cz-rise flex ${l.ai ? "justify-start" : "justify-end"}`}>
                <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${l.ai ? "rounded-tl-md bg-white/5 text-zinc-200" : "rounded-tr-md bg-[#1d4ed8]/25 text-white"}`}>
                  <div className="mb-0.5 flex gap-2 text-[11px] text-zinc-500">
                    <span>{l.ai ? "CallZest AI" : "Candidate"}</span>
                    <span className="tabular-nums">{l.time}</span>
                    <span className="tabular-nums">line {i + 1}</span>
                  </div>
                  {l.text}
                </div>
              </li>
            ))}
            {e >= 7000 && (
              <li className="flex justify-end gap-1 pr-2 text-zinc-500">
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current" />
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:150ms]" />
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:300ms]" />
              </li>
            )}
          </ol>
        </section>
      </div>
    </div>
  );
}

function ReviewScene({ e }: { e: number }) {
  const kept = e >= 5100;
  const summary =
    "Interested in the role and based in Pune. 4 years in backend work, on 12 LPA now and expecting 15. Can join in 30 days, early next month.";
  return (
    <div className="relative h-full">
      <CandidateHeader
        badge={<Pill tone="green">Completed</Pill>}
        actions={
          <>
            <Btn>Call now</Btn>
            <Btn variant="secondary">Mark opted out</Btn>
          </>
        }
      />
      <div className="grid grid-cols-[300px_1fr] gap-4">
        <div className="space-y-4">
          <Card title="Details">
            <dl className="text-sm">
              {[
                ["Phone", "+919820100001"],
                ["Applied role", "Backend Developer"],
                ["Experience", "4 yrs"],
                ["Location", "Pune"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-white/5 py-2 last:border-0">
                  <dt className="text-zinc-500">{k}</dt>
                  <dd className="text-white">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Show when={e >= 3900 && !kept}>
            <div className="rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-4 text-sm">
              <p className="mb-2 font-medium text-white">Current CTC: two different answers</p>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-black/30 p-2.5">
                  <p className="text-xs text-zinc-500">Stored</p>
                  <p className="font-medium text-white">12 LPA</p>
                  <p className="mt-0.5 text-xs text-zinc-400 italic">“around twelve lakhs” (line 8)</p>
                </div>
                <div className="rounded-xl bg-black/30 p-2.5">
                  <p className="text-xs text-zinc-500">Also said</p>
                  <p className="font-medium text-white">14 LPA</p>
                  <p className="mt-0.5 text-xs text-zinc-400 italic">“fourteen with the variable” (line 15)</p>
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                <Btn target="keep" variant="secondary" small pressed={pressedAt(e, 5000)}>
                  Keep 12 LPA
                </Btn>
                <Btn small>Use 14 LPA</Btn>
              </div>
            </div>
          </Show>
        </div>
        <div className="space-y-4">
          <Show when={e >= 200}>
            <section data-target="summary" className="rounded-3xl bg-[#18191c] p-5">
              <h2 className="font-display mb-2 text-base font-semibold">Summary</h2>
              <p className="min-h-[40px] text-sm leading-relaxed text-zinc-200">{typed(summary, e, 400, 12)}</p>
            </section>
          </Show>
          <section className="rounded-3xl bg-[#18191c] p-5">
            <h2 className="font-display text-base font-semibold">Screening answers</h2>
            <p className="mt-0.5 mb-3 text-sm text-zinc-500">Filled in by the screening calls. Hover an answer to see the candidate&apos;s words.</p>
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["Location", "Pune", "confirmed", "a backend role in Pune"],
                  ["Total experience", "4 years", "confirmed", "about four years now"],
                  ["Current CTC", "12 LPA", "answered", "around twelve lakhs"],
                  ["Expected CTC", "15 LPA", "answered", "fifteen would be good"],
                  ["Notice period", "30 days", "confirmed", "Thirty days"],
                  ["Interested", "Yes", "confirmed", "Yes, I am"],
                ] as const
              ).map(([label, value, state, quote], i) => (
                <Show key={label} when={e >= 1000 + i * 150}>
                  <Tile
                    label={label}
                    value={value}
                    state={state}
                    target={label === "Current CTC" ? "answer-ctc" : undefined}
                    quote={label === "Current CTC" ? quote : undefined}
                    hover={label === "Current CTC" && e >= 3000 && e < 4300}
                  />
                </Show>
              ))}
            </div>
          </section>
        </div>
      </div>
      <Toast show={kept && e < 8000}>Current CTC: kept 12 LPA</Toast>
    </div>
  );
}

/* Scene 6: the telephonic round on the job page */

const ROUND_QUESTIONS = [
  "Walk me through an API you built with FastAPI, end to end.",
  "A PostgreSQL query got slow in production. How do you find out why?",
  "How do you make a background job safe to retry?",
  "How would you version a public API without breaking old clients?",
];

function RoundScene({ e }: { e: number }) {
  const level = e >= 900 ? "Medium" : "Easy";
  const writing = e >= 2050 && e < 3300;
  const drafted = e >= 3300;
  const approved = e >= 4400;
  const calls: [string, number, ReactNode][] = [
    ["Priya Nair", 5000, e >= 5700 ? <Verdict tone="green" label="Strong fit · 82" target="verdict" /> : <Pill tone="green" live>On call</Pill>],
    ["Rahul Verma", 6300, e >= 7000 ? <Verdict tone="amber" label="Possible fit · 64" /> : <Pill tone="blue" live>Dialling</Pill>],
    ["Ananya Iyer", 6600, <Pill key="q" tone="blue">Queued</Pill>],
  ];
  return (
    <div className="relative h-full">
      <JobHeader />
      <Card
        title="Telephonic round"
        description="Questions made from the JD, asked on a second call and scored."
        icon={ROUND_ICON}
        action={approved ? <Pill tone="green">Approved · v1</Pill> : drafted ? <Pill tone="amber">Draft</Pill> : undefined}
      >
        {!drafted ? (
          <div className="flex h-[400px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 text-center">
            {writing ? (
              <>
                <span className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-white" />
                <p className="font-display mt-4 font-semibold text-white">Writing questions from the JD…</p>
                <p className="mt-1 text-sm text-zinc-500">This can take up to a minute.</p>
              </>
            ) : (
              <>
                <p className="font-display font-semibold text-white">No questions yet</p>
                <p className="mt-1 max-w-md text-sm text-zinc-500">
                  The AI reads the JD and writes questions with what a good answer covers. You check them, change anything, then approve.
                </p>
                <div className="mt-5 w-[420px] text-left">
                  <div className="flex justify-between text-xs text-zinc-400">
                    <span>Questions</span>
                    <span className="text-sm text-white">8</span>
                  </div>
                  <div className="relative mt-2 h-1.5 rounded-full bg-white">
                    <div className="absolute inset-y-0 left-0 w-[55%] rounded-full bg-[#1d4ed8]" />
                    <span className="absolute top-1/2 left-[55%] h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#1d4ed8] ring-2 ring-white" />
                  </div>
                  <p className="mt-4 mb-1.5 text-xs text-zinc-400">Level</p>
                  <div className="grid grid-cols-3 gap-2">
                    {["Easy", "Medium", "Hard"].map((l) => (
                      <span
                        key={l}
                        data-target={l === "Medium" ? "level-medium" : undefined}
                        className={`rounded-lg border py-1.5 text-center text-xs transition-colors ${
                          l === level ? "border-[#1d4ed8] bg-[#1d4ed8]/15 text-white" : "border-[#34363d] text-zinc-300"
                        }`}
                      >
                        {l}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="mt-5 flex gap-2">
                  <Btn target="generate" pressed={pressedAt(e, 1950)}>
                    ✦ Generate with AI
                  </Btn>
                  <Btn variant="secondary">Write my own</Btn>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-[1fr_330px] gap-4">
            <div>
              <ol className="space-y-2">
                {ROUND_QUESTIONS.map((q, i) => (
                  <Show key={q} when={e >= 3300 + i * 150}>
                    <li className="flex gap-3 rounded-2xl bg-white/[0.03] px-3.5 py-2.5 text-sm text-zinc-200">
                      <span className="text-zinc-500 tabular-nums">{i + 1}</span>
                      <span className="flex-1">{q}</span>
                      <span className="self-start rounded-md bg-white/5 px-1.5 py-0.5 text-[10px] text-zinc-400">Medium</span>
                    </li>
                  </Show>
                ))}
              </ol>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-zinc-500">+ 4 more · edit any question before approving</span>
                {!approved && (
                  <Btn target="approve" pressed={pressedAt(e, 4300)}>
                    Approve questions
                  </Btn>
                )}
              </div>
            </div>
            <Show when={approved}>
              <div className="rounded-2xl bg-white/[0.03] p-4">
                <p className="mb-3 text-sm font-medium text-white">Telephonic calls</p>
                <div className="space-y-2">
                  {calls.map(([name, at, badge]) => (
                    <Show key={name} when={e >= at}>
                      <div className="flex items-center justify-between rounded-xl bg-[#202226] px-3 py-2.5">
                        <span className="text-sm text-zinc-100">{name}</span>
                        {badge}
                      </div>
                    </Show>
                  ))}
                </div>
                <Show when={e >= 6000} className="mt-3 space-y-1.5">
                  {[
                    ["4/5", "text-green-300", "Clear design, covered retries", "idempotency keys on the payments API"],
                    ["5/5", "text-green-300", "Right first steps", "EXPLAIN ANALYZE, then the indexes"],
                    ["3/5", "text-amber-300", "Retry yes, no dead-letter queue", "we retry a few times"],
                  ].map(([s, tone, reason, quote]) => (
                    <div key={reason} className="rounded-xl bg-white/[0.03] px-3 py-2 text-xs">
                      <span className={`font-semibold tabular-nums ${tone}`}>{s}</span> <span className="text-zinc-400">{reason}</span>
                      <span className="text-zinc-500"> · “{quote}”</span>
                    </div>
                  ))}
                </Show>
              </div>
            </Show>
          </div>
        )}
      </Card>
    </div>
  );
}

function Verdict({ tone, label, target }: { tone: "green" | "amber"; label: string; target?: string }) {
  return (
    <span
      data-target={target}
      className={`cz-rise rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap tabular-nums ${
        tone === "green" ? "bg-green-500/10 text-green-300" : "bg-amber-400/10 text-amber-300"
      }`}
    >
      {label}
    </span>
  );
}

export function SceneView({ id, e }: { id: SceneId; e: number }) {
  switch (id) {
    case "job":
      return <JobScene e={e} />;
    case "upload":
      return <UploadScene e={e} />;
    case "calls":
      return <CallsScene e={e} />;
    case "live":
      return <LiveScene e={e} />;
    case "review":
      return <ReviewScene e={e} />;
    case "round":
      return <RoundScene e={e} />;
  }
}

