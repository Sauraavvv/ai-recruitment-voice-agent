"use client";

import { inputClass } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { listClients } from "@/services/clients";

/** "All clients" or one client: narrows a list to that client's jobs. Not shown when the
 * account sees no clients (recruiters don't, for now). */
export function ClientFilter({
  value,
  onChange,
  className = "max-w-56",
}: {
  value: string;
  onChange: (clientId: string) => void;
  className?: string;
}) {
  const { data } = useLoad("client-filter", () => listClients());
  if (!data || data.length === 0) return null;
  const clients = [...data].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${inputClass} ${className}`}
      aria-label="Client"
    >
      <option value="">All clients</option>
      {clients.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
          {c.status === "on_hold" ? " (on hold)" : c.status === "closed" ? " (closed)" : ""}
        </option>
      ))}
    </select>
  );
}
