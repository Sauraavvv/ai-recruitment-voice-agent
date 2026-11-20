"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, Skeleton } from "@/components/states";
import { useToast } from "@/components/toast";
import { Button, Card, Field, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { changeSheet, checkSheet, getSheetsStatus, syncAll } from "@/services/settings";
import type { SheetAccessCheck, SheetsStatus } from "@/types";

const STATES: Record<string, { label: string; tone: string }> = {
  ok: { label: "Connected", tone: "text-[#5fd35f]" },
  unknown: { label: "Connected, nothing synced yet", tone: "text-zinc-300" },
  degraded: { label: "Temporary failures, retrying", tone: "text-amber-300" },
  error: { label: "Needs fixing", tone: "text-red-300" },
  not_configured: { label: "Not set up", tone: "text-zinc-400" },
};

/** Google Sheets status and, for an admin, the sheet the candidates are copied to. */
export function SheetsCard() {
  const notify = useToast();
  const [refresh, setRefresh] = useState(0);
  const status = useLoad(`sheets-status:${refresh}`, () => getSheetsStatus(refresh > 0));
  const [busy, setBusy] = useState(false);
  const s = status.data;

  async function onSyncAll() {
    setBusy(true);
    try {
      const result = await syncAll();
      notify("success", `${result.queued_candidates} candidates queued for the sheet.`);
      status.reload();
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const state = s ? (STATES[s.state] ?? STATES.unknown) : null;
  return (
    <Card
      title="Google Sheets"
      description="A copy of every candidate, kept up to date. The database stays the source of truth."
      action={
        <Button
          variant="secondary"
          disabled={status.loading}
          onClick={() => setRefresh((n) => n + 1)}
        >
          Check again
        </Button>
      }
    >
      {status.error && !s ? (
        <ErrorState error={status.error} onRetry={status.reload} />
      ) : !s || !state ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="space-y-4">
          <div>
            <div className={`text-sm font-medium ${state.tone}`}>{state.label}</div>
            {s.message && <p className="mt-1 text-xs text-zinc-400">{s.message}</p>}
          </div>
          <dl className="divide-y divide-white/5 text-sm">
            <Row label="Sheet">
              {s.sheet_url ? (
                <a
                  href={s.sheet_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[#93b4ff] hover:underline"
                >
                  Open sheet · tab {s.tab}
                </a>
              ) : (
                "—"
              )}
            </Row>
            <Row label="Service account">
              {s.service_account_email ? (
                <span className="flex items-center justify-end gap-2">
                  <span className="truncate">{s.service_account_email}</span>
                  <button
                    type="button"
                    className="shrink-0 text-xs text-[#93b4ff] hover:underline"
                    onClick={() => {
                      void navigator.clipboard?.writeText(s.service_account_email ?? "");
                      notify("info", "Copied. Share the sheet with this address as Editor.");
                    }}
                  >
                    Copy
                  </button>
                </span>
              ) : (
                "—"
              )}
            </Row>
            <Row label="Last sync">{formatDate(s.last_success_at)}</Row>
            <Row label="Waiting / failed">
              <span className="tabular-nums">
                {s.pending_candidates} /{" "}
                <span className={s.failed_candidates ? "text-red-300" : ""}>
                  {s.failed_candidates}
                </span>
              </span>
            </Row>
          </dl>
          {(s.configured || (s.can_edit && s.key_configured)) && (
            <div className="flex flex-wrap items-start gap-2">
              {s.configured && (
                <Button variant="secondary" disabled={busy} onClick={onSyncAll}>
                  {busy ? "Queuing…" : "Sync all"}
                </Button>
              )}
              {s.can_edit && s.key_configured && (
                <ChangeSheet status={s} onChanged={() => setRefresh((n) => n + 1)} />
              )}
            </div>
          )}
          {!s.can_edit && (
            <p className="text-xs text-zinc-500">Only an admin can change the sheet.</p>
          )}
        </div>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
      <dt className="shrink-0 text-zinc-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-zinc-200">{children}</dd>
    </div>
  );
}

const HEADER_TEXT: Record<string, string> = {
  ok: "has HireCall's columns",
  empty: "is empty: the columns will be added",
  mismatch: "has other columns: use an empty sheet or tab",
  unknown: "couldn't be read",
};

/** Admin: paste a link → Check access → Save (then everyone is copied to the new sheet). */
function ChangeSheet({ status, onChanged }: { status: SheetsStatus; onChanged: () => void }) {
  const notify = useToast();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [tab, setTab] = useState("");
  const [check, setCheck] = useState<SheetAccessCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  async function onCheck() {
    setBusy(true);
    setCheck(null);
    try {
      setCheck(await checkSheet(link, tab));
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    setBusy(true);
    try {
      await changeSheet(link, tab);
      notify("success", "Sheet changed. Every candidate is being copied to it.");
      setOpen(false);
      setConfirm(false);
      setLink("");
      setCheck(null);
      onChanged();
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {status.sheet_id ? "Change sheet" : "Choose a sheet"}
      </Button>
    );
  }
  return (
    <div className="w-full space-y-3 rounded-2xl border border-white/10 p-4">
      <p className="text-xs text-zinc-400">
        Admin only. Share the new sheet with the service account as Editor first. The old sheet
        keeps its rows.
      </p>
      <Field label="Sheet link">
        <input
          value={link}
          onChange={(e) => {
            setLink(e.target.value);
            setCheck(null);
          }}
          placeholder="https://docs.google.com/spreadsheets/d/…"
          className={inputClass}
        />
      </Field>
      <Field label="Tab" hint={`Empty = ${status.tab}`}>
        <input
          value={tab}
          onChange={(e) => {
            setTab(e.target.value);
            setCheck(null);
          }}
          className={inputClass}
          maxLength={100}
        />
      </Field>
      {check && (
        <div
          role="status"
          className={`rounded-xl p-3 text-sm ${check.can_save ? "bg-green-500/10 text-green-200" : "bg-red-500/10 text-red-200"}`}
        >
          {check.reachable
            ? `Access ok; the tab ${HEADER_TEXT[check.header] ?? check.header}.`
            : (check.message ?? "The service account can't open this sheet.")}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={!link.trim() || busy} onClick={onCheck}>
          {busy && !confirm ? "Checking…" : "Check access"}
        </Button>
        <Button disabled={!check?.can_save || busy} onClick={() => setConfirm(true)}>
          Save
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Copy candidates to this sheet?"
        confirmLabel="Change sheet"
        busy={busy}
        onConfirm={onSave}
        onClose={() => setConfirm(false)}
      >
        From now on every candidate change goes to the new sheet, and all current candidates are
        copied there now. The old sheet is not changed or emptied.
      </ConfirmDialog>
    </div>
  );
}
