"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert, Button, Card, buttonClass, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { SCREENING_STATUS_LABELS, formatDate, yesNo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { listCandidates } from "@/services/candidates";

const PAGE_SIZE = 25;

// Status pills: always a label, colour only supports it
const STATUS_TONE: Record<string, string> = {
  completed: "bg-[#0ca30c]/15 text-[#5fd35f]",
  partially_completed: "bg-amber-500/15 text-amber-300",
  in_progress: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  callback_requested: "bg-[#1d4ed8]/20 text-[#93b4ff]",
  declined: "bg-red-500/15 text-red-300",
  opted_out: "bg-red-500/15 text-red-300",
  wrong_person: "bg-red-500/15 text-red-300",
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

export function CandidateList() {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [interested, setInterested] = useState("");
  const [page, setPage] = useState(1);

  // Debounce typing so each keystroke doesn't hit the API.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  const query = { q, screening_status: status, interested, page, page_size: PAGE_SIZE };
  const { data, error, loading } = useLoad(JSON.stringify(query), () => listCandidates(query));
  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Candidates"
        subtitle="Everyone added by upload or by hand, with their screening results."
      >
        <Link href="/candidates/new" className={buttonClass("secondary")}>
          Add candidate
        </Link>
        <Link href="/candidates/upload" className={buttonClass("primary")}>
          Upload file
        </Link>
      </PageHeader>

      <Card>
        <div className="mb-5 flex flex-wrap gap-3">
          <input
            type="search"
            placeholder="Search name, phone or email"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputClass} max-w-xs`}
            aria-label="Search candidates"
          />
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className={`${inputClass} max-w-48`}
            aria-label="Screening status"
          >
            <option value="">All screening statuses</option>
            {Object.entries(SCREENING_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <select
            value={interested}
            onChange={(e) => {
              setInterested(e.target.value);
              setPage(1);
            }}
            className={`${inputClass} max-w-40`}
            aria-label="Interest"
          >
            <option value="">Any interest</option>
            <option value="true">Interested</option>
            <option value="false">Not interested</option>
          </select>
          {loading && <span className="self-center text-sm text-zinc-500">Loading…</span>}
        </div>

        {error && <Alert>{errorMessage(error)}</Alert>}

        {data && data.items.length === 0 && (
          <Muted>
            {q || status || interested
              ? "No candidates match these filters."
              : "No candidates yet. Upload a file or add one manually."}
          </Muted>
        )}

        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs text-zinc-500 uppercase">
                <tr>
                  <th className="py-3 pr-4 font-medium">Name</th>
                  <th className="py-3 pr-4 font-medium">Phone</th>
                  <th className="py-3 pr-4 font-medium">Applied role</th>
                  <th className="py-3 pr-4 font-medium">Experience</th>
                  <th className="py-3 pr-4 font-medium">Screening</th>
                  <th className="py-3 pr-4 font-medium">Interested</th>
                  <th className="py-3 pr-4 font-medium">Added</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-zinc-300">
                {data.items.map((c) => (
                  <tr key={c.id} className="transition hover:bg-white/[0.03]">
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-3">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-medium text-white">
                          {initials(c.name)}
                        </span>
                        <span className="min-w-0">
                          <Link
                            href={`/candidates/${c.id}`}
                            className="block truncate font-medium text-white hover:underline"
                          >
                            {c.name}
                          </Link>
                          {c.email && (
                            <span className="block truncate text-xs text-zinc-500">{c.email}</span>
                          )}
                        </span>
                        {c.opted_out && (
                          <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-300">
                            Opted out
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap tabular-nums">{c.phone}</td>
                    <td className="py-3 pr-4">{c.applied_role}</td>
                    <td className="py-3 pr-4 whitespace-nowrap">
                      {c.total_experience == null ? "—" : `${c.total_experience} yrs`}
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className={`inline-block rounded-full px-2.5 py-1 text-xs whitespace-nowrap ${
                          STATUS_TONE[c.screening_status] ?? "bg-white/5 text-zinc-400"
                        }`}
                      >
                        {SCREENING_STATUS_LABELS[c.screening_status]}
                      </span>
                    </td>
                    <td className="py-3 pr-4">{yesNo(c.interested)}</td>
                    <td className="py-3 pr-4 whitespace-nowrap text-zinc-500">
                      {formatDate(c.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && total > 0 && (
          <div className="mt-5 flex items-center gap-3 text-sm text-zinc-400">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <span>
              Page {page} of {pages} · {total} candidate{total === 1 ? "" : "s"}
            </span>
            <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
