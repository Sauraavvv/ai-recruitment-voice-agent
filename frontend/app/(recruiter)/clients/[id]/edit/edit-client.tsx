"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorState, Skeleton } from "@/components/states";
import { useToast } from "@/components/toast";
import { Alert, BackLink, PageHeader, buttonClass } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";
import { getClient, updateClient } from "@/services/clients";

import { ClientEditor } from "../../client-editor";

export function EditClient() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const notify = useToast();
  const { data: user } = useLoad("me", me);
  const { data: client, error, reload } = useLoad(`client:${id}`, () => getClient(id));

  if (user && user.role !== "super_admin") {
    return (
      <>
        <PageHeader title="Edit client" />
        <Alert kind="info">Only a super admin can edit clients.</Alert>
      </>
    );
  }
  if (error && !client) return <ErrorState error={error} onRetry={reload} />;
  if (!client) return <Skeleton className="h-96 rounded-3xl" />;

  return (
    <>
      <BackLink href={`/clients/${client.id}`}>{client.name}</BackLink>
      <PageHeader title={`Edit ${client.name}`}>
        <Link href={`/clients/${client.id}`} className={buttonClass("secondary")}>
          Cancel
        </Link>
      </PageHeader>
      <ClientEditor
        client={client}
        submitLabel="Save changes"
        onSave={async (body) => {
          await updateClient(client.id, body);
          notify("success", "Client saved");
          router.push(`/clients/${client.id}`);
        }}
      />
    </>
  );
}
