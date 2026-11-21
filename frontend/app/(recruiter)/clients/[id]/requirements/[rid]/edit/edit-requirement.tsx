"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorState, Skeleton } from "@/components/states";
import { useToast } from "@/components/toast";
import { BackLink, PageHeader, buttonClass } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { getClient } from "@/services/clients";
import { getRequirement, updateRequirement } from "@/services/requirements";

import { RequirementForm } from "../../requirement-form";
import { type Section, requirementPath } from "../requirement-detail";

/** The route under a client: /clients/[id]/requirements/[rid]/edit */
export function EditRequirement() {
  const { rid } = useParams<{ rid: string }>();
  return <EditRequirementView requirementId={rid} section="client" />;
}

export function EditRequirementView({
  requirementId: rid,
  section,
}: {
  requirementId: string;
  section: Section;
}) {
  const router = useRouter();
  const notify = useToast();
  const { data: req, error, reload } = useLoad(`requirement:${rid}`, () => getRequirement(rid));
  const clientId = req?.client_id;
  const { data: client } = useLoad(clientId ? `client:${clientId}` : null, () =>
    getClient(clientId ?? ""),
  );

  if (error && !req) return <ErrorState error={error} onRetry={reload} />;
  if (!req) return <Skeleton className="h-96 rounded-3xl" />;
  const back = requirementPath(section, req.client_id, rid);

  return (
    <>
      <BackLink href={back}>{req.title}</BackLink>
      <PageHeader title="Edit job details" subtitle={req.title}>
        <Link href={back} className={buttonClass("secondary")}>
          Cancel
        </Link>
      </PageHeader>
      <RequirementForm
        requirement={req}
        clientName={client?.name}
        submitLabel="Save changes"
        onSave={async (body) => {
          await updateRequirement(req.id, body);
          notify("success", "Job details saved");
          router.push(back);
        }}
      />
    </>
  );
}
