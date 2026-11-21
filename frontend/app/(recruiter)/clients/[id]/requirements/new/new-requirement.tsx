"use client";

import { useParams, useRouter } from "next/navigation";

import { BackLink, PageHeader } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { getClient } from "@/services/clients";
import { createRequirement } from "@/services/requirements";

import { RequirementForm } from "../requirement-form";

export function NewRequirement() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: client } = useLoad(`client:${id}`, () => getClient(id));
  return (
    <>
      <BackLink href={`/clients/${id}`}>{client?.name ?? "Back to client"}</BackLink>
      <PageHeader
        title="Add requirement"
        subtitle={client ? `An opening at ${client.name}.` : undefined}
      />
      <RequirementForm
        clientName={client?.name}
        submitLabel="Add requirement →"
        onSave={async (body) => {
          const requirement = await createRequirement(id, body);
          router.push(`/clients/${id}/requirements/${requirement.id}`);
        }}
      />
    </>
  );
}
