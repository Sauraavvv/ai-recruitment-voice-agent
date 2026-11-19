"use client";

import { useState } from "react";

import { ErrorState, Skeleton } from "@/components/states";
import { Button, Card } from "@/components/ui";
import { timeAgo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { getProviderStatus } from "@/services/settings";
import type { ProviderStatus } from "@/types";

function state(p: ProviderStatus): { label: string; tone: string; dot: string } {
  if (!p.configured) return { label: "Not set up", tone: "text-zinc-400", dot: "bg-zinc-600" };
  if (p.reachable) return { label: "Connected", tone: "text-[#5fd35f]", dot: "bg-[#0ca30c]" };
  return { label: "Problem", tone: "text-red-300", dot: "bg-red-400" };
}

/** OpenAI, Deepgram, Exotel and the voice: configured, reachable, message. No secrets. */
export function ProviderCards() {
  const [refresh, setRefresh] = useState(0);
  const status = useLoad(`provider-status:${refresh}`, () => getProviderStatus(refresh > 0));
  return (
    <Card
      title="Connections"
      description="Checked at most once a minute. Keys are never shown here."
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
          {status.data.providers.map((p) => {
            const s = state(p);
            return (
              <li key={p.name} className="flex items-start gap-3 py-3 text-sm">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${s.dot}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-white">{p.label}</div>
                  {p.message && <div className="text-xs text-zinc-400">{p.message}</div>}
                  {p.detail && <div className="text-xs text-zinc-500">{p.detail}</div>}
                </div>
                <div className="shrink-0 text-right">
                  <div className={`text-xs font-medium ${s.tone}`}>{s.label}</div>
                  <div className="text-[11px] text-zinc-500">{timeAgo(p.last_checked)}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
