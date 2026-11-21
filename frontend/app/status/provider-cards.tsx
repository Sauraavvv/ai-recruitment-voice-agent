"use client";

import { useState } from "react";

import { ErrorState, Skeleton } from "@/components/states";
import { Button, Card } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";

// GET /health/connections: public, generic names and a state only (see backend api/health.py)
type Connection = {
  name: string;
  label: string;
  state: "ok" | "problem" | "not_set_up";
  last_checked: string;
};

const STATES: Record<Connection["state"], { label: string; tone: string; dot: string }> = {
  ok: { label: "Connected", tone: "text-[#5fd35f]", dot: "bg-[#0ca30c]" },
  problem: { label: "Problem", tone: "text-red-300", dot: "bg-red-400" },
  not_set_up: { label: "Not set up", tone: "text-zinc-400", dot: "bg-zinc-600" },
};

async function getConnections() {
  return (await apiFetch<Connection[]>("/health/connections", { cache: "no-store" })).data;
}

/** The services calls depend on. No login needed: the status of the whole site. */
export function ProviderCards() {
  const [refresh, setRefresh] = useState(0);
  const status = useLoad(`connections:${refresh}`, getConnections);
  return (
    <Card
      title="Connections"
      description="The services calls depend on. Checked at most once a minute."
      action={
        <Button
          variant="secondary"
          disabled={status.loading}
          onClick={() => setRefresh((n) => n + 1)}
        >
          {status.loading && status.data ? "Checking…" : "Check again"}
        </Button>
      }
    >
      {status.error && !status.data ? (
        <ErrorState error={status.error} onRetry={status.reload} />
      ) : !status.data ? (
        <Skeleton className="h-48" />
      ) : (
        <ul className="divide-y divide-white/5">
          {status.data.map((c) => {
            const s = STATES[c.state];
            return (
              <li key={c.name} className="flex items-start gap-3 py-3 text-sm">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${s.dot}`} aria-hidden />
                <div className="min-w-0 flex-1 font-medium text-white">{c.label}</div>
                <div className="shrink-0 text-right">
                  <div className={`text-xs font-medium ${s.tone}`}>{s.label}</div>
                  <div className="text-[11px] text-zinc-500">{timeAgo(c.last_checked)}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
