"use client";

import { type FormEvent, type ReactNode, useMemo, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { KpiBar } from "@/components/kpi-bar";
import { ErrorState } from "@/components/states";
import { useToast } from "@/components/toast";
import { Alert, Button, PageHeader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";
import { addTeamMember, listTeam, updateTeamMember } from "@/services/team";
import type { TeamMember, TeamMemberUpdate } from "@/types";

import { Pills, Row, Section, line } from "../clients/form-layout";

const MIN_PASSWORD = 10;
type Role = TeamMember["role"];
const ROLE_LABELS: Record<Role, string> = { super_admin: "Super admin", recruiter: "Recruiter" };
const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as Role[]).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}));

/** 14 characters without look-alikes (0/O, 1/l/I), easy to read out or type. */
function generatePassword() {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const values = crypto.getRandomValues(new Uint32Array(14));
  return Array.from(values, (v) => chars[v % chars.length]).join("");
}

type Shared = { name: string; email: string; password: string };

function RoleBadge({ role }: { role: Role }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase ring-1 ${
        role === "super_admin"
          ? "bg-amber-400/10 text-amber-300 ring-amber-400/20"
          : "bg-white/5 text-zinc-400 ring-white/10"
      }`}
    >
      {ROLE_LABELS[role]}
    </span>
  );
}

export function AccountsView() {
  const { data: user } = useLoad("me", me);
  const isSuperAdmin = user?.role === "super_admin";
  const team = useLoad(isSuperAdmin ? "team" : null, listTeam);
  const [adding, setAdding] = useState(false);
  // Login details to hand over, shown once after an account is added or a password is set
  const [shared, setShared] = useState<Shared | null>(null);

  const counts = useMemo(() => {
    const all = team.data ?? [];
    return {
      total: all.length,
      admins: all.filter((m) => m.role === "super_admin").length,
      recruiters: all.filter((m) => m.role === "recruiter").length,
      off: all.filter((m) => !m.is_active).length,
    };
  }, [team.data]);

  if (user && !isSuperAdmin) {
    return (
      <>
        <PageHeader title="Accounts" />
        <Alert kind="info">Only a super admin can add and manage accounts.</Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Accounts"
        subtitle={user ? `Logins for your team at ${user.organization.name}.` : undefined}
      >
        {!adding && <Button onClick={() => setAdding(true)}>+ Add account</Button>}
      </PageHeader>

      <div className="space-y-6">
        <KpiBar
          items={[
            { label: "Team members", value: counts.total },
            { label: "Super admins", value: counts.admins, dot: "bg-amber-400" },
            { label: "Recruiters", value: counts.recruiters, dot: "bg-zinc-400" },
            { label: "Deactivated", value: counts.off },
          ]}
        />

        {shared && <SharedLogin shared={shared} onDone={() => setShared(null)} />}

        {adding && (
          <AddAccount
            onCancel={() => setAdding(false)}
            onAdded={(member, password) => {
              setShared({ name: member.name, email: member.email, password });
              setAdding(false);
              team.reload();
            }}
          />
        )}

        <section>
          <div className="mb-3 flex items-center gap-4">
            <h2 className="font-display text-base font-semibold text-white">
              Team
              <span className="ml-2 rounded-full bg-white/5 px-2 py-0.5 text-xs font-normal text-zinc-400">
                {counts.total}
              </span>
            </h2>
            <span className="h-px flex-1 bg-gradient-to-r from-white/10 to-transparent" />
          </div>

          {team.error ? (
            <ErrorState error={team.error} onRetry={team.reload} />
          ) : !team.data ? (
            <div className="space-y-2" role="status" aria-label="Loading">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="h-[72px] animate-pulse rounded-2xl bg-[#18191c]" />
              ))}
            </div>
          ) : (
            <TeamList
              members={team.data}
              selfId={user?.id}
              onChanged={team.reload}
              onPasswordSet={(member, password) =>
                setShared({ name: member.name, email: member.email, password })
              }
            />
          )}
        </section>
      </div>
    </>
  );
}

/** The login details to hand over, once. */
function SharedLogin({ shared, onDone }: { shared: Shared; onDone: () => void }) {
  const notify = useToast();
  return (
    <div className="rounded-3xl bg-[#18191c] p-5 ring-1 ring-green-400/20">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-white">
            <span className="h-2 w-2 rounded-full bg-green-400" />
            Share these login details with {shared.name}
          </div>
          <p className="mt-1 text-xs text-zinc-500">The password isn&apos;t shown again.</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              void navigator.clipboard
                ?.writeText(
                  `Login: ${window.location.origin}/login\nEmail: ${shared.email}\nPassword: ${shared.password}`,
                )
                .then(() => notify("success", "Login details copied"));
            }}
          >
            Copy
          </Button>
          <Button variant="secondary" onClick={onDone}>
            Done
          </Button>
        </div>
      </div>
      <dl className="mt-4 grid gap-3 rounded-2xl bg-black/30 p-4 font-mono text-sm sm:grid-cols-2">
        <div>
          <dt className="font-sans text-[11px] text-zinc-500">Email</dt>
          <dd className="truncate text-zinc-200">{shared.email}</dd>
        </div>
        <div>
          <dt className="font-sans text-[11px] text-zinc-500">Password</dt>
          <dd className="text-zinc-200">{shared.password}</dd>
        </div>
      </dl>
    </div>
  );
}

function AddAccount({
  onAdded,
  onCancel,
}: {
  onAdded: (member: TeamMember, password: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState(generatePassword);
  const [role, setRole] = useState<Role>("recruiter");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onAdded(await addTeamMember({ name, email, password, role }), password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6 rounded-3xl bg-[#18191c] p-6 sm:p-8">
      {error && <Alert>{error}</Alert>}
      <Section n="+" title="New account" note="share the login with them after adding">
        <Row label="Name" required>
          <input
            required
            autoFocus
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ravi Kumar"
            className={line}
          />
        </Row>
        <Row label="Email" required>
          <input
            required
            type="email"
            maxLength={320}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="ravi@company.com"
            autoComplete="off"
            className={line}
          />
        </Row>
        <Row label="Password" required as="div" hint={`At least ${MIN_PASSWORD} characters.`}>
          <div className="flex items-center gap-2">
            <input
              required
              aria-label="Password"
              minLength={MIN_PASSWORD}
              maxLength={200}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              className={`${line} font-mono`}
            />
            <Button
              variant="secondary"
              onClick={() => setPassword(generatePassword())}
              title="Make a new password"
            >
              New
            </Button>
          </div>
        </Row>
        <Row label="Role" as="div">
          <Pills label="Role" options={ROLE_OPTIONS} value={role} onChange={setRole} />
        </Row>
      </Section>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add account"}
        </Button>
      </div>
    </form>
  );
}

type Pending =
  { kind: "deactivate"; member: TeamMember } | { kind: "password"; member: TeamMember };

function TeamList({
  members,
  selfId,
  onChanged,
  onPasswordSet,
}: {
  members: TeamMember[];
  selfId?: string;
  onChanged: () => void;
  onPasswordSet: (member: TeamMember, password: string) => void;
}) {
  const notify = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [newPassword, setNewPassword] = useState("");

  async function update(member: TeamMember, body: TeamMemberUpdate, done: string) {
    setBusyId(member.id);
    try {
      await updateTeamMember(member.id, body);
      notify("success", done);
      onChanged();
      return true;
    } catch (err) {
      notify("error", errorMessage(err));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function confirmPending() {
    if (!pending) return;
    const { member } = pending;
    if (pending.kind === "deactivate") {
      await update(member, { is_active: false }, `${member.name} can no longer log in`);
    } else if (
      await update(member, { password: newPassword }, `New password set for ${member.name}`)
    ) {
      onPasswordSet(member, newPassword);
    }
    setPending(null);
  }

  // You first, then active people, then deactivated ones
  const sorted = [...members].sort(
    (a, b) =>
      Number(b.id === selfId) - Number(a.id === selfId) ||
      Number(b.is_active) - Number(a.is_active),
  );

  return (
    <>
      <ul className="space-y-2">
        {sorted.map((m) => {
          const self = m.id === selfId;
          const busy = busyId === m.id;
          return (
            <li
              key={m.id}
              className={`flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl bg-[#18191c] px-5 py-4 ring-1 ring-white/5 ${
                m.is_active ? "" : "opacity-60"
              }`}
            >
              <div className="min-w-0 flex-[2_1_14rem]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-white">{m.name}</span>
                  {self && <span className="text-xs text-zinc-500">(you)</span>}
                  <RoleBadge role={m.role} />
                </div>
                <div className="truncate text-sm text-zinc-500">{m.email}</div>
              </div>

              <div className="w-32 text-xs">
                <div className="text-zinc-500">Status</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-zinc-200">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${m.is_active ? "bg-green-400" : "bg-zinc-600"}`}
                  />
                  {m.is_active ? "Active" : "Deactivated"}
                </div>
              </div>

              <div className="w-32 text-xs">
                <div className="text-zinc-500">Last login</div>
                <div className="mt-0.5 text-zinc-200">
                  {m.last_login_at ? timeAgo(m.last_login_at) : "Never"}
                </div>
              </div>

              <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                {!self && m.is_active && (
                  <select
                    aria-label={`Role of ${m.name}`}
                    value={m.role}
                    disabled={busy}
                    onChange={(e) => {
                      const role = e.target.value as Role;
                      void update(m, { role }, `${m.name} is now ${ROLE_LABELS[role]}`);
                    }}
                    className="rounded-lg border border-white/10 bg-transparent px-2.5 py-1.5 text-xs text-zinc-200 outline-none hover:border-white/25 focus:border-white/40 [&>option]:bg-[#18191c]"
                  >
                    {ROLE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                )}
                <SmallButton
                  disabled={busy}
                  onClick={() => {
                    setNewPassword(generatePassword());
                    setPending({ kind: "password", member: m });
                  }}
                >
                  Set password
                </SmallButton>
                {!self &&
                  (m.is_active ? (
                    <SmallButton
                      danger
                      disabled={busy}
                      onClick={() => setPending({ kind: "deactivate", member: m })}
                    >
                      Deactivate
                    </SmallButton>
                  ) : (
                    <SmallButton
                      disabled={busy}
                      onClick={() =>
                        void update(m, { is_active: true }, `${m.name} can log in again`)
                      }
                    >
                      Activate
                    </SmallButton>
                  ))}
              </div>
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={pending?.kind === "deactivate"}
        title={`Deactivate ${pending?.member.name ?? ""}?`}
        confirmLabel="Deactivate"
        danger
        busy={busyId !== null}
        onConfirm={() => void confirmPending()}
        onClose={() => setPending(null)}
      >
        They&apos;re logged out and can&apos;t log in until you activate the account again. Their
        work stays.
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.kind === "password"}
        title={`New password for ${pending?.member.name ?? ""}`}
        confirmLabel="Set password"
        busy={busyId !== null}
        confirmDisabled={newPassword.length < MIN_PASSWORD}
        onConfirm={() => void confirmPending()}
        onClose={() => setPending(null)}
      >
        <div className="flex items-center gap-2">
          <input
            aria-label="New password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={MIN_PASSWORD}
            maxLength={200}
            autoComplete="new-password"
            className={`${line} font-mono`}
          />
          <Button variant="secondary" onClick={() => setNewPassword(generatePassword())}>
            New
          </Button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">At least {MIN_PASSWORD} characters.</p>
      </ConfirmDialog>
    </>
  );
}

function SmallButton({
  danger,
  disabled,
  onClick,
  children,
}: {
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-lg border px-2.5 py-1.5 text-xs transition disabled:cursor-not-allowed disabled:opacity-40 ${
        danger
          ? "border-red-400/20 text-red-300 hover:bg-red-500/10"
          : "border-white/10 text-zinc-200 hover:border-white/25 hover:bg-white/5"
      }`}
    >
      {children}
    </button>
  );
}
