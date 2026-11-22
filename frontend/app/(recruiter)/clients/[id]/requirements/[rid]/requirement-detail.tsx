"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorState, Skeleton } from "@/components/states";
import { BackLink, PageHeader, buttonClass } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { getClient } from "@/services/clients";
import { getRequirement } from "@/services/requirements";

import { REQUIREMENT_STATUS, RequirementCard, WORK_MODES } from "../requirement-form";
import { ScreeningCard } from "./screening-card";
import { TelephonicCard } from "./telephonic-card";

/** Where a requirement's pages live: under its client, or under Jobs (so the sidebar keeps
 * the section the user came from). */
export type Section = "client" | "jobs";

export function requirementPath(section: Section, clientId: string, rid: string) {
  return section === "jobs" ? `/jobs/${rid}` : `/clients/${clientId}/requirements/${rid}`;
}

/** The route under a client: /clients/[id]/requirements/[rid] */
export function RequirementDetail() {
  const { rid } = useParams<{ rid: string }>();
  return <RequirementView requirementId={rid} section="client" />;
}

export function RequirementView({
  requirementId: rid,
  section,
}: {
  requirementId: string;
  section: Section;
}) {
  const { data: req, error, reload } = useLoad(`requirement:${rid}`, () => getRequirement(rid));
  const clientId = req?.client_id;
  const { data: client } = useLoad(clientId ? `client:${clientId}` : null, () =>
    getClient(clientId ?? ""),
  );

  if (error && !req) return <ErrorState error={error} onRetry={reload} />;
  if (!req) return <Skeleton className="h-96 rounded-3xl" />;

  const status = REQUIREMENT_STATUS[req.status];
  const facts = [
    client?.name,
    req.location,
    req.work_mode ? WORK_MODES[req.work_mode] : "",
    `${req.openings} opening${req.openings === 1 ? "" : "s"}`,
  ].filter(Boolean);

  return (
    <>
      {section === "jobs" ? (
        <BackLink href="/jobs">All jobs</BackLink>
      ) : (
        <BackLink href={`/clients/${req.client_id}`}>{client?.name ?? "Back to client"}</BackLink>
      )}
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {req.title}
            <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${status.tone}`}>
              {status.label}
            </span>
          </span>
        }
        subtitle={facts.join(" · ")}
      >
        <Link
          href={`${requirementPath(section, req.client_id, rid)}/edit`}
          className={buttonClass("secondary")}
        >
          Edit job details
        </Link>
      </PageHeader>

      <div className="space-y-6">
        {/* Both stretch to the taller one, so their bottoms line up */}
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0">
            <ScreeningCard
              requirementId={req.id}
              version={req.updated_at}
              editHref={`${requirementPath(section, req.client_id, rid)}/edit`}
            />
          </div>
          <div className="[&>div]:h-full">
            <RequirementCard requirement={req} clientName={client?.name} />
          </div>
        </div>

        <TelephonicCard
          requirementId={req.id}
          editHref={`${requirementPath(section, req.client_id, rid)}/edit`}
        />
      </div>
    </>
  );
}
