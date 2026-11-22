"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorState, Skeleton } from "@/components/states";
import { Alert, BackLink, PageHeader } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { listClients } from "@/services/clients";
import { createRequirement } from "@/services/requirements";

import { Row, line } from "../../clients/form-layout";
import { RequirementForm } from "../../clients/[id]/requirements/requirement-form";

const STATUS_NOTE = { active: "", on_hold: " (on hold)", closed: " (closed)" } as const;

/**
 * Adding a job from Jobs (recruiters and super admins): the same form as adding a requirement
 * under a client, with the client chosen first from the company's clients. `?client=<id>`
 * picks one in advance.
 */
export function NewJob() {
  const router = useRouter();
  const params = useSearchParams();
  const { data, error, reload } = useLoad("client-filter", () => listClients());
  const [chosen, setChosen] = useState(params.get("client") ?? "");

  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Skeleton className="h-96 rounded-3xl" />;

  const clients = [...data].sort((a, b) => a.name.localeCompare(b.name));
  const clientId = clients.some((c) => c.id === chosen) ? chosen : "";
  const client = clients.find((c) => c.id === clientId);

  return (
    <>
      <BackLink href="/jobs">All jobs</BackLink>
      <PageHeader
        title="Add job"
        subtitle={client ? `An opening at ${client.name}.` : "Choose the client it's for."}
      />
      {clients.length === 0 ? (
        <Alert kind="info">
          Your company has no clients yet. A super admin adds clients; then you can add jobs for
          them here.
        </Alert>
      ) : (
        <RequirementForm
          clientName={client?.name}
          clientField={
            <Row label="Client" required>
              <select
                required
                autoFocus
                value={clientId}
                onChange={(e) => setChosen(e.target.value)}
                className={`${line} cursor-pointer`}
              >
                <option value="" disabled>
                  Choose a client…
                </option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {STATUS_NOTE[c.status]}
                  </option>
                ))}
              </select>
            </Row>
          }
          submitLabel="Add job →"
          onSave={async (body) => {
            const job = await createRequirement(clientId, body);
            router.push(`/jobs/${job.id}`);
          }}
        />
      )}
    </>
  );
}
