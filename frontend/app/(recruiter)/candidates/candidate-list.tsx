"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert, Button, buttonClass, Muted, PageHeader, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { SCREENING_STATUS_LABELS, formatDate, yesNo } from "@/lib/labels";
import { useLoad } from "@/lib/use-load";
import { listCandidates } from "@/services/candidates";

const PAGE_SIZE = 25;

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
      <PageHeader title="Candidates">
        <Link href="/candidates/new" className={buttonClass("secondary")}>
          Add candidate
        </Link>
        <Link href="/candidates/upload" className={buttonClass("primary")}>
          Upload file
        </Link>
      </PageHeader>

      <div className="mb-4 flex flex-wrap gap-3">
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
            <thead className="border-b border-zinc-200 text-xs text-zinc-500 uppercase dark:border-zinc-800">
              <tr>
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Phone</th>
                <th className="py-2 pr-4">Applied role</th>
                <th className="py-2 pr-4">Experience</th>
                <th className="py-2 pr-4">Screening</th>
                <th className="py-2 pr-4">Interested</th>
                <th className="py-2 pr-4">Added</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="border-b border-zinc-100 dark:border-zinc-900">
                  <td className="py-2 pr-4">
                    <Link href={`/candidates/${c.id}`} className="font-medium underline">
                      {c.name}
                    </Link>
                    {c.opted_out && <span className="ml-2 text-xs text-red-600">opted out</span>}
                  </td>
                  <td className="py-2 pr-4 font-mono">{c.phone}</td>
                  <td className="py-2 pr-4">{c.applied_role}</td>
                  <td className="py-2 pr-4">
                    {c.total_experience == null ? "—" : `${c.total_experience} yrs`}
                  </td>
                  <td className="py-2 pr-4">{SCREENING_STATUS_LABELS[c.screening_status]}</td>
                  <td className="py-2 pr-4">{yesNo(c.interested)}</td>
                  <td className="py-2 pr-4 whitespace-nowrap">{formatDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && total > 0 && (
        <div className="mt-4 flex items-center gap-3 text-sm">
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
    </>
  );
}
