"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";

type Readiness = {
  status: "ok" | "error";
  components: Record<string, "ok" | "error">;
  errors?: Record<string, string>;
};

type State =
  | { kind: "loading" }
  | { kind: "loaded"; readiness: Readiness; checkedAt: Date }
  | { kind: "unreachable"; message: string; checkedAt: Date };

const REFRESH_MS = 10_000;

const LABELS: Record<string, string> = {
  database: "PostgreSQL",
  redis: "Redis",
  worker: "Background worker",
};

export function SystemStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const check = useCallback(async () => {
    try {
      // 503 still carries a valid body describing which component failed.
      const { data } = await apiFetch<Readiness>("/health/ready", {
        cache: "no-store",
        acceptStatuses: [503],
      });
      setState({ kind: "loaded", readiness: data, checkedAt: new Date() });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Unknown error";
      setState({ kind: "unreachable", message, checkedAt: new Date() });
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(check, 0);
    const timer = setInterval(check, REFRESH_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [check]);

  if (state.kind === "loading") {
    return <p className="text-sm text-zinc-500">Checking services…</p>;
  }

  if (state.kind === "unreachable") {
    return (
      <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-red-900">
        <p className="font-medium">Backend unreachable</p>
        <p className="text-sm">{state.message}</p>
        <CheckedAt date={state.checkedAt} onRetry={check} />
      </div>
    );
  }

  const { readiness } = state;
  return (
    <div className="space-y-4">
      <p className="text-lg font-medium">
        Overall:{" "}
        <StatusText ok={readiness.status === "ok"}>
          {readiness.status === "ok" ? "All systems ready" : "Degraded"}
        </StatusText>
      </p>
      <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {Object.entries(readiness.components).map(([name, status]) => (
          <li key={name} className="flex items-center justify-between px-4 py-3">
            <span>{LABELS[name] ?? name}</span>
            <span className="text-right">
              <StatusText ok={status === "ok"}>{status === "ok" ? "OK" : "Error"}</StatusText>
              {readiness.errors?.[name] && (
                <span className="block text-xs text-zinc-500">{readiness.errors[name]}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
      <CheckedAt date={state.checkedAt} onRetry={check} />
    </div>
  );
}

function StatusText({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={
        ok
          ? "font-medium text-green-700 dark:text-green-400"
          : "font-medium text-red-700 dark:text-red-400"
      }
    >
      {ok ? "● " : "✕ "}
      {children}
    </span>
  );
}

function CheckedAt({ date, onRetry }: { date: Date; onRetry: () => void }) {
  return (
    <p className="text-xs text-zinc-500">
      Last checked {date.toLocaleTimeString()} ·{" "}
      <button type="button" onClick={onRetry} className="underline">
        Check now
      </button>
    </p>
  );
}
