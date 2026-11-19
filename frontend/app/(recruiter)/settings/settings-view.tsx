"use client";

import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, Skeleton } from "@/components/states";
import { useToast } from "@/components/toast";
import { Button, Card, Field, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useLoad } from "@/lib/use-load";
import { getSettings, updateSettings } from "@/services/settings";
import type { GeneralUpdate, SettingsPage } from "@/types";

import { ProviderCards } from "./provider-cards";
import { SheetsCard } from "./sheets-card";

const DAYS: [string, string][] = [
  ["mon", "Mon"],
  ["tue", "Tue"],
  ["wed", "Wed"],
  ["thu", "Thu"],
  ["fri", "Fri"],
  ["sat", "Sat"],
  ["sun", "Sun"],
];
const HOURS = Array.from({ length: 25 }, (_, h) => h);
const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** The opening line as the agent would say it, for the template being edited. */
export function previewIntroduction(template: string, s: SettingsPage, organization: string) {
  const values: Record<string, string> = {
    first_name: s.introduction.sample_first_name,
    company: s.introduction.company,
    job_title: s.introduction.job_title,
    organization: organization.trim() || s.introduction.company,
  };
  return template.replace(/\{([^{}]*)\}/g, (match, key: string) => values[key] ?? match);
}

export function SettingsView() {
  const settings = useLoad("settings", getSettings);
  return (
    <>
      <PageHeader title="Settings" subtitle="Calling, the AI's introduction, and connections.">
        <Link href="/settings/job" className={buttonClass("secondary")}>
          Job settings
        </Link>
      </PageHeader>
      {settings.error && !settings.data && (
        <ErrorState error={settings.error} onRetry={settings.reload} />
      )}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          {settings.data ? (
            <>
              <PauseCard data={settings.data} onSaved={settings.setData} />
              <CallingCard data={settings.data} onSaved={settings.setData} />
              <IntroCard data={settings.data} onSaved={settings.setData} />
            </>
          ) : (
            !settings.error && <Skeleton className="h-96 rounded-3xl" />
          )}
        </div>
        <div className="space-y-4">
          <ProviderCards />
          <SheetsCard />
          {settings.data && <RetryCard data={settings.data} onSaved={settings.setData} />}
        </div>
      </div>
    </>
  );
}

