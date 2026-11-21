"use client";

import { useRouter } from "next/navigation";

import { Alert, BackLink, PageHeader } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";
import { createClient } from "@/services/clients";

import { ClientEditor } from "../client-editor";

export default function NewClientPage() {
  const router = useRouter();
  const { data: user } = useLoad("me", me);

  if (user && user.role !== "super_admin") {
    return (
      <>
        <PageHeader title="Add client" />
        <Alert kind="info">Only a super admin can add clients.</Alert>
      </>
    );
  }

  return (
    <>
      <BackLink href="/clients">All clients</BackLink>
      <PageHeader title="Add client" subtitle="A company you're hiring for." />
      <ClientEditor
        submitLabel="Add client →"
        onSave={async (body) => {
          const client = await createClient(body);
          router.push(`/clients/${client.id}`);
        }}
      />
    </>
  );
}
