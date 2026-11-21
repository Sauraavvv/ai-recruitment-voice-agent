"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, Card } from "@/components/ui";
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

  const action = (
    <Button variant="secondary" onClick={check} disabled={state.kind === "loading"}>
      Check now
    </Button>
  );

  return (
    <Card
      title="Services"
      description="Database, queue and background worker. Refreshes every 10 seconds."
      action={action}
    >
      {state.kind === "loading" ? (
        <p className="text-sm text-zinc-500">Checking services…</p>
      ) : state.kind === "unreachable" ? (
        <div className="space-y-3">
          <div
            role="alert"
            className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200"
          >
            <p className="font-medium">Backend unreachable</p>
            <p>{state.message}</p>
          </div>
          <CheckedAt date={state.checkedAt} />
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm">
            Overall:{" "}
            <StatusText ok={state.readiness.status === "ok"}>
              {state.readiness.status === "ok" ? "All systems ready" : "Degraded"}
            </StatusText>
          </p>
          <ul className="divide-y divide-white/5">
            {Object.entries(state.readiness.components).map(([name, status]) => (
              <li key={name} className="flex items-start gap-3 py-3 text-sm">
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                    status === "ok" ? "bg-[#0ca30c]" : "bg-red-400"
                  }`}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-white">{LABELS[name] ?? name}</div>
                  {state.readiness.errors?.[name] && (
                    <div className="text-xs text-zinc-400">{state.readiness.errors[name]}</div>
                  )}
                </div>
                <StatusText ok={status === "ok"}>{status === "ok" ? "OK" : "Error"}</StatusText>
              </li>
            ))}
          </ul>
          <CheckedAt date={state.checkedAt} />
        </div>
      )}
    </Card>
  );
}

function StatusText({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={`text-xs font-medium ${ok ? "text-[#5fd35f]" : "text-red-300"}`}>
      {children}
    </span>
  );
}

function CheckedAt({ date }: { date: Date }) {
  return <p className="text-xs text-zinc-500">Last checked {date.toLocaleTimeString()}</p>;
}