function useSave(onSaved: (data: SettingsPage) => void) {
  const notify = useToast();
  const [busy, setBusy] = useState(false);
  async function save(body: GeneralUpdate, success: string) {
    setBusy(true);
    try {
      onSaved(await updateSettings(body));
      notify("success", success);
      return true;
    } catch (err) {
      notify("error", errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, save };
}

function PauseCard({ data, onSaved }: { data: SettingsPage; onSaved: (d: SettingsPage) => void }) {
  const { busy, save } = useSave(onSaved);
  const [confirm, setConfirm] = useState(false);
  const enabled = data.general.calling_enabled;
  return (
    <Card
      title="Calling"
      description={
        !data.limits.calling_enabled_env
          ? "Paused on the server (CALLING_ENABLED=false); this switch can't turn it on."
          : enabled
            ? data.calling_now
              ? "On. Calls go out now (inside calling hours)."
              : "On. Calls wait for calling hours."
            : "Paused. Nothing is dialed; queued calls are cancelled when their turn comes."
      }
      action={
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Calling enabled"
          disabled={busy}
          onClick={() =>
            enabled ? setConfirm(true) : save({ calling_enabled: true }, "Calling resumed.")
          }
          className={`relative h-7 w-12 shrink-0 rounded-full transition ${
            enabled ? "bg-[#0ca30c]" : "bg-zinc-700"
          } disabled:opacity-50`}
        >
          <span
            className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${
              enabled ? "left-6" : "left-1"
            }`}
          />
        </button>
      }
    >
      <p className={`text-sm font-medium ${enabled ? "text-[#5fd35f]" : "text-amber-300"}`}>
        {enabled ? "Calling is on" : "Calling is paused"}
      </p>
      <ConfirmDialog
        open={confirm}
        title="Pause all calling?"
        confirmLabel="Pause calling"
        danger
        busy={busy}
        onConfirm={async () => {
          if (await save({ calling_enabled: false }, "Calling paused.")) setConfirm(false);
        }}
        onClose={() => setConfirm(false)}
      >
        No new calls start, retries don&apos;t dial, and calls waiting in the queue are cancelled.
        Calls already on the line finish normally.
      </ConfirmDialog>
    </Card>
  );
}

function CallingCard({
  data,
  onSaved,
}: {
  data: SettingsPage;
  onSaved: (d: SettingsPage) => void;
}) {
  const { busy, save } = useSave(onSaved);
  const g = data.general;
  const [days, setDays] = useState<string[]>(g.calling.days);
  const [start, setStart] = useState(g.calling.start_hour);
  const [end, setEnd] = useState(g.calling.end_hour);
  const [concurrent, setConcurrent] = useState(g.max_concurrent_calls);
  const dirty =
    days.join() !== g.calling.days.join() ||
    start !== g.calling.start_hour ||
    end !== g.calling.end_hour ||
    concurrent !== g.max_concurrent_calls;
  const invalid = days.length === 0 || end <= start;
  return (
    <Card title="Calling preferences" description={`Times are in ${data.limits.timezone}.`}>
      <fieldset className="mb-4">
        <legend className="mb-2 text-sm font-medium text-zinc-200">Days</legend>
        <div className="flex flex-wrap gap-2">
          {DAYS.map(([value, label]) => {
            const on = days.includes(value);
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                onClick={() => setDays(on ? days.filter((d) => d !== value) : [...days, value])}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  on ? "bg-[#1d4ed8] text-white" : "bg-[#24262b] text-zinc-400 hover:text-white"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </fieldset>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <Field label="From">
          <select
            value={start}
            onChange={(e) => setStart(Number(e.target.value))}
            className={inputClass}
          >
            {HOURS.slice(0, 24).map((h) => (
              <option key={h} value={h}>
                {hour(h)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Until">
          <select
            value={end}
            onChange={(e) => setEnd(Number(e.target.value))}
            className={inputClass}
          >
            {HOURS.slice(1).map((h) => (
              <option key={h} value={h}>
                {hour(h)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="At once" hint={`Max ${data.limits.max_concurrent_calls}`}>
          <select
            value={concurrent}
            onChange={(e) => setConcurrent(Number(e.target.value))}
            className={inputClass}
          >
            {Array.from({ length: data.limits.max_concurrent_calls }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n} call{n === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {end <= start && <p className="mb-3 text-xs text-red-300">“Until” must be after “From”.</p>}
      {days.length === 0 && <p className="mb-3 text-xs text-red-300">Pick at least one day.</p>}
      <Button
        disabled={!dirty || invalid || busy}
        onClick={() =>
          save(
            {
              calling: { days, start_hour: start, end_hour: end },
              max_concurrent_calls: concurrent,
            },
            "Calling preferences saved.",
          )
        }
      >
        {busy ? "Saving…" : "Save"}
      </Button>
    </Card>
  );
}

function IntroCard({ data, onSaved }: { data: SettingsPage; onSaved: (d: SettingsPage) => void }) {
  const { busy, save } = useSave(onSaved);
  const g = data.general;
  const [org, setOrg] = useState(g.organization_name ?? "");
  const [template, setTemplate] = useState(g.agent_introduction ?? "");
  const dirty = org !== (g.organization_name ?? "") || template !== (g.agent_introduction ?? "");
  const preview = template.trim()
    ? previewIntroduction(template, data, org)
    : data.introduction.built_in
      ? data.introduction.text
      : "(the built-in introduction)";
  return (
    <Card
      title="Organization and introduction"
      description="What the AI says right after the candidate confirms who they are."
    >
      <div className="space-y-4">
        <Field
          label="Organization name"
          hint="Used as {organization}; defaults to the job's company."
        >
          <input
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            className={inputClass}
            maxLength={200}
          />
        </Field>
        <Field
          label="Agent introduction"
          hint={
            <>
              Leave empty for the built-in line. Can use {"{first_name}"}, {"{company}"},{" "}
              {"{job_title}"}, {"{organization}"}. Must say it&apos;s an AI and end with a question.
            </>
          }
        >
          <textarea
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            rows={3}
            maxLength={500}
            placeholder="Hi {first_name}, I'm an AI recruitment assistant calling on behalf of {company}…"
            className={inputClass}
          />
        </Field>
        <div className="rounded-2xl bg-[#202226] p-4">
          <div className="text-xs text-zinc-500">
            Preview · to {data.introduction.sample_first_name}, for the{" "}
            {data.introduction.job_title} job
          </div>
          <p className="mt-1 text-sm text-zinc-200">“{preview}”</p>
        </div>
        <div className="flex gap-2">
          <Button
            disabled={!dirty || busy}
            onClick={() =>
              save(
                { organization_name: org || null, agent_introduction: template.trim() || null },
                "Introduction saved.",
              )
            }
          >
            {busy ? "Saving…" : "Save"}
          </Button>
          {g.agent_introduction && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={async () => {
                if (
                  await save({ agent_introduction: null }, "Back to the built-in introduction.")
                ) {
                  setTemplate("");
                }
              }}
            >
              Use built-in
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function RetryCard({ data, onSaved }: { data: SettingsPage; onSaved: (d: SettingsPage) => void }) {
  const { busy, save } = useSave(onSaved);
  const r = data.general.retry;
  const [attempts, setAttempts] = useState(r.max_attempts);
  const [interval, setIntervalDays] = useState(r.interval_days);
  const dirty = attempts !== r.max_attempts || interval !== r.interval_days;
  return (
    <Card
      title="Retries"
      description="For unanswered calls. Automatic retries arrive in the next release; the values are kept."
    >
      <div className="mb-4 grid grid-cols-2 gap-3">
        <Field label="Attempts per candidate">
          <select
            value={attempts}
            onChange={(e) => setAttempts(Number(e.target.value))}
            className={inputClass}
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Days between attempts">
          <select
            value={interval}
            onChange={(e) => setIntervalDays(Number(e.target.value))}
            className={inputClass}
          >
            {[2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n} days
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Button
        disabled={!dirty || busy}
        onClick={() =>
          save({ retry: { max_attempts: attempts, interval_days: interval } }, "Retries saved.")
        }
      >
        {busy ? "Saving…" : "Save"}
      </Button>
    </Card>
  );
}
